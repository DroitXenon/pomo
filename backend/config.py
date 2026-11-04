"""Validated environment configuration without import-time side effects."""

from dataclasses import dataclass
import os

from backend.policy import PolicyConfig


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
            dev_controls=_boolean(environ, "POMO_DEV_CONTROLS", "true"),
            sound_enabled=_boolean(environ, "POMO_SOUND_ENABLED", "false"),
            policy=PolicyConfig(
                absence_seconds=_number(environ, "POMO_ABSENCE_SECONDS", "5"),
                cooldown_seconds=_number(environ, "POMO_REMINDER_COOLDOWN_SECONDS", "30"),
                observation_timeout_seconds=_number(environ, "POMO_OBSERVATION_TIMEOUT_SECONDS", "3"),
            ),
        )
