"""Small validated observations; images never enter shared state."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class HeadPose(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, frozen=True)
    yaw: float
    pitch: float
    roll: float


class IrisObservation(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, frozen=True)
    direction: Literal['center', 'left', 'right', 'up', 'down', 'closed', 'unknown'] = 'unknown'
    blink_score: float | None = Field(default=None, ge=0, le=1)
    horizontal: float | None = Field(default=None, ge=0, le=1)
    vertical: float | None = Field(default=None, ge=0, le=1)
    vertical_offset: float | None = None
    reason: str = 'unavailable'


class EyeMovement(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    eyeLeft: IrisObservation = Field(default_factory=IrisObservation)
    eyeRight: IrisObservation = Field(default_factory=IrisObservation)


class Observation(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, frozen=True)
    observed_at: float
    processed_at: float
    presence: Literal['present', 'not_detected', 'unknown']
    reason: str = 'usable'
    brightness: float | None = None
    blur_variance: float | None = None
    head_pose: HeadPose | None = None
    face_box: tuple[float, float, float, float] | None = None
    blendshapes: dict[str, float] = Field(default_factory=dict)
    eye_movement: EyeMovement = Field(default_factory=EyeMovement)
