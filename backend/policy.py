"""Camera-independent state and reminder policy with injectable clocks."""

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import time
from typing import Callable
from uuid import uuid4


DISPLAYS = frozenset({"ready", "shutdown", "distraction", "reminding", "unavailable"})
PRESENCES = frozenset({"present", "absent", "unknown", "unavailable"})
SOURCES = frozenset({"simulated", "camera"})
REMINDER_MESSAGE = "Ready to return to your study session?"


@dataclass(frozen=True)
class PolicyConfig:
    absence_seconds: float = 5.0
    cooldown_seconds: float = 30.0
    observation_timeout_seconds: float = 3.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"{name} must be finite")
            if value < 0 or (name != "cooldown_seconds" and value == 0):
                raise ValueError(f"{name} must be positive" if name != "cooldown_seconds"
                                 else "cooldown_seconds must be non-negative")


class ReminderEngine:
    """Owns behaviour, independently of WebSockets, camera devices or rendering.

    ``observed_at`` is a source Unix timestamp. Freshness after receipt uses the
    monotonic clock, including any age the observation already had on arrival.
    A session token invalidates buffered observations across lifecycle changes.
    Call ``tick`` regularly to expire observations and evaluate reminder timing.
    """

    def __init__(self, config: PolicyConfig | None = None, *,
                 clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time,
                 initially_muted: bool = True):
        self.config = config or PolicyConfig()
        self._clock = clock
        self._wall_clock = wall_clock
        self.powered_on = True
        self.monitoring_enabled = False
        self.muted = self._boolean(initially_muted, "initially_muted")
        self.behavior_state = "ready"
        self._preview = None
        self.camera_status = "unavailable"
        self.observation_session = uuid4().hex
        self._presence = "unknown"
        self._source = "none"
        self._observed_at = None
        self._received_at = None
        self._initial_age = 0.0
        self._expires_at = None
        self._absence_started_at = None
        self._cooldown_until = 0.0
        self._reminder_active = False
        self._reminder_id = 0
        self._events = deque(maxlen=100)
        self._event_id = 0

    @staticmethod
    def _boolean(value, name):
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean")
        return value

    def record(self, kind: str, message: str, level: str = "info") -> dict:
        if level not in {"info", "warning", "error"}:
            raise ValueError("Unknown event level")
        self._event_id += 1
        event = {
            "id": self._event_id,
            "at": datetime.fromtimestamp(self._wall_clock(), timezone.utc).isoformat(),
            "level": level,
            "kind": str(kind)[:64],
            "message": str(message)[:300],
        }
        self._events.append(event)
        return dict(event)

    def _transition(self, state, reason):
        if state == self.behavior_state:
            return False
        previous = self.behavior_state
        self.behavior_state = state
        self.record("state_changed", f"{previous} -> {state}: {reason}")
        return True

    def _clear_reminder(self, reason):
        if self._reminder_active:
            self._reminder_active = False
            self.record("reminder_cleared", reason)

    def _reset_observations(self):
        self._presence = "unknown"
        self._source = "none"
        self._observed_at = None
        self._received_at = None
        self._initial_age = 0.0
        self._expires_at = None
        self._absence_started_at = None
        self.camera_status = "unavailable"

    def _resting_state(self):
        if not self.powered_on:
            return "shutdown"
        return "unavailable" if self.monitoring_enabled else "ready"

    def invalidate_observations(self, reason: str, level: str = "warning"):
        self._clear_reminder(reason)
        self._reset_observations()
        self.observation_session = uuid4().hex
        self._transition(self._resting_state(), reason)
        self.record("observations_invalidated", reason, level)
        return True

    def set_monitoring(self, enabled: bool):
        enabled = self._boolean(enabled, "enabled")
        if enabled and not self.powered_on:
            raise ValueError("Power on Pomo before enabling monitoring")
        if enabled == self.monitoring_enabled:
            return False
        self.monitoring_enabled = enabled
        self._preview = None
        reason = "Monitoring enabled" if enabled else "Monitoring paused"
        self.invalidate_observations(reason, level="info")
        self.record("monitoring_changed", reason)
        return True

    def set_power(self, enabled: bool):
        enabled = self._boolean(enabled, "enabled")
        if enabled == self.powered_on:
            return False
        self.powered_on = enabled
        self.monitoring_enabled = False
        self._preview = None
        self._cooldown_until = 0.0
        reason = "Pomo powered on; monitoring paused" if enabled else "Pomo shut down"
        self.invalidate_observations(reason, level="info")
        self.record("power_changed", reason)
        return True

    def set_muted(self, muted: bool):
        muted = self._boolean(muted, "muted")
        if muted == self.muted:
            return False
        self.muted = muted
        self.record("sound_changed", "Sound muted" if muted else "Sound enabled")
        return True

    def preview(self, display: str):
        if display not in DISPLAYS:
            raise ValueError("Unknown display preview")
        if not self.powered_on or self.monitoring_enabled:
            raise ValueError("Display previews require power on and monitoring paused")
        if self._preview == display:
            return False
        self._preview = display
        self.record("display_preview", f"Previewing {display}")
        return True

    def clear_preview(self):
        if self._preview is None:
            return False
        self._preview = None
        self.record("display_preview", "Display preview cleared")
        return True

    def observe(self, presence: str, source: str, observed_at: float, session_id: str):
        if presence not in PRESENCES or source not in SOURCES:
            raise ValueError("Unknown observation presence or source")
        if not self.powered_on or not self.monitoring_enabled:
            raise ValueError("Observations require power on and monitoring enabled")
        if session_id != self.observation_session:
            raise ValueError("Observation session is stale; use the current session")
        now = self._clock()
        if self._expires_at is not None and now >= self._expires_at:
            raise ValueError("Observation session expired; wait for a refreshed snapshot")
        if (isinstance(observed_at, bool) or not isinstance(observed_at, (float, int))
                or not math.isfinite(observed_at)):
            raise ValueError("Observation timestamp must be finite")
        age = self._wall_clock() - observed_at
        if age >= self.config.observation_timeout_seconds or age < -1.0:
            raise ValueError("Observation timestamp is stale or in the future")
        if self._observed_at is not None and observed_at <= self._observed_at:
            raise ValueError("Observation timestamp must be newer than the previous observation")

        previous_presence, previous_source = self._presence, self._source
        previous_camera = self.camera_status
        self._presence = "unknown" if presence == "unavailable" else presence
        self._source = source
        self._observed_at = float(observed_at)
        self._received_at = now
        self._initial_age = max(0.0, age)
        self.camera_status = "unavailable" if presence == "unavailable" else "available"
        self._expires_at = (now + self.config.observation_timeout_seconds - self._initial_age
                            if self.camera_status == "available" else None)
        if (self._presence, source, self.camera_status) != (
                previous_presence, previous_source, previous_camera):
            self.record("observation_changed", f"{source}: {presence}")
        if presence == "absent":
            if self._absence_started_at is None:
                self._absence_started_at = now
        else:
            self._absence_started_at = None
            self._clear_reminder("Presence restored" if presence == "present"
                                 else "Detection input unavailable or uncertain")
        self._evaluate(now)
        return True

    def _evaluate(self, now):
        if not self.powered_on or not self.monitoring_enabled:
            return self._transition(self._resting_state(), "Monitoring inactive")
        if self.camera_status != "available" or self._presence == "unknown":
            return self._transition("unavailable", "Detection input unavailable or uncertain")
        if self._presence == "present":
            return self._transition("ready", "User present")
        if self._reminder_active:
            return self._transition("reminding", "Reminder active")
        duration = now - self._absence_started_at
        if duration >= self.config.absence_seconds and now >= self._cooldown_until:
            self._reminder_id += 1
            self._reminder_active = True
            self._cooldown_until = now + self.config.cooldown_seconds
            self.record("reminder_triggered", f"Reminder {self._reminder_id} triggered after sustained absence")
            self._transition("reminding", "Sustained absence threshold reached")
            return True
        return self._transition("distraction", "Absence observed")

    def dismiss(self, reminder_id: int):
        """Clear the active cue and guarantee a full quiet period after dismissal."""
        if (type(reminder_id) is not int or not self._reminder_active
                or reminder_id != self._reminder_id):
            raise ValueError("Reminder is no longer active; refresh the current reminder")
        self._reminder_active = False
        self._cooldown_until = max(self._cooldown_until,
                                   self._clock() + self.config.cooldown_seconds)
        self.record("reminder_dismissed", f"Reminder {reminder_id} dismissed")
        # Dismissing a long-running cue must not let an already-expired cooldown
        # cause a new cue on the next tick. Returning/pause also retain cooldown.
        self._transition("distraction", "Reminder dismissed")
        return True

    def tick(self):
        now = self._clock()
        if (self.monitoring_enabled and self._expires_at is not None
                and now >= self._expires_at):
            return self.invalidate_observations("Observation timed out")
        return self._evaluate(now)

    def snapshot(self):
        now = self._clock()
        age = (None if self._received_at is None
               else round(max(0.0, now - self._received_at + self._initial_age), 3))
        duration = (0.0 if self._absence_started_at is None
                    else round(max(0.0, now - self._absence_started_at), 3))
        return {
            "powered_on": self.powered_on,
            "monitoring_enabled": self.monitoring_enabled,
            "muted": self.muted,
            "behavior_state": self.behavior_state,
            "display": self._preview or self.behavior_state,
            "preview_active": self._preview is not None,
            "camera_status": self.camera_status,
            "observation_session": self.observation_session,
            "observation": {
                "presence": self._presence,
                "source": self._source,
                "observed_at": self._observed_at,
                "age_seconds": age,
            },
            "absence_duration_seconds": duration,
            "cooldown_remaining_seconds": round(max(0.0, self._cooldown_until - now), 3),
            "reminder": {"active": self._reminder_active, "id": self._reminder_id,
                         "message": REMINDER_MESSAGE if self._reminder_active else None},
            "settings": asdict(self.config),
            "events": [dict(event) for event in self._events],
        }
