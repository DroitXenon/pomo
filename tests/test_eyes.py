"""Synthetic iris geometry in unmirrored input; no camera or model required."""
from types import SimpleNamespace
import math

import numpy as np
import pytest

from backend.config import PerceptionConfig
from backend.eyes import EYES, eye_movement_from_landmarks
from backend.observations import EyeMovement, HeadPose, Observation
from backend.perception import FacePerception


def landmarks(eye_positions=None, roll=0, scale=1):
    positions = eye_positions or {}
    points = [SimpleNamespace(x=0.5, y=0.5) for _ in range(478)]
    for name, indices in EYES.items():
        start = 0.60 if name == 'eyeLeft' else 0.25
        width, top, height = 0.12, 0.46, 0.08
        x, y = positions.get(name, (0.5, 0.5))
        coordinates = [(start, 0.5), (start + width, 0.5)]
        coordinates += [(start + width * fraction, top) for fraction in (0.25, 0.5, 0.75)]
        coordinates += [(start + width * fraction, top + height) for fraction in (0.25, 0.5, 0.75)]
        cx, cy = start + width * x, top + height * y
        coordinates += [(cx - 0.004, cy), (cx, cy - 0.004),
                        (cx + 0.004, cy), (cx, cy + 0.004)]
        ids = (*indices['corners'], *indices['upper'], *indices['lower'], *indices['iris'])
        for index, (px, py) in zip(ids, coordinates):
            # Rotate in pixel coordinates so non-square frame geometry is tested.
            dx, dy = (px - 0.5) * 640 * scale, (py - 0.5) * 480 * scale
            angle = math.radians(roll)
            points[index] = SimpleNamespace(
                x=0.5 + (dx * math.cos(angle) - dy * math.sin(angle)) / 640,
                y=0.5 + (dx * math.sin(angle) + dy * math.cos(angle)) / 480)
    return points


def estimate(points, shapes=None, pose=None, **settings):
    return eye_movement_from_landmarks(points, shapes or {}, pose or HeadPose(yaw=0,pitch=0,roll=0),
                                      640, 480, PerceptionConfig(**settings))


@pytest.mark.parametrize('eye', ['eyeLeft', 'eyeRight'])
@pytest.mark.parametrize('position,direction', [
    ((0.5, 0.5), 'center'), ((0.8, 0.5), 'left'), ((0.2, 0.5), 'right'),
    ((0.5, 0.15), 'up'), ((0.5, 0.85), 'down')])
def test_each_iris_direction_is_subject_relative(eye, position, direction):
    result = estimate(landmarks({eye: position}))
    observation = getattr(result, eye)
    assert observation.direction == direction
    assert observation.horizontal == pytest.approx(position[0])
    assert observation.vertical == pytest.approx(position[1])
    other = 'eyeRight' if eye == 'eyeLeft' else 'eyeLeft'
    assert getattr(result, other).direction == 'center'


@pytest.mark.parametrize('roll,scale', [(30, 1), (-25, 0.7), (0, 1.2)])
def test_eye_local_coordinates_handle_roll_and_scale(roll, scale):
    result = estimate(landmarks({'eyeLeft': (0.8, 0.5), 'eyeRight': (0.5, 0.15)}, roll, scale))
    assert result.eyeLeft.direction == 'left'
    assert result.eyeRight.direction == 'up'


def test_blink_only_suppresses_the_affected_eye():
    result = estimate(landmarks(), {'eyeBlinkLeft': 0.9, 'eyeBlinkRight': 0.1})
    assert result.eyeLeft.direction == 'closed' and result.eyeLeft.reason == 'blink'
    assert result.eyeRight.direction == 'center'
    # There is no retained eye direction after a blink; observations are per-frame.
    assert estimate(landmarks({'eyeLeft': (0.2, 0.5)})).eyeLeft.direction == 'right'


