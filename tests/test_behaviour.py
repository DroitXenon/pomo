"""Policy tests use only synthetic observations and explicit monotonic times."""
import pytest

from backend.behaviour import Behaviour
from backend.config import BehaviourConfig
from backend.observations import Observation


def observation(at, presence='present', **kwargs):
    return Observation(observed_at=at, processed_at=at, presence=presence, **kwargs)


def policy(**kwargs):
    result = Behaviour(BehaviourConfig(**kwargs))
    result.reset(enabled=True)
    return result


def feed(result, presence, start, end):
    at = start
    while at <= end:
        result.observe(observation(at, presence), at)
        at += 0.25


def armed(**kwargs):
    result = policy(**kwargs)
    feed(result, 'present', 0, 0.5)
    assert result.armed
    return result


def test_empty_initial_view_never_arms_or_reminds():
    result = policy()
    feed(result, 'not_detected', 0, 20)
    assert result.status == 'possible_absence'
    assert result.snapshot()['absence_seconds'] == 20
    assert not result.armed
    assert not result.reminder_active


def test_grace_and_exact_sustained_absence_threshold():
    # Preserve the original camera policy's ten-second boundary regression even
    # though the integrated application now defaults to a five-second threshold.
    result = armed(absence_seconds=10)
    feed(result, 'not_detected', 1, 1.75)
    assert result.status == 'tracking_loss'
    result.observe(observation(2, 'not_detected'), 2)
    assert result.status == 'possible_absence'
    feed(result, 'not_detected', 2.25, 10.75)
    assert not result.reminder_active
    result.observe(observation(11, 'not_detected'), 11)
    assert result.reminder_active
    feed(result, 'not_detected', 11.25, 15)
    assert result.reminder_active


def test_visible_face_cancels_pending_absence_and_stable_return_clears_reminder():
    result = armed(absence_seconds=2)
    feed(result, 'not_detected', 1, 2)
    feed(result, 'present', 2.25, 2.75)
    assert result.absence_since is None
    feed(result, 'not_detected', 3, 5)
    assert result.reminder_active
    result.observe(observation(5.25), 5.25)
    assert result.reminder_active
    feed(result, 'present', 5.5, 5.75)
    assert not result.reminder_active
    assert result.status == 'present'


def test_unknown_cancels_reminder_and_requires_fresh_face_baseline():
    result = armed(absence_seconds=1)
    feed(result, 'not_detected', 1, 2)
    assert result.reminder_active
    result.observe(observation(2.25, 'unknown', reason='low_light'), 2.25)
    assert result.status == 'uncertain' and not result.reminder_active
    feed(result, 'not_detected', 2.5, 20)
    assert result.status == 'possible_absence'
    assert not result.reminder_active


def test_stale_tick_suppresses_reminders_without_new_input():
    result = armed()
    result.observe(observation(1, 'not_detected'), 1)
    result.tick(2.01)
    assert result.status == 'stale'
    assert not result.armed and result.absence_since is None
    result.tick(100)
    assert not result.reminder_active


def test_missing_observation_gap_cannot_count_as_absence():
    result = armed(absence_seconds=1)
    result.observe(observation(1, 'not_detected'), 1)
    result.observe(observation(10, 'not_detected'), 10)
    assert not result.armed and not result.reminder_active


def test_out_of_order_and_stale_inference_cannot_trigger_reminder():
    result = armed()
    result.observe(observation(0.25, 'not_detected'), 0.75)
    assert result.status == 'present'
    result.observe(observation(1, 'not_detected'), 3)
    assert result.status == 'stale' and not result.reminder_active
    result.observe(observation(5, 'not_detected'), 4)
    assert not result.reminder_active


def test_dismissal_requires_a_new_continuous_absence_interval():
    result = armed(absence_seconds=1)
    feed(result, 'not_detected', 1, 2)
    result.dismiss()
    assert not result.reminder_active and result.absence_since is None
    feed(result, 'not_detected', 2.25, 3)
    assert not result.reminder_active
    result.observe(observation(3.25, 'not_detected'), 3.25)
    assert result.reminder_active


@pytest.mark.parametrize('unavailable', [False, True])
def test_pause_and_unavailable_reset_pending_evidence(unavailable):
    result = armed(absence_seconds=1)
    feed(result, 'not_detected', 1, 2)
    result.dismiss()
    result.reset(unavailable=unavailable)
    result.observe(observation(2.25, 'not_detected'), 2.25)
    assert not result.reminder_active
    result.reset(enabled=True)
    feed(result, 'not_detected', 3, 20)
    assert not result.armed and not result.reminder_active


def test_manual_preview_does_not_create_a_dismissible_reminder():
    result = policy()
    with pytest.raises(ValueError):
        result.dismiss()


def test_invalid_timing_configuration_is_rejected():
    with pytest.raises(ValueError):
        BehaviourConfig(absence_seconds=0.5, tracking_loss_grace_seconds=1)


def test_unarmed_absence_counter_and_possible_absence_share_exact_grace_boundary():
    result = policy(tracking_loss_grace_seconds=1.5)
    feed(result, 'not_detected', 5, 6.25)
    assert result.snapshot()['absence_seconds'] == 1.25
    assert result.status == 'tracking_loss'
    result.observe(observation(6.5, 'not_detected'), 6.5)
    assert result.snapshot()['absence_seconds'] == 1.5
    assert result.status == 'possible_absence'
    assert not result.reminder_active


def test_unknown_resets_counter_but_fresh_non_detection_starts_it_again():
    result = armed()
    feed(result, 'not_detected', 1, 3)
    result.observe(observation(3.25, 'unknown'), 3.25)
    assert result.snapshot()['absence_seconds'] == 0
    feed(result, 'not_detected', 3.5, 4.5)
    assert result.snapshot()['absence_seconds'] == 1
    assert result.status == 'possible_absence'
    assert not result.armed and not result.reminder_active
