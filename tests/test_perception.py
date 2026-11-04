from types import SimpleNamespace
import math

import numpy as np
import pytest

from backend.config import PerceptionConfig
from backend.observations import HeadPose, Observation
from backend.perception import FacePerception, HeadDirection, pose_from_matrix


def rotation(yaw=0, pitch=0, roll=0):
    y, p, r = map(math.radians, (yaw, pitch, roll))
    ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    matrix = np.eye(4)
    matrix[:3, :3] = 2 * rz @ ry @ rx
    return matrix


def test_head_angles_remove_scale_and_recover_known_rotation():
    pose = pose_from_matrix(rotation(35, -20, 10))
    assert pose.yaw == pytest.approx(35)
    assert pose.pitch == pytest.approx(-20)
    assert pose.roll == pytest.approx(10)


@pytest.mark.parametrize('matrix', [np.zeros((4, 4)), np.full((4, 4), np.nan), np.eye(3)])
def test_invalid_pose_does_not_invent_head_direction(matrix):
    assert pose_from_matrix(matrix) is None


def test_head_direction_hysteresis_and_loss():
    head = HeadDirection(PerceptionConfig())
    pose = lambda yaw=0, pitch=0: HeadPose(yaw=yaw, pitch=pitch, roll=0)
    assert head.classify(pose()) == 'forward'
    assert head.classify(pose(35)) == 'left'
    assert head.classify(pose(27)) == 'left'
    assert head.classify(pose(24)) == 'forward'
    assert head.classify(pose(-35)) == 'right'
    assert head.classify(pose(0, 30)) == 'down'
    assert head.classify(pose(0, -30)) == 'up'
    assert head.classify(None) == 'unknown'
    head.reset()
    assert head.classify(pose()) == 'forward'


@pytest.mark.parametrize('level,reason', [(0, 'low_light'), (255, 'overexposed'),
                                         (128, 'low_detail_or_blur')])
def test_poor_quality_is_unknown_without_running_inference(level, reason):
    detector = object.__new__(FacePerception)
    detector.config = PerceptionConfig(min_blur_variance=15)
    result = detector.analyse(np.full((48, 64, 3), level, dtype=np.uint8))
    assert result['presence'] == 'unknown' and result['reason'] == reason


def test_model_output_conversion_keeps_expression_scores_separate_from_presence():
    result = SimpleNamespace(
        face_landmarks=[[SimpleNamespace(x=0.2, y=0.1), SimpleNamespace(x=0.8, y=0.9)]],
        facial_transformation_matrixes=[rotation()],
        face_blendshapes=[[SimpleNamespace(category_name='jawOpen', score=0.9),
                          SimpleNamespace(category_name='eyeBlinkLeft', score=0.2)]])
    output = FacePerception.observation_from_result(result, {})
    assert output['presence'] == 'present'
    assert output['blendshapes']['jawOpen'] == 0.9
    assert output['face_box'] == (0.2, 0.1, 0.8, 0.9)
    assert output['head_pose']['yaw'] == pytest.approx(0)
    result.face_landmarks = []
    assert FacePerception.observation_from_result(result, {})['presence'] == 'not_detected'


def test_observation_rejects_nonfinite_values_and_invalid_presence():
    with pytest.raises(ValueError):
        Observation(observed_at=float('nan'), processed_at=1, presence='present')
    with pytest.raises(ValueError):
        Observation(observed_at=1, processed_at=1, presence='distracted')


def test_automatic_direction_does_not_learn_first_turned_face_as_forward():
    head = HeadDirection(PerceptionConfig())
    assert head.classify(HeadPose(yaw=45, pitch=0, roll=0)) == 'left'
    assert head.classify(HeadPose(yaw=0, pitch=0, roll=0)) == 'forward'
    assert head.classify(None) == 'unknown'
    head.reset()
    assert head.classify(HeadPose(yaw=-45, pitch=0, roll=0)) == 'right'



def test_default_blur_threshold_accepts_moderate_detail_but_rejects_flat_frames():
    detector = object.__new__(FacePerception)
    detector.config = PerceptionConfig()
    detector.timestamp_ms = -1
    calls = []
    def detect(image, timestamp):
        calls.append(timestamp)
        return SimpleNamespace(face_landmarks=[])
    detector.model = SimpleNamespace(detect_for_video=detect)
    gray = np.random.default_rng(8).integers(127,130,(48,64),dtype=np.uint8)
    rgb = np.repeat(gray[:,:,None],3,axis=2)
    result = detector.analyse(rgb)
    assert len(calls) == 1
    assert 5 <= result['blur_variance'] < 15
    assert result['presence'] == 'not_detected'
    assert result['reason'] == 'no_face'
    rejected = detector.analyse(np.full((48,64,3),128,dtype=np.uint8))
    assert len(calls) == 1
    assert rejected['presence'] == 'unknown'
    assert rejected['reason'] == 'low_detail_or_blur'
