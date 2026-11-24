"""Deterministic policy checks: no webcam, event loop, or real-time sleeps."""

from dataclasses import replace
import math

import pytest

from backend.policy import DISPLAYS, REMINDER_MESSAGES, PolicyConfig, ReminderEngine


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.epoch = 1_790_000_000.0

    def monotonic(self):
        return self.now

    def wall(self):
        return self.epoch + self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def policy():
    clock = FakeClock()
    engine = ReminderEngine(clock=clock.monotonic, wall_clock=clock.wall)
    return engine, clock


def observe(engine, clock, presence="absent", source="simulated"):
    return engine.observe(presence, source, clock.wall(), engine.observation_session)


def start_absence(engine, clock):
    engine.set_monitoring(True)
    observe(engine, clock)


def continue_absence(engine, clock, seconds, step=1.0):
    end = clock.now + seconds
    while clock.now < end:
        clock.advance(min(step, end - clock.now))
        observe(engine, clock)


def trigger_reminder(engine, clock):
    start_absence(engine, clock)
    continue_absence(engine, clock, engine.config.absence_seconds)
    assert engine.snapshot()["reminder"]["active"]


def test_initial_state_and_enable_require_fresh_observations(policy):
    engine, clock = policy
    initial = engine.snapshot()
    assert initial["powered_on"] is True
    assert initial["monitoring_enabled"] is False
    assert initial["display"] == "bored"
    assert initial["muted"] is True
    assert initial["camera_status"] == "unavailable"
    assert initial["observation"]["source"] == "none"
    engine.set_monitoring(True)
    current = engine.snapshot()
    assert current["behavior_state"] == "bored"
    assert current["observation_session"] != initial["observation_session"]
    clock.advance(100)
    engine.tick()
    assert engine.snapshot()["reminder"]["id"] == 0
    observe(engine, clock, "present")
    assert engine.snapshot()["behavior_state"] == "happy"


@pytest.mark.parametrize("presence,camera_status", [
    ("uncertain", "available"), ("unavailable", "unavailable")])
def test_uncertain_or_unavailable_input_clears_reminder(policy, presence, camera_status):
    engine, clock = policy
    trigger_reminder(engine, clock)
    clock.advance(0.1)
    observe(engine, clock, presence)
    state = engine.snapshot()
    assert state["behavior_state"] == ("happy" if presence == "uncertain" else "bored")
    assert state["camera_status"] == camera_status
    assert state["observation"]["presence"] == presence
    assert state["reminder"]["active"] is False
    assert state["absence_duration_seconds"] == 0
    clock.advance(100)
    engine.tick()
    assert engine.snapshot()["reminder"]["id"] == 1


def test_brief_uncertainty_shows_happy_until_expiry(policy):
    engine, clock = policy
    engine.set_monitoring(True)
    engine.observe("uncertain", "camera", clock.wall(), engine.observation_session)
    state = engine.snapshot()
    assert state["observation"]["presence"] == "uncertain"
    assert state["behavior_state"] == state["display"] == "happy"
    assert state["absence_duration_seconds"] == 0
    clock.advance(0.999)
    engine.tick()
    assert engine.snapshot()["display"] == "happy"
    clock.advance(2.001)
    engine.tick()
    assert engine.snapshot()["display"] == "bored"
    clock.advance(0.1)
    observe(engine, clock, "uncertain", "camera")
    assert engine.snapshot()["display"] == "happy"