def test_closed_eye_without_blink_score_uses_lid_geometry():
    points = landmarks()
    for index in EYES['eyeLeft']['upper']:
        points[index].y = 0.499
    for index in EYES['eyeLeft']['lower']:
        points[index].y = 0.501
    result = estimate(points)
    assert result.eyeLeft.direction == 'closed'
    assert result.eyeLeft.reason == 'eye_closed'
    assert result.eyeRight.direction == 'center'


@pytest.mark.parametrize('yaw,pitch', [(65, 0), (0, 50)])
def test_strong_head_turn_does_not_masquerade_as_eye_movement(yaw, pitch):
    result = estimate(landmarks(), pose=HeadPose(yaw=yaw, pitch=pitch, roll=0))
    assert result.eyeLeft.reason == result.eyeRight.reason == 'head_turned'
    assert result.eyeLeft.direction == result.eyeRight.direction == 'unknown'


def test_missing_or_invalid_geometry_is_unknown():
    assert estimate(landmarks()[:468]).eyeLeft.reason == 'missing_landmarks'
    points = landmarks()
    points[474].x = float('nan')
    assert estimate(points).eyeLeft.reason == 'invalid_landmarks'
    points = landmarks()
    points[263] = points[362]
    assert estimate(points).eyeLeft.reason == 'eye_too_small'


def test_unknown_observation_has_no_stale_iris_direction():
    observation = Observation(observed_at=1, processed_at=1, presence='unknown')
    assert observation.eye_movement == EyeMovement()
    with pytest.raises(ValueError):
        Observation(observed_at=1, processed_at=1, presence='present',
                    eye_movement={'eyeLeft': {'direction':'distracted'}})


def test_real_analysis_path_uses_iris_landmarks_and_preserves_mouth_scores():
    detector = object.__new__(FacePerception)
    detector.config = PerceptionConfig()
    detector.timestamp_ms = -1
    result = SimpleNamespace(face_landmarks=[landmarks({'eyeLeft': (0.8,0.5)})],
        facial_transformation_matrixes=[np.eye(4)],
        face_blendshapes=[[SimpleNamespace(category_name='jawOpen', score=0.25),
                          SimpleNamespace(category_name='eyeBlinkLeft', score=0.1)]])
    detector.model = SimpleNamespace(detect_for_video=lambda *_: result)
    rgb = np.random.default_rng(3).integers(40,200,(48,64,3),dtype=np.uint8)
    output = detector.analyse(rgb)
    assert output['eye_movement']['eyeLeft']['direction'] == 'left'
    assert output['eye_movement']['eyeRight']['direction'] == 'center'
    assert output['blendshapes']['jawOpen'] == 0.25


@pytest.mark.parametrize('yaw,pitch', [(45,0),(-55,0),(0,35),(0,-40),(60,45)])
def test_wider_head_angle_range_keeps_valid_iris_observations(yaw, pitch):
    result = estimate(landmarks({'eyeLeft':(0.8,0.5),'eyeRight':(0.2,0.5)}),
                      pose=HeadPose(yaw=yaw,pitch=pitch,roll=0))
    assert result.eyeLeft.direction == 'left'
    assert result.eyeRight.direction == 'right'


@pytest.mark.parametrize('score', [0.55,0.60,0.65,0.70])
def test_observed_closed_eye_blink_range_suppresses_iris_direction(score):
    result = estimate(landmarks(), {'eyeBlinkLeft':score,'eyeBlinkRight':0.1})
    assert result.eyeLeft.reason == 'blink'
    assert result.eyeRight.direction == 'center'


def test_single_lid_landmark_error_does_not_change_direction():
    points = landmarks({'eyeLeft':(0.8,0.5)})
    points[385].y = 0.499
    result = estimate(points)
    assert result.eyeLeft.direction == 'left'


