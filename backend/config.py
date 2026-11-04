"""Validated camera, perception and behaviour settings loaded by __main__."""
from dataclasses import dataclass
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.policy import PolicyConfig

ROOT = Path(__file__).resolve().parents[1]


class FiniteConfig(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)


class CameraConfig(FiniteConfig):
    width: int = Field(default=640, ge=64, le=1920)
    height: int = Field(default=480, ge=64, le=1080)
    fps: int = Field(default=10, ge=1, le=30)
    jpeg_quality: float = Field(default=0.75, ge=0.1, le=1)
    max_bytes: int = Field(default=524288, ge=1024, le=2097152)
    timeout_seconds: float = Field(default=3, ge=0.1, le=60)
    startup_seconds: float = Field(default=30, ge=1, le=120)
    model_path: Path = ROOT / 'models/face_landmarker.task'

    @classmethod
    def from_env(cls, environ=None):
        return settings_from_env(cls, 'POMO_CAMERA_', environ)

    def browser_settings(self):
        return self.model_dump(exclude={'model_path'})


def settings_from_env(cls, prefix, environ=None):
    environ = os.environ if environ is None else environ
    return cls(**{name: environ[f'{prefix}{name.upper()}']
                  for name in cls.model_fields if f'{prefix}{name.upper()}' in environ})


class PerceptionConfig(FiniteConfig):
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
    def from_env(cls, environ=None):
        return settings_from_env(cls, 'POMO_PERCEPTION_', environ)


class BehaviourConfig(FiniteConfig):
    tracking_loss_grace_seconds: float = Field(default=1, ge=0, le=30)
    absence_seconds: float = Field(default=5, gt=0, le=3600)
    return_seconds: float = Field(default=0.5, ge=0, le=30)
    observation_max_age_seconds: float = Field(default=1, gt=0, le=60)

    @model_validator(mode='after')
    def ordered_durations(self):
        if self.tracking_loss_grace_seconds > self.absence_seconds:
            raise ValueError('tracking loss grace must not exceed absence duration')
        return self

    @classmethod
    def from_env(cls, environ=None):
        return settings_from_env(cls, 'POMO_', environ)


def _boolean(environ, name, default):
    value = environ.get(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def _number(environ, name, default):
    try:
        return float(environ.get(name, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a finite number") from error


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    dev_controls: bool
    sound_enabled: bool
    policy: PolicyConfig
    camera: CameraConfig
    perception: PerceptionConfig
    behaviour: BehaviourConfig

    @classmethod
    def from_env(cls, environ=None):
        environ = os.environ if environ is None else environ
        host = environ.get("POMO_HOST", "127.0.0.1").strip()
        if not host:
            raise ValueError("POMO_HOST must not be empty")
        try:
            port = int(environ.get("POMO_PORT", "8000"))
        except (TypeError, ValueError) as error:
            raise ValueError("POMO_PORT must be an integer between 1 and 65535") from error
        if not 1 <= port <= 65535:
            raise ValueError("POMO_PORT must be between 1 and 65535")
        return cls(
            host=host, port=port,
            camera=CameraConfig.from_env(environ),
            perception=PerceptionConfig.from_env(environ),
            behaviour=BehaviourConfig.from_env(environ),
            dev_controls=_boolean(environ, "POMO_DEV_CONTROLS", "true"),
            sound_enabled=_boolean(environ, "POMO_SOUND_ENABLED", "false"),
            policy=PolicyConfig(
                absence_seconds=_number(environ, "POMO_ABSENCE_SECONDS", "5"),
                cooldown_seconds=_number(environ, "POMO_REMINDER_COOLDOWN_SECONDS", "30"),
                observation_timeout_seconds=_number(environ, "POMO_OBSERVATION_TIMEOUT_SECONDS", "3"),
            ),
        )