def test_pause_resets_observations_and_rejects_old_session_on_resume(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    original_session = engine.observation_session
    engine.set_monitoring(False)
    paused = engine.snapshot()
    assert paused["display"] == "bored"
    assert paused["reminder"]["active"] is False
    assert paused["absence_duration_seconds"] == 0
    assert paused["cooldown_remaining_seconds"] == 0
    assert paused["reminder"]["stage"] == 0
    with pytest.raises(ValueError, match="monitoring enabled"):
        observe(engine, clock)
    engine.set_monitoring(True)
    assert engine.snapshot()["display"] == "bored"
    clock.advance(0.1)
    with pytest.raises(ValueError, match="session"):
        engine.observe("absent", "simulated", clock.wall(), original_session)
    observe(engine, clock)
    assert engine.snapshot()["absence_duration_seconds"] == 0


def test_soft_shutdown_stops_monitoring_and_wake_is_paused(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    engine.set_power(False)
    off = engine.snapshot()
    assert off["behavior_state"] == "idle"
    assert off["powered_on"] is False
    assert off["monitoring_enabled"] is False
    assert off["reminder"]["active"] is False
    assert off["cooldown_remaining_seconds"] == 0
    with pytest.raises(ValueError, match="Power on"):
        engine.set_monitoring(True)
    engine.set_power(True)
    awake = engine.snapshot()
    assert awake["display"] == "bored"
    assert awake["monitoring_enabled"] is False
    assert awake["observation"]["source"] == "none"
    assert awake["reminder"]["id"] == 1


def test_expiry_accounts_for_age_already_present_at_receipt(policy):
    engine, clock = policy
    engine.set_monitoring(True)
    old_session = engine.observation_session
    engine.observe("absent", "camera", clock.wall() - 2.5, old_session)
    clock.advance(0.49)
    assert engine.tick() is False
    assert engine.snapshot()["display"] == "surprised"
    clock.advance(0.01)
    assert engine.tick() is True
    expired = engine.snapshot()
    assert expired["display"] == "bored"
    assert expired["observation_session"] != old_session
    assert expired["absence_duration_seconds"] == 0
    assert expired["observation"]["source"] == "none"
    event_count = len(expired["events"])
    clock.advance(100)
    assert engine.tick() is False
    assert len(engine.snapshot()["events"]) == event_count


def test_disconnect_invalidates_buffered_observations_and_active_reminder(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    original_session = engine.observation_session
    engine.invalidate_observations("Observation producer disconnected")
    assert engine.snapshot()["display"] == "bored"
    assert engine.snapshot()["reminder"]["active"] is False
    clock.advance(0.1)
    with pytest.raises(ValueError, match="session"):
        engine.observe("absent", "camera", clock.wall(), original_session)


def test_expiry_clears_an_active_reminder_and_the_departure(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    clock.advance(3)
    engine.tick()
    expired = engine.snapshot()
    assert expired["behavior_state"] == "bored"
    assert expired["reminder"]["active"] is False
    assert expired["reminder"]["stage"] == 0
    assert expired["absence_duration_seconds"] == 0
    assert any(event["kind"] == "absence_interrupted" for event in expired["events"])


@pytest.mark.parametrize("initial_presence", ["absent", "uncertain"])
def test_expired_generation_rejects_before_timer_and_requires_new_session(policy, initial_presence):
    engine, clock = policy
    engine.set_monitoring(True)
    observe(engine, clock, initial_presence)
    original_session = engine.observation_session
    clock.advance(4)
    before = engine.snapshot()
    for _ in range(2):
        with pytest.raises(ValueError, match="Observation session expired"):
            observe(engine, clock)
        assert engine.snapshot() == before

    assert engine.tick() is True
    refreshed = engine.snapshot()
    assert refreshed["observation_session"] != original_session
    assert refreshed["behavior_state"] == "bored"
    assert refreshed["absence_duration_seconds"] == 0
    assert engine.tick() is False
    assert engine.snapshot() == refreshed
    with pytest.raises(ValueError, match="session is stale"):
        engine.observe("absent", "simulated", clock.wall(), original_session)
    assert engine.snapshot() == refreshed

    observe(engine, clock)
    assert engine.snapshot()["absence_duration_seconds"] == 0
    continue_absence(engine, clock, 9)
    assert engine.snapshot()["reminder"]["id"] == 0
    continue_absence(engine, clock, 1)
    assert engine.snapshot()["reminder"]["id"] == 1


@pytest.mark.parametrize("display", sorted(DISPLAYS))
def test_manual_previews_do_not_change_behaviour_or_trigger_sound(policy, display):
    engine, clock = policy
    engine.preview(display)
    state = engine.snapshot()
    assert state["display"] == display
    assert state["behavior_state"] == "bored"
    assert state["preview_active"] is True
    assert state["reminder"]["id"] == 0
    assert state["powered_on"] is True
    engine.clear_preview()
    assert engine.snapshot()["preview_active"] is False
    engine.preview(display)
    engine.set_monitoring(True)
    assert engine.snapshot()["preview_active"] is False
    with pytest.raises(ValueError, match="monitoring paused"):
        engine.preview(display)


def test_sound_preference_does_not_retrigger_a_reminder(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    engine.set_muted(False)
    assert engine.snapshot()["muted"] is False
    assert engine.snapshot()["reminder"]["id"] == 1
    engine.set_muted(True)
    assert engine.snapshot()["reminder"]["id"] == 1


def test_invalid_dismissals_do_not_mutate_current_reminder(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    before = engine.snapshot()
    for value in (0, 2, True, "1"):
        with pytest.raises(ValueError):
            engine.dismiss(value)
        assert engine.snapshot() == before


@pytest.mark.parametrize("timestamp_offset", [-3, -4, 1.001, math.nan, math.inf])
def test_stale_future_and_nonfinite_timestamps_are_rejected_without_mutation(policy, timestamp_offset):
    engine, clock = policy
    engine.set_monitoring(True)
    before = engine.snapshot()
    with pytest.raises(ValueError):
        engine.observe("absent", "camera", clock.wall() + timestamp_offset,
                       engine.observation_session)
    assert engine.snapshot() == before


def test_duplicate_and_out_of_order_observations_do_not_mutate_state(policy):
    engine, clock = policy
    start_absence(engine, clock)
    before = engine.snapshot()
    for timestamp in (clock.wall(), clock.wall() - 0.1):
        with pytest.raises(ValueError, match="newer"):
            engine.observe("present", "camera", timestamp, engine.observation_session)
        assert engine.snapshot() == before


def test_wall_clock_change_does_not_distort_monotonic_expiry(policy):
    engine, clock = policy
    start_absence(engine, clock)
    clock.epoch += 3600
    clock.advance(2)
    assert engine.tick() is False
    assert engine.snapshot()["observation"]["age_seconds"] == 2
    clock.advance(1)
    assert engine.tick() is True
    assert engine.snapshot()["display"] == "bored"


def test_debug_events_are_bounded_and_snapshots_cannot_mutate_them(policy):
    engine, clock = policy
    for index in range(250):
        engine.record("test_event", f"Event {index}")
    state = engine.snapshot()
    assert len(state["events"]) == 100
    assert state["events"][0]["id"] == 151
    assert state["events"][-1]["id"] == 250
    assert state["events"][-1]["at"].endswith("+00:00")
    state["events"][-1]["message"] = "Changed outside policy"
    assert engine.snapshot()["events"][-1]["message"] == "Event 249"


def test_unchanged_observation_heartbeats_do_not_spam_debug_log(policy):
    engine, clock = policy
    start_absence(engine, clock)
    initial_events = len(engine.snapshot()["events"])
    continue_absence(engine, clock, 4, step=0.1)
    assert len(engine.snapshot()["events"]) == initial_events


@pytest.mark.parametrize("field,value", [
    ("absence_seconds", 0), ("absence_seconds", -1),
    ("absence_seconds", math.nan), ("absence_seconds", True),
    ("cooldown_seconds", -1), ("cooldown_seconds", math.inf),
    ("observation_timeout_seconds", 0), ("observation_timeout_seconds", "3"),
    ("repeat_seconds", 0), ("standby_seconds", 300), ("standby_seconds", 200)])
def test_invalid_policy_configuration_is_rejected(field, value):
    with pytest.raises(ValueError):
        replace(PolicyConfig(), **{field: value})

def kinds(engine, kind):
    return [event for event in engine.snapshot()["events"] if event["kind"] == kind]


def test_surprised_while_away_then_first_reminder_after_ten_seconds(policy):
    engine, clock = policy
    start_absence(engine, clock)
    assert engine.snapshot()["display"] == "surprised"
    assert len(kinds(engine, "departure_detected")) == 1
    continue_absence(engine, clock, 9)
    clock.advance(0.999)
    engine.tick()
    state = engine.snapshot()
    assert state["display"] == "surprised"
    assert state["reminder"]["active"] is False
    assert state["next_step_seconds"] == pytest.approx(0.001)
    clock.advance(0.001)
    assert engine.tick() is True
    state = engine.snapshot()
    assert state["display"] == state["behavior_state"] == "sad"
    assert state["reminder"] == {"active": True, "id": 1, "stage": 1,
                                 "message": REMINDER_MESSAGES[1]}
    assert state["absence_duration_seconds"] == 10
    assert state["cooldown_remaining_seconds"] == 0
    assert state["next_step_seconds"] == 300
    assert "(first)" in kinds(engine, "reminder_triggered")[-1]["message"]


def test_brief_absence_does_not_accumulate_across_present_observations(policy):
    engine, clock = policy
    start_absence(engine, clock)
    continue_absence(engine, clock, 8)
    clock.advance(0.1)
    observe(engine, clock, "present")
    assert engine.snapshot()["absence_duration_seconds"] == 0
    assert "before any reminder" in kinds(engine, "user_returned")[-1]["message"]
    clock.advance(0.1)
    observe(engine, clock)
    continue_absence(engine, clock, 8)
    assert engine.snapshot()["display"] == "surprised"
    assert engine.snapshot()["reminder"]["id"] == 0


def test_second_reminder_then_standby_then_return_shows_happy(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    continue_absence(engine, clock, 299)
    assert engine.snapshot()["reminder"]["id"] == 1
    continue_absence(engine, clock, 1)
    state = engine.snapshot()
    assert state["reminder"] == {"active": True, "id": 2, "stage": 2,
                                 "message": REMINDER_MESSAGES[2]}
    assert state["display"] == "sad"
    assert "(second)" in kinds(engine, "reminder_triggered")[-1]["message"]
    continue_absence(engine, clock, 299)
    assert engine.snapshot()["standby"] is False
    continue_absence(engine, clock, 1)
    state = engine.snapshot()
    assert state["standby"] is True
    assert state["display"] == "bored"
    assert state["monitoring_enabled"] is True
    assert state["reminder"]["active"] is False
    assert state["next_step_seconds"] is None
    assert len(kinds(engine, "standby_entered")) == 1
    continue_absence(engine, clock, 100)
    assert engine.snapshot()["reminder"]["id"] == 2
    assert len(kinds(engine, "reminder_triggered")) == 2
    clock.advance(0.5)
    observe(engine, clock, "present")
    state = engine.snapshot()
    assert state["display"] == "happy"
    assert state["standby"] is False
    assert "after standby" in kinds(engine, "user_returned")[-1]["message"]


def test_dismissal_silences_the_cue_but_keeps_the_schedule(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    engine.dismiss(1)
    dismissed = engine.snapshot()
    assert dismissed["display"] == "sad"
    assert dismissed["reminder"]["active"] is False
    assert dismissed["reminder"]["stage"] == 1
    continue_absence(engine, clock, 300)
    assert engine.snapshot()["reminder"]["id"] == 2
    assert engine.snapshot()["reminder"]["active"] is True


def test_return_logs_latency_after_the_latest_reminder_and_resets_the_sequence(policy):
    engine, clock = policy
    trigger_reminder(engine, clock)
    continue_absence(engine, clock, 23.3, step=0.6)
    clock.advance(0.1)
    observe(engine, clock, "present")
    state = engine.snapshot()
    assert state["display"] == "happy"
    assert state["reminder"]["active"] is False
    assert state["reminder"]["stage"] == 0
    assert state["absence_duration_seconds"] == 0
    message = kinds(engine, "user_returned")[-1]["message"]
    assert "23.4s after reminder 1 (first)" in message
    assert "away 33.4s" in message
    clock.advance(0.1)
    observe(engine, clock)
    assert engine.snapshot()["display"] == "surprised"
    continue_absence(engine, clock, 10)
    assert engine.snapshot()["reminder"]["id"] == 2
    assert engine.snapshot()["reminder"]["stage"] == 1


def test_departure_time_includes_the_initial_uncertainty(policy):
    engine, clock = policy
    engine.set_monitoring(True)
    observe(engine, clock, "uncertain")
    clock.advance(0.999)
    observe(engine, clock, "uncertain")
    assert engine.snapshot()["display"] == "happy"
    clock.advance(0.001)
    engine.tick()
    state = engine.snapshot()
    assert state["observation"]["presence"] == "absent"
    assert state["display"] == "surprised"
    assert state["absence_duration_seconds"] == 1
    for _ in range(9):
        clock.advance(1)
        observe(engine, clock, "uncertain")
    assert engine.snapshot()["reminder"]["id"] == 1
    assert engine.snapshot()["display"] == "sad"
    clock.advance(0.1)
    observe(engine, clock, "present")
    assert engine.snapshot()["display"] == "happy"


def test_cooldown_spaces_first_reminders_between_departures():
    clock = FakeClock()
    engine = ReminderEngine(PolicyConfig(cooldown_seconds=30), clock=clock.monotonic,
                            wall_clock=clock.wall)
    trigger_reminder(engine, clock)
    clock.advance(0.1)
    observe(engine, clock, "present")
    clock.advance(0.1)
    observe(engine, clock)
    continue_absence(engine, clock, 29.7)
    assert engine.snapshot()["display"] == "surprised"
    assert engine.snapshot()["reminder"]["id"] == 1
    continue_absence(engine, clock, 0.2)
    assert engine.snapshot()["reminder"]["id"] == 2