def test_configured_angle_and_blink_limits_are_respected():
    result = estimate(landmarks(),pose=HeadPose(yaw=50,pitch=0,roll=0),eye_max_yaw_degrees=40)
    assert result.eyeLeft.reason == 'head_turned'
    assert estimate(landmarks(), {'eyeBlinkLeft':0.6},eye_blink_threshold=0.7).eyeLeft.direction == 'center'


def test_closed_eye_scores_are_exported_without_rescaling():
    result = SimpleNamespace(face_landmarks=[landmarks()],
        facial_transformation_matrixes=[np.eye(4)],
        face_blendshapes=[[SimpleNamespace(category_name='eyeBlinkLeft',score=0.60),
                          SimpleNamespace(category_name='eyeBlinkRight',score=0.70)]])
    output = FacePerception.observation_from_result(result,{})
    assert output['blendshapes'] == {'eyeBlinkLeft':0.60,'eyeBlinkRight':0.70}
    eyes = estimate(result.face_landmarks[0],output['blendshapes'])
    assert eyes.eyeLeft.reason == eyes.eyeRight.reason == 'blink'


def test_blink_reports_closed_even_when_head_direction_is_unavailable():
    result = estimate(landmarks(), {'eyeBlinkLeft':0.6},pose=HeadPose(yaw=70,pitch=0,roll=0))
    assert result.eyeLeft.direction == 'closed'
    assert result.eyeRight.direction == 'unknown'
    assert result.eyeRight.reason == 'head_turned'


def test_closed_lids_do_not_require_visible_iris_landmarks():
    points = landmarks()[:468]
    for index in EYES['eyeLeft']['upper']:
        points[index].y=0.499
    for index in EYES['eyeLeft']['lower']:
        points[index].y=0.501
    result=estimate(points)
    assert result.eyeLeft.direction == 'closed'
    assert result.eyeRight.direction == 'unknown'


def test_invalid_lid_order_is_not_reported_closed():
    points=landmarks()
    for index in EYES['eyeLeft']['upper']:
        points[index].y=0.6
    result=estimate(points)
    assert result.eyeLeft.direction == 'unknown'
    assert result.eyeLeft.reason == 'invalid_eye_geometry'


@pytest.mark.parametrize('raw,expected', [(0,0),(0.12,0.2),(0.30,0.5),(0.48,0.8),
                                         (0.54,0.9),(0.55,0.9167),(0.57,0.95),(0.60,1),(0.70,1)])
def test_blink_score_rises_continuously_with_model_closure(raw,expected):
    eye=estimate(landmarks(),{'eyeBlinkLeft':raw}).eyeLeft
    assert eye.blink_score == pytest.approx(expected)
    assert eye.direction == ('closed' if raw>=0.55 else 'center')


def test_closed_label_and_geometry_do_not_force_blink_score_to_one():
    points=landmarks()
    for index in EYES['eyeLeft']['upper']:
        points[index].y=0.499
    for index in EYES['eyeLeft']['lower']:
        points[index].y=0.501
    eye=estimate(points,{'eyeBlinkLeft':0.30}).eyeLeft
    assert eye.direction == 'closed'
    assert eye.blink_score == 0.5
    assert estimate(points).eyeLeft.blink_score is None


def test_full_closure_reference_is_configurable_and_missing_input_is_unknown():
    assert estimate(landmarks(),{'eyeBlinkLeft':0.5},eye_blink_full_closure=0.8).eyeLeft.blink_score==0.625
    assert estimate(landmarks()).eyeLeft.blink_score is None


@pytest.mark.parametrize('eye', ['eyeLeft','eyeRight'])
@pytest.mark.parametrize('direction,offset', [('up',-0.02),('down',0.02)])
def test_vertical_model_signals_detect_iris_and_lids_moving_together(eye,direction,offset):
    points=landmarks()
    indices=EYES[eye]
    for index in (*indices['upper'],*indices['lower'],*indices['iris']):
        points[index].y+=offset
    # Eye-corner anchoring preserves vertical motion even when lids follow iris.
    assert getattr(estimate(points),eye).direction==direction
    shapes={indices[direction]:0.7,indices['blink']:0.1}
    observation=getattr(estimate(points,shapes),eye)
    assert observation.direction==direction
    assert observation.vertical==pytest.approx(0.5)


