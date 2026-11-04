"""MediaPipe observations and diagnostic head pose, without reminder decisions."""
import math
import time

import cv2
import numpy as np

from .config import PerceptionConfig
from .observations import HeadPose
from .eyes import eye_movement_from_landmarks

MOVEMENT_NAMES = {'eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen',
                  'mouthSmileLeft', 'mouthSmileRight', 'eyeLookUpLeft',
                  'eyeLookUpRight', 'eyeLookDownLeft', 'eyeLookDownRight'}


def pose_from_matrix(matrix):
    """Remove uniform scale, then extract XYZ Euler angles in degrees."""
    rotation = np.asarray(matrix, dtype=float)
    if rotation.shape != (4, 4) or not np.isfinite(rotation).all():
        return None
    rotation = rotation[:3, :3]
    u, singular, vt = np.linalg.svd(rotation)
    if singular.min() < 1e-6:
        return None
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        return None
    # MediaPipe metric coordinates: right-handed, camera looking down -Z.
    yaw = math.atan2(-rotation[2, 0], math.hypot(rotation[0, 0], rotation[1, 0]))
    pitch = math.atan2(rotation[2, 1], rotation[2, 2])
    roll = math.atan2(rotation[1, 0], rotation[0, 0])
    return HeadPose(yaw=math.degrees(yaw), pitch=math.degrees(pitch), roll=math.degrees(roll))


class HeadDirection:
    def __init__(self, config: PerceptionConfig):
        self.config = config
        self.reset()

    def reset(self):
        self.direction = 'unknown'

    def classify(self, pose: HeadPose | None):
        if pose is None:
            self.direction = 'unknown'
            return self.direction
        # Camera-facing canonical pose is the reference for every session.
        yaw = (pose.yaw + 180) % 360 - 180
        pitch = (pose.pitch + 180) % 360 - 180
        c = self.config
        candidates = {'left': yaw, 'right': -yaw, 'down': pitch, 'up': -pitch}
        thresholds = {'left': c.yaw_degrees, 'right': c.yaw_degrees,
                      'down': c.pitch_degrees, 'up': c.pitch_degrees}
        previous = self.direction
        if previous in candidates and candidates[previous] >= thresholds[previous] - c.hysteresis_degrees:
            return previous
        candidate = max(candidates, key=lambda key: candidates[key] / thresholds[key])
        self.direction = candidate if candidates[candidate] >= thresholds[candidate] else 'forward'
        return self.direction


class FacePerception:
    """Created, called and closed on the same long-lived processing thread."""
    def __init__(self, config: PerceptionConfig, model_path):
        import mediapipe as mp
        self.config = config
        self.timestamp_ms = -1
        self.model = mp.tasks.vision.FaceLandmarker.create_from_options(
            mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=1, output_face_blendshapes=True,
                output_facial_transformation_matrixes=True,
                min_face_detection_confidence=config.detection_confidence,
                min_face_presence_confidence=config.presence_confidence,
                min_tracking_confidence=config.tracking_confidence))

    def analyse(self, rgb):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        brightness = float(gray.mean())
        blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        metrics = {'brightness': round(brightness, 2), 'blur_variance': round(blur, 2)}
        reason = ('low_light' if brightness < self.config.min_brightness else
                  'overexposed' if brightness > self.config.max_brightness else
                  'low_detail_or_blur' if blur < self.config.min_blur_variance else None)
        if reason:
            return dict(presence='unknown', reason=reason, **metrics)
        import mediapipe as mp
        self.timestamp_ms = max(self.timestamp_ms + 1, int(time.monotonic() * 1000))
        result = self.model.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), self.timestamp_ms)
        observation = self.observation_from_result(result, metrics)
        if observation['presence'] == 'present':
            pose = HeadPose(**observation['head_pose']) if observation['head_pose'] else None
            observation['eye_movement'] = eye_movement_from_landmarks(
                result.face_landmarks[0], observation['blendshapes'], pose,
                rgb.shape[1], rgb.shape[0], self.config).model_dump()
        return observation

    @staticmethod
    def observation_from_result(result, metrics):
        if not result.face_landmarks:
            return dict(presence='not_detected', reason='no_face', **metrics)
        landmarks = result.face_landmarks[0]
        xs, ys = [point.x for point in landmarks], [point.y for point in landmarks]
        if not xs or not np.isfinite(xs + ys).all():
            return dict(presence='unknown', reason='invalid_landmarks', **metrics)
        box = tuple(float(np.clip(v, 0, 1)) for v in (min(xs), min(ys), max(xs), max(ys)))
        matrices = result.facial_transformation_matrixes
        pose = pose_from_matrix(matrices[0]) if len(matrices) else None
        shapes = result.face_blendshapes
        blendshapes = {category.category_name: round(float(category.score), 4)
                       for category in (shapes[0] if shapes else [])
                       if category.category_name in MOVEMENT_NAMES and math.isfinite(category.score)}
        return dict(presence='present', reason='usable', face_box=box,
                    head_pose=pose.model_dump() if pose else None,
                    blendshapes=blendshapes, **metrics)

    def close(self):
        self.model.close()
