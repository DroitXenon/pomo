"""Protocol/runtime integration checks using synthetic observations and clocks."""

import json
import logging

import anyio
from fastapi.testclient import TestClient
import pytest

from backend.app import create_app as app_factory
from tests.camera_helpers import DecodeProcessor
from backend.policy import PolicyConfig


def create_app(*args, **kwargs):
    kwargs.setdefault("processor_factory", DecodeProcessor)
    return app_factory(*args, **kwargs)


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
def rig():
    clock = FakeClock()
    app = create_app(
        config=PolicyConfig(absence_seconds=2, cooldown_seconds=10,
                            observation_timeout_seconds=3),
        clock=clock.monotonic, wall_clock=clock.wall, run_ticker=False,
    )
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as setup:
            setup.receive_json()
            state = command(setup, "set_input_source", source="simulated")
            assert state["input_source"] == "simulated"
        yield client, app, clock


def command(ws, kind, **fields):
    ws.send_json({"type": kind, **fields})
    return ws.receive_json()


def observe(ws, clock, state, presence="absent", source="simulated", **fields):
    payload = {
        "presence": presence, "source": source, "observed_at": clock.wall(),
        "session_id": state["observation_session"], **fields,
    }
    return command(ws, "submit_observation", **payload)


def current(client, app):
    return client.portal.call(app.state.runtime.snapshot)


def tick(client, app):
    client.portal.call(app.state.runtime.tick)


def without_events(state):
    return {key: value for key, value in state.items() if key != "events"}


def trigger_reminder(ws, clock):
    state = command(ws, "set_monitoring", enabled=True)
    state = observe(ws, clock, state)
    for _ in range(2):
        clock.advance(1)
        state = observe(ws, clock, state)
    assert state["reminder"]["active"]
    return state


def close_and_wait(client, app, ws, expected_clients):
    """Wait for transport cleanup using scheduler checkpoints, never sleeps."""
    ws.close()

    async def wait_for_disconnect():
        with anyio.fail_after(2):
            while len(app.state.runtime.clients) != expected_clients:
                await anyio.lowlevel.checkpoint()

    client.portal.call(wait_for_disconnect)


def test_health_static_and_protocol_defaults(rig):
    client, _, _ = rig
    assert client.get("/health").json() == {
        "status": "ok", "phase": 2, "protocol_version": 7, "camera_processor_ready": True,
    }
    assert "Pomo" in client.get("/").text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    with client.websocket_connect("/ws") as ws:
        state = ws.receive_json()
        assert state["type"] == "state"
        assert state["protocol_version"] == 7
        assert state["revision"] == 1
        assert state["instance_id"] and state["observation_session"]
        assert state["powered_on"] is True
        assert state["monitoring_enabled"] is False
        assert state["muted"] is True
        assert state["display"] == state["behavior_state"] == "ready"
        assert state["reminder"] == {"active": False, "id": 0, "message": None}


def test_commands_broadcast_identical_snapshots_to_all_clients(rig):
    client, _, clock = rig
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.receive_json()
        b.receive_json()
        state = command(a, "set_monitoring", enabled=True)
        assert state == b.receive_json()
        assert state["revision"] == 2 and state["display"] == "unavailable"
        state = observe(a, clock, state, "present", "simulated")
        assert state == b.receive_json()
        assert state["revision"] == 3 and state["display"] == "ready"
        state = command(b, "set_muted", muted=False)
        assert state == a.receive_json()
        assert state["revision"] == 4 and state["muted"] is False


def test_input_source_changes_require_pause_and_power_and_clear_old_generation(rig):
    client, app, _ = rig
    with client.websocket_connect('/ws') as ws:
        state = ws.receive_json()
        old_session = state['observation_session']
        state = command(ws, 'set_input_source', source='camera')
        assert state['input_source'] == 'camera'
        assert state['observation_session'] != old_session
        state = command(ws, 'set_monitoring', enabled=True)
        before = current(client, app)
        assert command(ws, 'set_input_source', source='simulated')['type'] == 'error'
        assert without_events(current(client, app)) == without_events(before)
        state = command(ws, 'set_monitoring', enabled=False)
        assert state['camera_session'] is None
        state = command(ws, 'set_power', enabled=False)
        before = current(client, app)
        assert command(ws, 'set_input_source', source='simulated')['type'] == 'error'
        assert without_events(current(client, app)) == without_events(before)
        state = command(ws, 'set_power', enabled=True)
        state = command(ws, 'set_input_source', source='simulated')
        assert state['input_source'] == 'simulated'


def test_camera_metadata_cannot_bypass_selected_camera_frame_pipeline(rig):
    client, app, clock = rig
    with client.websocket_connect('/ws') as ws:
        ws.receive_json()
        state = command(ws, 'set_monitoring', enabled=True)
        before = current(client, app)
        assert observe(ws, clock, state, source='camera')['type'] == 'error'
        assert without_events(current(client, app)) == without_events(before)


