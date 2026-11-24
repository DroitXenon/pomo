"""Camera-independent state and reminder policy with injectable clocks."""

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import time
from typing import Callable
from uuid import uuid4

from .observations import PRESENCES


DISPLAYS = frozenset({"happy", "idle", "sad", "surprised", "bored"})
SOURCES = frozenset({"simulated", "camera"})
REMINDER_MESSAGES = {
    1: "I miss you. Please come back to your study when you're ready.",
    2: "I'm still here. Come back to your study whenever you're ready.",
}
STAGE_NAMES = {1: "first", 2: "second"}


@dataclass(frozen=True)
class PolicyConfig:
    """Timings, measured from the moment a face is first lost.

    ``absence_seconds`` is the departure-to-first-reminder delay. The second
    reminder follows ``repeat_seconds`` after the first, and standby begins
    ``standby_seconds`` after the first. ``cooldown_seconds`` only spaces out
    first reminders between separate departures.
    """
    absence_seconds: float = 10.0
    cooldown_seconds: float = 0.0
    observation_timeout_seconds: float = 3.0
    uncertainty_seconds: float = 1.0
    repeat_seconds: float = 300.0
    standby_seconds: float = 600.0

    def __post_init__(self):
        for name, value in asdict(self).items():
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"{name} must be finite")
            if value < 0 or (name != "cooldown_seconds" and value == 0):
                raise ValueError(f"{name} must be positive" if name != "cooldown_seconds"
                                 else "cooldown_seconds must be non-negative")
        if self.standby_seconds <= self.repeat_seconds:
            raise ValueError("standby_seconds must be greater than repeat_seconds")


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
        self.behavior_state = "bored"
        self._preview = None
        self.camera_status = "unavailable"
        self.observation_session = uuid4().hex
        self._presence = "unavailable"
        self._uncertain_since = None
        self._source = "none"
        self._observed_at = None
        self._received_at = None
        self._initial_age = 0.0
        self._expires_at = None
        self._absence_started_at = None
        self._reminder_stage = 0
        self._first_reminder_at = None
        self._last_reminder_at = None
        self._standby = False
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

    def _start_absence(self, departed_at):
        if self._absence_started_at is None:
            self._absence_started_at = departed_at
            self.record("departure_detected",
                        f"{self._source}: user away since {self._event_time(departed_at)}")

    def _event_time(self, monotonic_at):
        wall = self._wall_clock() - (self._clock() - monotonic_at)
        return datetime.fromtimestamp(wall, timezone.utc).isoformat()

    def _end_absence(self, kind, reason):
        """Close a departure episode, logging how long after each cue it ended."""
        if self._absence_started_at is None:
            self._clear_reminder(reason)
            return
        now = self._clock()
        away = now - self._absence_started_at
        if self._standby:
            detail = f"after standby; away {away:.1f}s"
        elif self._reminder_stage:
            detail = (f"{now - self._last_reminder_at:.1f}s after reminder {self._reminder_id} "
                      f"({STAGE_NAMES[self._reminder_stage]}); away {away:.1f}s")
        else:
            detail = f"before any reminder; away {away:.1f}s"
        self._clear_reminder(reason)
        self.record(kind, f"{reason} {detail}")
        self._absence_started_at = None
        self._reminder_stage = 0
        self._first_reminder_at = None
        self._last_reminder_at = None
        self._standby = False

    def _reset_observations(self):
        self._presence = "unavailable"
        self._uncertain_since = None
        self._source = "none"
        self._observed_at = None
        self._received_at = None
        self._initial_age = 0.0
        self._expires_at = None
        self.camera_status = "unavailable"

    def _resting_state(self):
        if not self.powered_on:
            return "idle"
        return "bored"

    def invalidate_observations(self, reason: str, level: str = "warning"):
        self._end_absence("absence_interrupted", reason)
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
        departed_at = now
        if presence == "uncertain":
            if self._uncertain_since is None:
                self._uncertain_since = now
            departed_at = self._uncertain_since
            effective_presence = "absent" if now - self._uncertain_since >= self.config.uncertainty_seconds else "uncertain"
        else:
            self._uncertain_since = None
            effective_presence = presence
        self._presence = effective_presence
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
        if effective_presence == "absent":
            self._start_absence(departed_at)
        elif presence == "present":
            self._end_absence("user_returned", "User returned")
        else:
            self._end_absence("absence_interrupted", "Detection input unavailable or uncertain")
        self._evaluate(now)
        return True

    def _evaluate(self, now):
        if not self.powered_on or not self.monitoring_enabled:
            return self._transition(self._resting_state(), "Monitoring inactive")
        if self.camera_status != "available":
            return self._transition("bored", "Detection input unavailable or uncertain")
        if self._presence == "uncertain":
            if self._uncertain_since is not None and now - self._uncertain_since >= self.config.uncertainty_seconds:
                self._presence = "absent"
                self.record("observation_changed", f"{self._source}: absent after sustained uncertainty")
                self._start_absence(self._uncertain_since)
            else:
                return self._transition("happy", "Detection input uncertain")
        if self._presence == "present":
            return self._transition("happy", "User present")
        if self._standby:
            return self._transition("bored", "Standby")
        config = self.config
        if self._reminder_stage and now >= self._first_reminder_at + config.standby_seconds:
            self._standby = True
            self._clear_reminder("Standby")
            self.record("standby_entered", f"No return {now - self._first_reminder_at:.1f}s after the first reminder")
            return self._transition("bored", "Standby after no return")
        if self._reminder_stage == 1 and now >= self._first_reminder_at + config.repeat_seconds:
            self._trigger_reminder(2, now)
            return self._transition("sad", "Second reminder") or True
        if (not self._reminder_stage and now - self._absence_started_at >= config.absence_seconds
                and now >= self._cooldown_until):
            self._trigger_reminder(1, now)
            self._first_reminder_at = now
            self._cooldown_until = now + config.cooldown_seconds
            return self._transition("sad", "Sustained absence threshold reached") or True
        if self._reminder_stage:
            return self._transition("sad", "Waiting for the user to return")
        return self._transition("surprised", "Absence observed")

    def _trigger_reminder(self, stage, now):
        self._reminder_id += 1
        self._reminder_stage = stage
        self._reminder_active = True
        self._last_reminder_at = now
        self.record("reminder_triggered",
                    f"Reminder {self._reminder_id} ({STAGE_NAMES[stage]}) after "
                    f"{now - self._absence_started_at:.1f}s away")

    def _next_step_seconds(self, now):
        if self._absence_started_at is None or self._standby or self._presence != "absent":
            return None
        if not self._reminder_stage:
            due = max(self._absence_started_at + self.config.absence_seconds, self._cooldown_until)
        elif self._reminder_stage == 1:
            due = self._first_reminder_at + self.config.repeat_seconds
        else:
            due = self._first_reminder_at + self.config.standby_seconds
        return round(max(0.0, due - now), 3)

    def dismiss(self, reminder_id: int):
        """Silence the active cue; the second-reminder and standby schedule continue."""
        if (type(reminder_id) is not int or not self._reminder_active
                or reminder_id != self._reminder_id):
            raise ValueError("Reminder is no longer active; refresh the current reminder")
        self._reminder_active = False
        self._cooldown_until = max(self._cooldown_until,
                                   self._clock() + self.config.cooldown_seconds)
        self.record("reminder_dismissed", f"Reminder {reminder_id} dismissed")
        self._transition("sad", "Reminder dismissed")
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
            "standby": self._standby,
            "next_step_seconds": self._next_step_seconds(now),
            "reminder": {"active": self._reminder_active, "id": self._reminder_id,
                         "stage": self._reminder_stage,
                         "message": (REMINDER_MESSAGES[self._reminder_stage]
                                     if self._reminder_active else None)},
            "settings": asdict(self.config),
            "events": [dict(event) for event in self._events],
        }