def test_ambiguous_or_weak_vertical_signals_do_not_create_direction():
    shapes={'eyeLookUpLeft':0.6,'eyeLookDownLeft':0.58}
    assert estimate(landmarks(),shapes).eyeLeft.direction=='center'
    assert estimate(landmarks(),{'eyeLookUpLeft':0.2}).eyeLeft.direction=='center'


def test_looking_down_with_narrow_open_lids_is_not_classified_closed():
    points=landmarks()
    for index in EYES['eyeLeft']['upper']:
        points[index].y=0.492
    for index in EYES['eyeLeft']['lower']:
        points[index].y=0.508
    for index in EYES['eyeLeft']['iris']:
        points[index].y+=0.007
    result=estimate(points,{'eyeLookDownLeft':0.7,'eyeBlinkLeft':0.1})
    assert result.eyeLeft.direction=='down'
    assert estimate(points).eyeLeft.direction=='closed'


def test_vertical_signals_do_not_override_a_detected_blink():
    result=estimate(landmarks(),{'eyeLookUpLeft':0.9,'eyeBlinkLeft':0.6})
    assert result.eyeLeft.direction=='closed'


def test_perception_exports_vertical_eye_signals():
    result=SimpleNamespace(face_landmarks=[landmarks()],facial_transformation_matrixes=[np.eye(4)],
        face_blendshapes=[[SimpleNamespace(category_name=name,score=score) for name,score in
            [('eyeLookUpLeft',0.7),('eyeLookDownLeft',0.1),('eyeLookUpRight',0.1),('eyeLookDownRight',0.6)]]])
    output=FacePerception.observation_from_result(result,{})
    assert output['blendshapes']['eyeLookUpLeft']==0.7
    points=result.face_landmarks[0]
    for index in EYES['eyeLeft']['iris']:
        points[index].y-=0.008
    for index in EYES['eyeRight']['iris']:
        points[index].y+=0.008
    eyes=estimate(points,output['blendshapes'])
    assert eyes.eyeLeft.direction=='up'
    assert eyes.eyeRight.direction=='down'


@pytest.mark.parametrize('eye',['eyeLeft','eyeRight'])
def test_asymmetric_lids_do_not_label_a_centered_iris_up(eye):
    points=landmarks()
    indices=EYES[eye]
    for index in indices['upper']:
        points[index].y=0.49
    for index in indices['lower']:
        points[index].y=0.56
    # Iris is above the lid-opening midpoint, but centered on stable corners.
    result=getattr(estimate(points,{indices['up']:0.7}),eye)
    assert result.vertical < 0.3
    assert result.vertical_offset == pytest.approx(0)
    assert result.direction=='center'


@pytest.mark.parametrize('eye',['eyeLeft','eyeRight'])
def test_upward_iris_motion_is_up_even_when_lid_relative_position_stays_center(eye):
    points=landmarks()
    indices=EYES[eye]
    for index in (*indices['upper'],*indices['lower'],*indices['iris']):
        points[index].y-=0.02
    result=getattr(estimate(points),eye)
    assert result.vertical==pytest.approx(0.5)
    assert result.vertical_offset < -0.08
    assert result.direction=='up'


def test_wrong_way_model_signal_cannot_override_iris_displacement():
    points=landmarks({'eyeLeft':(0.5,0.85)})
    result=estimate(points,{'eyeLookUpLeft':0.9})
    assert result.eyeLeft.direction=='down'


def test_centered_iris_is_not_up_from_model_signal_alone():
    assert estimate(landmarks(),{'eyeLookUpLeft':0.9}).eyeLeft.direction=='center'
