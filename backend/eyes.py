"""Coarse, eye-relative iris observations. No screen gaze or attention decisions."""
import numpy as np

from .config import PerceptionConfig
from .observations import EyeMovement, HeadPose, IrisObservation

# MediaPipe subject-left/right eye and iris connections:
# https://github.com/google-ai-edge/mediapipe/blob/master/mediapipe/python/solutions/face_mesh_connections.py
# Corners run from image-left to image-right in unmirrored input.
EYES = {
    'eyeLeft': {'corners': (362, 263), 'upper': (385, 386, 387), 'lower': (380, 374, 373),
                'iris': (474, 475, 476, 477), 'blink': 'eyeBlinkLeft',
                'up': 'eyeLookUpLeft', 'down': 'eyeLookDownLeft'},
    'eyeRight': {'corners': (33, 133), 'upper': (160, 159, 158), 'lower': (144, 145, 153),
                 'iris': (469, 470, 471, 472), 'blink': 'eyeBlinkRight',
                 'up': 'eyeLookUpRight', 'down': 'eyeLookDownRight'},
}


def estimate_eye(landmarks, indices, blink, width, height, config, unavailable_reason=None, look_up=0, look_down=0):
    # Normalize the model's observed closure range continuously. The direction
    # classification must never force this numeric measurement to a binary value.
    score = (round(float(np.clip(blink / config.eye_blink_full_closure, 0, 1)), 4)
             if blink is not None and np.isfinite(blink) else None)
    if blink is not None and blink >= config.eye_blink_threshold:
        return IrisObservation(blink_score=score, direction='closed', reason='blink')
    if unavailable_reason:
        return IrisObservation(blink_score=score, reason=unavailable_reason)
    # Model signals corroborate vertical displacement; they cannot select a
    # vertical label when the iris is centered on the eye-corner line.
    vertical_signals = {
        'up': look_up if look_up >= config.eye_vertical_signal_threshold and
                        look_up - look_down >= config.eye_vertical_signal_margin else 0,
        'down': look_down if look_down >= config.eye_vertical_signal_threshold and
                            look_down - look_up >= config.eye_vertical_signal_margin else 0,
    }
    required = (*indices['corners'], *indices['upper'], *indices['lower'])
    if len(landmarks) <= max(required):
        return IrisObservation(blink_score=score, reason='missing_landmarks')
    points = np.array([(landmarks[i].x, landmarks[i].y) for i in required], dtype=float)
    if not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
        return IrisObservation(blink_score=score, reason='invalid_landmarks')
    points *= (width, height)
    corner, other = points[:2]
    upper, lower = points[2:5], points[5:8]
    horizontal_axis = other - corner
    eye_width = float(np.linalg.norm(horizontal_axis))
    if eye_width < 4:
        return IrisObservation(blink_score=score, reason='eye_too_small')
    horizontal_axis /= eye_width
    vertical_axis = np.array([-horizontal_axis[1], horizontal_axis[0]])
    # Three lid pairs reduce sensitivity to a single misplaced landmark.
    top = float(np.median((upper - corner) @ vertical_axis))
    bottom = float(np.median((lower - corner) @ vertical_axis))
    eye_height = bottom - top
    if eye_height < 0:
        return IrisObservation(blink_score=score, reason='invalid_eye_geometry')
    aperture = eye_height / eye_width
    if aperture < 0.06 or (aperture < 0.12 and not any(vertical_signals.values())):
        return IrisObservation(blink_score=score, direction='closed', reason='eye_closed')
    if len(landmarks) <= max(indices['iris']):
        return IrisObservation(blink_score=score, reason='missing_landmarks')
    iris_points = np.array([(landmarks[i].x, landmarks[i].y) for i in indices['iris']], dtype=float)
    if not np.isfinite(iris_points).all() or np.any(iris_points < 0) or np.any(iris_points > 1):
        return IrisObservation(blink_score=score, reason='invalid_landmarks')
    iris = (iris_points * (width, height)).mean(axis=0)
    x = float(np.dot(iris - corner, horizontal_axis) / eye_width)
    iris_height = float(np.dot(iris - corner, vertical_axis))
    y = float((iris_height - top) / eye_height)
    vertical_offset = iris_height / eye_width
    if not (-0.25 <= x <= 1.25 and -0.25 <= y <= 1.25):
        return IrisObservation(blink_score=score, reason='iris_outside_eye')
    x, y = float(np.clip(x, 0, 1)), float(np.clip(y, 0, 1))
    # Image-right corresponds to subject-left for an unmirrored frontal face.
    directions = {'left': (x - 0.5) / config.eye_horizontal_margin,
                  'right': (0.5 - x) / config.eye_horizontal_margin,
                  'up': -vertical_offset / config.eye_vertical_offset_threshold,
                  'down': vertical_offset / config.eye_vertical_offset_threshold}
    for name, strength in vertical_signals.items():
        # Qualified model evidence permits smaller measured excursions, but the
        # iris must move in the same direction. Absolute coefficients have no
        # assumed neutral value and cannot override centered geometry.
        if strength:
            directions[name] = max(directions[name], directions[name] * 2)

    direction = max(directions, key=directions.get)
    if directions[direction] < 1:
        direction = 'center'
    return IrisObservation(blink_score=score, direction=direction, horizontal=round(x, 4),
                           vertical=round(y, 4), vertical_offset=round(vertical_offset, 4), reason='usable')


def eye_movement_from_landmarks(landmarks, blendshapes, pose: HeadPose | None,
                               width: int, height: int, config: PerceptionConfig):
    # Roll is handled by eye-local axes. Eye-local geometry supports a wider head-angle range,
    # while extreme yaw/pitch still requires unknown rather than a forced label.
    if pose is None:
        reason = 'head_pose_unavailable'
    elif abs(pose.yaw) > config.eye_max_yaw_degrees or abs(pose.pitch) > config.eye_max_pitch_degrees:
        reason = 'head_turned'
    else:
        reason = None
    return EyeMovement(**{
        name: estimate_eye(landmarks, indices, blendshapes.get(indices['blink']),
                           width, height, config, unavailable_reason=reason,
                           look_up=blendshapes.get(indices['up'], 0),
                           look_down=blendshapes.get(indices['down'], 0))
        for name, indices in EYES.items()
    })