@pytest.mark.parametrize("display", ["ready", "shutdown", "distraction", "reminding", "unavailable"])
def test_previews_are_separate_from_policy_and_real_reminders(rig, display):
    client, _, _ = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = command(ws, "preview_display", display=display)
        assert state["display"] == display
        assert state["behavior_state"] == "ready" and state["powered_on"] is True
        assert state["preview_active"] is True and state["reminder"]["id"] == 0
        assert not any(e["kind"] == "reminder_triggered" for e in state["events"])
        state = command(ws, "clear_preview")
        assert state["display"] == "ready" and state["preview_active"] is False
        state = command(ws, "set_monitoring", enabled=True)
        revision = state["revision"]
        assert command(ws, "preview_display", display="ready")["type"] == "error"
        state = command(ws, "set_muted", muted=False)
        assert state["revision"] == revision + 1 and state["display"] == "unavailable"


@pytest.mark.parametrize("payload", [
    "bad json", "[]", "null", "{}", '{"type":"unknown"}',
    '{"type":"set_monitoring","enabled":"false"}',
    '{"type":"set_monitoring","enabled":1}',
    '{"type":"set_monitoring","enabled":null}',
    '{"type":"set_monitoring"}',
    '{"type":"set_monitoring","enabled":true,"extra":"private-payload"}',
    '{"type":"set_power","enabled":0}',
    '{"type":"set_muted","muted":"true"}',
    '{"type":"dismiss_reminder","reminder_id":true}',
    '{"type":"dismiss_reminder","reminder_id":1.0}',
    '{"type":"dismiss_reminder","reminder_id":0}',
    '{"type":"clear_preview","display":"ready"}',
    '{"type":"set_input_source"}',
    '{"type":"set_input_source","source":"browser"}',
    '{"type":"set_input_source","source":null}',
    '{"type":"set_input_source","source":"camera","enabled":true}',
    '{"type":"camera_failed","enabled":false}',
    '{"type":"camera_failed","source":"camera"}',
    '{"type":"camera_failed","session_id":"private-session"}',
    '{"type":"preview_display","display":"possible_absence"}',
    '{"type":"preview_display","display":null}',
    pytest.param("x" * 4097, id="oversized-text"),
])
def test_invalid_commands_and_binary_frames_preserve_robot_state(rig, payload):
    client, app, _ = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        before = current(client, app)
        ws.send_text(payload)
        error = ws.receive_json()
        assert error["type"] == "error" and error["code"] == "invalid_command"
        assert without_events(current(client, app)) == without_events(before)
        assert current(client, app)["events"][-1]["kind"] == "command_rejected"
        ws.send_bytes(b"private-binary-payload")
        assert ws.receive_json()["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)


@pytest.mark.parametrize("field,value", [
    ("presence", "distraction"), ("presence", None), ("source", "browser"),
    ("observed_at", True), ("observed_at", "1790000000"),
    ("observed_at", None), ("observed_at", float("nan")),
    ("observed_at", float("inf")), ("session_id", ""),
    ("session_id", 123), ("session_id", "x" * 101), ("extra", "private-payload"),
])
def test_observation_schema_is_strict_and_rejections_preserve_state(rig, field, value):
    client, app, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = command(ws, "set_monitoring", enabled=True)
        before = current(client, app)
        assert observe(ws, clock, state, **{field: value})["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)


def test_stale_future_duplicate_and_out_of_order_input_is_rejected(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = command(ws, "set_monitoring", enabled=True)
        state = observe(ws, clock, state, "present", "simulated")
        for timestamp in (clock.wall() - 3, clock.wall() + 1.01,
                          clock.wall(), clock.wall() - 0.1):
            before = current(client, app)
            assert observe(ws, clock, state, observed_at=timestamp)["type"] == "error"
            assert without_events(current(client, app)) == without_events(before)


def test_elapsed_tick_triggers_once_and_dismissal_requires_current_id(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = command(ws, "set_monitoring", enabled=True)
        state = observe(ws, clock, state)
        clock.advance(1)
        state = observe(ws, clock, state)
        clock.advance(0.999)
        tick(client, app)
        assert ws.receive_json()["reminder"]["active"] is False
        clock.advance(0.001)
        tick(client, app)
        state = ws.receive_json()
        assert state["display"] == "reminding" and state["reminder"]["id"] == 1
        for _ in range(11):
            clock.advance(1)
            state = observe(ws, clock, state)
        assert state["reminder"]["id"] == 1
        assert sum(e["kind"] == "reminder_triggered" for e in state["events"]) == 1
        before = current(client, app)
        assert command(ws, "dismiss_reminder", reminder_id=2)["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)
        state = command(ws, "dismiss_reminder", reminder_id=1)
        assert state["display"] == "distraction" and state["reminder"]["active"] is False
        assert state["cooldown_remaining_seconds"] == 10
        for _ in range(10):
            clock.advance(1)
            state = observe(ws, clock, state)
        assert state["reminder"]["id"] == 2 and state["reminder"]["active"] is True
        before = current(client, app)
        assert command(ws, "dismiss_reminder", reminder_id=1)["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)


def test_cooldown_survives_return_pause_and_unavailable_input(rig):
    client, _, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = trigger_reminder(ws, clock)
        state = command(ws, "dismiss_reminder", reminder_id=1)
        assert state["cooldown_remaining_seconds"] == 10
        clock.advance(0.1)
        state = observe(ws, clock, state, "present")
        assert state["display"] == "ready"
        assert state["cooldown_remaining_seconds"] == pytest.approx(9.9)
        state = command(ws, "set_monitoring", enabled=False)
        assert state["display"] == "ready"
        assert state["cooldown_remaining_seconds"] == pytest.approx(9.9)
        state = command(ws, "set_monitoring", enabled=True)
        clock.advance(0.1)
        state = observe(ws, clock, state, "unavailable")
        assert state["display"] == "unavailable"
        assert state["cooldown_remaining_seconds"] == pytest.approx(9.8)
        clock.advance(0.1)
        state = observe(ws, clock, state)
        for _ in range(3):
            clock.advance(1)
            state = observe(ws, clock, state)
        assert state["display"] == "distraction" and state["reminder"]["id"] == 1


def test_expiry_rotates_session_once_and_rejects_buffered_observations(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = command(ws, "set_monitoring", enabled=True)
        old_session = state["observation_session"]
        state = observe(ws, clock, state, observed_at=clock.wall() - 2.5)
        clock.advance(0.5)
        tick(client, app)
        state = ws.receive_json()
        assert state["observation_session"] != old_session
        assert state["display"] == "unavailable" and state["absence_duration_seconds"] == 0
        assert state["observation"]["source"] == "none"
        before = current(client, app)
        tick(client, app)
        assert current(client, app) == before
        assert observe(ws, clock, state, session_id=old_session)["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)
        state = observe(ws, clock, state)
        assert state["absence_duration_seconds"] == 0


def test_frame_arriving_after_expiry_cannot_beat_the_timer_with_an_old_session(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = command(ws, "set_monitoring", enabled=True)
        state = observe(ws, clock, state, source="simulated")
        old_session = state["observation_session"]
        clock.advance(3.1)
        before = current(client, app)
        error = observe(ws, clock, state, source="simulated")
        assert error["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)
        assert current(client, app)["observation_session"] == old_session

        tick(client, app)
        state = ws.receive_json()
        assert state["observation_session"] != old_session
        assert state["display"] == "unavailable"
        assert state["observation"]["source"] == "none"
        assert state["reminder"]["active"] is False
        state = observe(ws, clock, state, source="simulated")
        assert state["display"] == "distraction"
        assert state["absence_duration_seconds"] == 0
        assert state["reminder"]["active"] is False


def test_pause_and_soft_power_cycle_require_fresh_session_and_reset_inputs(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = trigger_reminder(ws, clock)
        original_session = state["observation_session"]
        state = command(ws, "set_monitoring", enabled=False)
        assert state["display"] == "ready" and state["reminder"]["active"] is False
        assert state["observation_session"] != original_session
        state = command(ws, "set_monitoring", enabled=True)
        assert observe(ws, clock, state, session_id=original_session)["type"] == "error"
        state = observe(ws, clock, state, "present")
        active_session = state["observation_session"]
        state = command(ws, "set_power", enabled=False)
        assert state["powered_on"] is False and state["monitoring_enabled"] is False
        assert state["display"] == "shutdown" and state["reminder"]["active"] is False
        assert state["observation"]["source"] == "none"
        assert state["observation_session"] != active_session
        before = current(client, app)
        for kind, fields in (("set_monitoring", {"enabled": True}),
                             ("preview_display", {"display": "ready"})):
            assert command(ws, kind, **fields)["type"] == "error"
            assert without_events(current(client, app)) == without_events(before)
        state = command(ws, "set_power", enabled=True)
        assert state["display"] == "ready" and state["monitoring_enabled"] is False
        assert state["observation_session"] != active_session


def test_mute_changes_preserve_reminder_and_do_not_retrigger(rig):
    client, _, clock = rig
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        state = trigger_reminder(ws, clock)
        reminder = state["reminder"]
        trigger_ids = [e["id"] for e in state["events"] if e["kind"] == "reminder_triggered"]
        for muted in (False, True, False):
            state = command(ws, "set_muted", muted=muted)
            assert state["muted"] is muted and state["reminder"] == reminder
            assert [e["id"] for e in state["events"]
                    if e["kind"] == "reminder_triggered"] == trigger_ids


def test_dev_controls_disable_simulation_but_allow_camera_producer():
    clock = FakeClock()
    app = create_app(False, clock=clock.monotonic, wall_clock=clock.wall, run_ticker=False)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        state = ws.receive_json()
        assert state["dev_controls"] is False
        assert state["input_source"] == "camera"
        assert command(ws, "preview_display", display="reminding")["type"] == "error"
        assert command(ws, "clear_preview")["type"] == "error"
        assert command(ws, "set_input_source", source="simulated")["type"] == "error"
        state = command(ws, "set_monitoring", enabled=True)
        assert state["camera_session"]
        before = current(client, app)
        assert observe(ws, clock, state)["type"] == "error"
        assert without_events(current(client, app)) == without_events(before)
        from tests.test_camera import upload
        assert upload(client, state["camera_session"]).status_code == 200
        state = ws.receive_json()
        assert state["frames_received"] == 1
        assert state["camera_observation"]["presence"] == "unknown"
        assert state["reminder"]["active"] is False


def test_viewer_disconnect_preserves_simulated_source_and_reconnect_has_current_reminder(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as producer:
        producer.receive_json()
        state = command(producer, "set_monitoring", enabled=True)
        state = observe(producer, clock, state, source="simulated")
        with client.websocket_connect("/ws") as viewer:
            viewer.receive_json()
            original_session = state["observation_session"]
            clock.advance(1)
            state = observe(producer, clock, state, source="simulated")
            assert viewer.receive_json() == state
            close_and_wait(client, app, viewer, 1)
        assert current(client, app)["observation_session"] == original_session
        assert current(client, app)["observation"]["source"] == "simulated"
        clock.advance(1)
        state = observe(producer, clock, state, source="simulated")
        assert state["reminder"]["active"] is True
        trigger_ids = [e["id"] for e in state["events"] if e["kind"] == "reminder_triggered"]
        with client.websocket_connect("/ws") as reconnected:
            received = reconnected.receive_json()
            assert received["reminder"] == state["reminder"]
            assert received["revision"] == state["revision"]
            assert received["observation_session"] == original_session
            assert [e["id"] for e in received["events"]
                    if e["kind"] == "reminder_triggered"] == trigger_ids


def test_producer_disconnect_invalidates_input_and_broadcasts(rig):
    client, app, clock = rig
    with client.websocket_connect("/ws") as viewer, client.websocket_connect("/ws") as producer:
        viewer.receive_json()
        producer.receive_json()
        state = command(producer, "set_monitoring", enabled=True)
        viewer.receive_json()
        state = observe(producer, clock, state, source="simulated")
        viewer.receive_json()
        original_session = state["observation_session"]
        close_and_wait(client, app, producer, 1)
        state = viewer.receive_json()
        assert state["display"] == "unavailable" and state["observation"]["source"] == "none"
        assert state["observation_session"] != original_session
        assert state["reminder"]["active"] is False
        assert observe(viewer, clock, state, source="simulated",
                       session_id=original_session)["type"] == "error"


def test_rejected_payloads_are_private_and_debug_events_are_bounded(rig, caplog):
    client, app, _ = rig
    secret = "private-camera-frame-do-not-log"
    with client.websocket_connect("/ws") as ws, caplog.at_level(logging.INFO, logger="pomo"):
        ws.receive_json()
        for _ in range(105):
            ws.send_text(json.dumps({"type": "set_monitoring", "enabled": secret}))
            assert secret not in json.dumps(ws.receive_json())
        state = current(client, app)
        assert state["revision"] == 1 and len(state["events"]) == 100
        assert secret not in json.dumps(state) and secret not in caplog.text
        assert all(len(e["message"]) <= 300 for e in state["events"])
        assert all(e["at"].endswith("+00:00") for e in state["events"])


def test_new_backend_instance_resets_state_and_tokens():
    clock = FakeClock()
    app = create_app(clock=clock.monotonic, wall_clock=clock.wall, run_ticker=False)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        original = ws.receive_json()
        command(ws, "set_muted", muted=False)
        command(ws, "set_power", enabled=False)
    restarted = create_app(clock=clock.monotonic, wall_clock=clock.wall, run_ticker=False)
    with TestClient(restarted) as client, client.websocket_connect("/ws") as ws:
        state = ws.receive_json()
        assert state["revision"] == 0 and state["powered_on"] is True
        assert state["monitoring_enabled"] is False and state["muted"] is True
        assert state["display"] == "ready" and state["reminder"]["id"] == 0
        assert state["instance_id"] != original["instance_id"]
        assert state["observation_session"] != original["observation_session"]
