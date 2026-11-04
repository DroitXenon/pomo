"""Validated camera, perception and behaviour settings loaded by __main__."""
import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]


class CameraConfig(BaseModel):
    width: int = Field(default=640, ge=64, le=1920)
    height: int = Field(default=480, ge=64, le=1080)
    fps: int = Field(default=10, ge=1, le=30)
    jpeg_quality: float = Field(default=0.75, ge=0.1, le=1)
    max_bytes: int = Field(default=524288, ge=1024, le=2097152)
    timeout_seconds: float = Field(default=3, ge=0.1, le=60)
    startup_seconds: float = Field(default=30, ge=1, le=120)
    model_path: Path = ROOT / 'models/face_landmarker.task'

    @classmethod
    def from_env(cls):
        return settings_from_env(cls, 'POMO_CAMERA_')

    def browser_settings(self):
        return self.model_dump(exclude={'model_path'})


def settings_from_env(cls, prefix):
    return cls(**{name: os.environ[f'{prefix}{name.upper()}']
                  for name in cls.model_fields if f'{prefix}{name.upper()}' in os.environ})


class PerceptionConfig(BaseModel):
    detection_confidence: float = Field(default=0.5, ge=0, le=1)
    presence_confidence: float = Field(default=0.5, ge=0, le=1)
    tracking_confidence: float = Field(default=0.5, ge=0, le=1)
    min_brightness: float = Field(default=35, ge=0, le=255)
    max_brightness: float = Field(default=230, ge=0, le=255)
    min_blur_variance: float = Field(default=5, ge=0)
    yaw_degrees: float = Field(default=30, ge=10, le=80)
    pitch_degrees: float = Field(default=25, ge=10, le=80)
    hysteresis_degrees: float = Field(default=5, ge=0, lt=10)

    eye_horizontal_margin: float = Field(default=0.15, ge=0.05, le=0.45)
    eye_vertical_offset_threshold: float = Field(default=0.08, ge=0.02, le=0.30)
    eye_vertical_signal_threshold: float = Field(default=0.30, ge=0.05, le=1)
    eye_vertical_signal_margin: float = Field(default=0.10, ge=0, le=1)
    eye_blink_threshold: float = Field(default=0.55, ge=0, le=1)
    eye_blink_full_closure: float = Field(default=0.60, ge=0.05, le=1)
    eye_max_yaw_degrees: float = Field(default=60, ge=0, le=80)
    eye_max_pitch_degrees: float = Field(default=45, ge=0, le=80)

    @model_validator(mode='after')
    def ordered_brightness(self):
        if self.min_brightness >= self.max_brightness:
            raise ValueError('min_brightness must be below max_brightness')
        return self

    @classmethod
    def from_env(cls):
        return settings_from_env(cls, 'POMO_PERCEPTION_')


class BehaviourConfig(BaseModel):
    tracking_loss_grace_seconds: float = Field(default=1, ge=0, le=30)
    absence_seconds: float = Field(default=10, gt=0, le=3600)
    return_seconds: float = Field(default=0.5, ge=0, le=30)
    observation_max_age_seconds: float = Field(default=1, gt=0, le=60)

    @model_validator(mode='after')
    def ordered_durations(self):
        if self.tracking_loss_grace_seconds > self.absence_seconds:
            raise ValueError('tracking loss grace must not exceed absence duration')
        return self

    @classmethod
    def from_env(cls):
        return settings_from_env(cls, 'POMO_')
