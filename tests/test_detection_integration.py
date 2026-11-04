"""Synthetic JPEG detections through the unified camera/policy transport."""

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.config import BehaviourConfig
from backend.policy import PolicyConfig
from tests.camera_helpers import DecodeProcessor
from tests.test_camera import start, upload


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def wall(self):
        return 1_790_000_000.0 + self.now

    def advance(self, seconds):
        self.now += seconds


def harness():
    clock = FakeClock()
    detection = {'presence': 'present', 'head_pose': {'yaw': 0, 'pitch': 0, 'roll': 0}}

    class ScriptedProcessor(DecodeProcessor):
        def analyse(self, rgb):
            return dict(detection)

    app = create_app(
        processor_factory=ScriptedProcessor, clock=clock.monotonic,
        wall_clock=clock.wall, run_ticker=False,
        config=PolicyConfig(absence_seconds=1, cooldown_seconds=2,
                            observation_timeout_seconds=3),
        behaviour_config=BehaviourConfig(absence_seconds=1,
            tracking_loss_grace_seconds=0.25, return_seconds=0.25),
    )
    return app, clock, detection


class CameraDriver:
    def __init__(self, client, ws, clock, detection):
        self.client, self.ws = client, ws
        self.clock, self.detection = clock, detection
        self.token = start(ws)
        self.sequence = 0

    def frame(self, presence=None, advance=0.25):
        if presence is not None:
            self.detection['presence'] = presence
        self.clock.advance(advance)
        result = upload(self.client, self.token, self.sequence)
        assert result.status_code == 200, result.text
        self.sequence += 1
        return self.ws.receive_json()

    def arm(self):
        state = self.frame('present', advance=0)
        assert state['camera_observation']['presence'] == 'present'
        state = self.frame('present')
        assert state['camera_armed'] is True
        assert state['behavior_state'] == 'ready'
        return state

    def remind(self):
        self.arm()
        state = self.frame('not_detected')
        assert state['reminder']['active'] is False
        for _ in range(5):
            state = self.frame('not_detected')
        assert state['behavior_state'] == 'reminding'
        assert state['display'] == 'reminding'
        assert state['reminder']['active'] is True
        return state


def send(ws, kind, **fields):
    ws.send_json({'type': kind, **fields})
    return ws.receive_json()


def test_camera_absence_reminder_mute_dismissal_cooldown_return_and_pause():
    app, clock, detection = harness()
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        state = driver.remind()
        assert state['observation']['presence'] == 'absent'
        assert state['observation']['source'] == 'camera'
        assert state['camera_observation']['presence'] == 'not_detected'
        reminder_id = state['reminder']['id']
        cue_ids = [e['id'] for e in state['events'] if e['kind'] == 'reminder_triggered']
        assert len(cue_ids) == 1
        state = send(ws, 'set_muted', muted=False)
        assert state['muted'] is False and state['reminder']['id'] == reminder_id
        state = send(ws, 'set_muted', muted=True)
        assert state['muted'] is True and state['reminder']['id'] == reminder_id
        for _ in range(12):
            state = driver.frame('not_detected')
        assert state['reminder']['id'] == reminder_id
        state = send(ws, 'dismiss_reminder', reminder_id=reminder_id)
        assert state['display'] == 'distraction'
        assert state['reminder']['active'] is False
        assert state['cooldown_remaining_seconds'] == 2
        for _ in range(7):
            state = driver.frame('not_detected')
            assert state['reminder']['active'] is False
        state = driver.frame('not_detected')
        assert state['reminder']['id'] == reminder_id + 1
        assert send(ws, 'dismiss_reminder', reminder_id=reminder_id)['type'] == 'error'
        driver.frame('present')
        state = driver.frame('present')
        assert state['display'] == 'ready' and state['reminder']['active'] is False
        assert state['cooldown_remaining_seconds'] > 0
        state = driver.frame('unknown')
        assert state['display'] == 'unavailable' and state['camera_armed'] is False
        assert state['absence_duration_seconds'] == 0
        state = send(ws, 'set_monitoring', enabled=False)
        assert state['display'] == 'ready' and state['camera_session'] is None
        assert state['camera_observation'] is None
        assert upload(client, driver.token, driver.sequence).status_code == 409


def test_camera_observation_stales_before_transport_session_timeout():
    app, clock, detection = harness()
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        state = driver.arm()
        observation_token = state['observation_session']
        clock.advance(1.1)
        client.portal.call(app.state.runtime.tick)
        state = ws.receive_json()
        assert state['camera_capture_status'] == 'available'
        assert state['monitoring_enabled'] is True
        assert state['camera_tracking_status'] == 'stale'
        assert state['camera_armed'] is False
        assert state['camera_observation'] is None
        assert state['behavior_state'] == 'unavailable'
        assert state['reminder']['active'] is False
        assert state['camera_session'] == driver.token
        assert state['observation_session'] != observation_token


def test_late_inference_is_unknown_even_when_frame_transport_succeeds():
    clock = FakeClock()

    class DelayedProcessor(DecodeProcessor):
        def analyse(self, rgb):
            clock.advance(1.1)
            return {'presence': 'present', 'head_pose': {'yaw': 0, 'pitch': 0, 'roll': 0}}

    app = create_app(processor_factory=DelayedProcessor, clock=clock.monotonic,
                     wall_clock=clock.wall, run_ticker=False)
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        token = start(ws)
        assert upload(client, token).status_code == 200
        state = ws.receive_json()
        assert state['camera_capture_status'] == 'available'
        assert state['camera_observation']['presence'] == 'unknown'
        assert state['camera_observation']['reason'] == 'stale'
        assert state['observation']['presence'] == 'unknown'
        assert state['head_direction'] == 'unknown' and state['camera_armed'] is False
        assert state['reminder']['active'] is False


def test_rejected_duplicate_camera_timestamp_rolls_back_tracking_and_diagnostics():
    clock = FakeClock()
    detection = {'presence': 'present', 'head_pose': {'yaw': 45, 'pitch': 0, 'roll': 0}}

    class ScriptedProcessor(DecodeProcessor):
        def analyse(self, rgb):
            return dict(detection)

    app = create_app(
        processor_factory=ScriptedProcessor, clock=clock.monotonic,
        wall_clock=lambda: 1_790_000_000.0, run_ticker=False,
        behaviour_config=BehaviourConfig(return_seconds=0),
    )
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        token = start(ws)
        assert upload(client, token).status_code == 200
        accepted = ws.receive_json()
        assert accepted['camera_armed'] is True
        assert accepted['head_direction'] == 'left'
        clock.advance(0.25)
        runtime = app.state.runtime
        before = client.portal.call(runtime.snapshot)
        adapter_before = (runtime._present_since, runtime._lost_since,
                          runtime._last_camera_observed, runtime.head.direction)
        detection['presence'] = 'unknown'
        assert upload(client, token, 1).status_code == 409
        assert client.portal.call(runtime.snapshot) == before
        assert (runtime._present_since, runtime._lost_since,
                runtime._last_camera_observed, runtime.head.direction) == adapter_before
        assert runtime.last_sequence == 1  # Consumed packets remain protected against replay.


def test_first_turned_face_is_reported_without_triggering_a_reminder():
    app, clock, detection = harness()
    detection['head_pose']['yaw'] = 45
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        state = driver.frame(advance=0)
        assert state['head_direction'] == 'left'
        assert state['camera_observation']['head_pose']['yaw'] == 45
        assert state['reminder']['active'] is False


def test_eye_and_blendshape_diagnostics_never_drive_absence_or_reminders():
    app, clock, detection = harness()
    detection['eye_movement'] = {
        'eyeLeft': {'direction': 'left', 'horizontal': 0.8, 'vertical': 0.5, 'reason': 'usable'},
        'eyeRight': {'direction': 'down', 'horizontal': 0.5, 'vertical': 0.8, 'reason': 'usable'},
    }
    detection['blendshapes'] = {'eyeBlinkLeft': 0.55, 'eyeBlinkRight': 0.48, 'jawOpen': 0}
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        driver.arm()
        for _ in range(48):
            state = driver.frame('present')
            assert state['reminder']['active'] is False
            assert state['display'] == 'ready'
            assert state['absence_duration_seconds'] == 0
        raw = state['camera_observation']
        assert raw['eye_movement']['eyeLeft']['direction'] == 'left'
        assert raw['eye_movement']['eyeRight']['direction'] == 'down'
        assert raw['blendshapes']['eyeBlinkRight'] == 0.48
        assert state['camera_armed'] is True
        assert not any(e['kind'] == 'reminder_triggered' for e in state['events'])


def test_closed_eye_label_and_raw_blink_score_reach_clients():
    app, clock, detection = harness()
    detection['eye_movement'] = {
        'eyeLeft': {'direction': 'closed', 'reason': 'blink'},
        'eyeRight': {'direction': 'center', 'horizontal': 0.5, 'vertical': 0.5, 'reason': 'usable'},
    }
    detection['blendshapes'] = {'eyeBlinkLeft': 0.6, 'eyeBlinkRight': 0.12}
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        state = driver.frame(advance=0)
        raw = state['camera_observation']
        assert raw['eye_movement']['eyeLeft']['direction'] == 'closed'
        assert raw['blendshapes']['eyeBlinkLeft'] == 0.6
        assert state['reminder']['active'] is False


@pytest.mark.parametrize('expression', ['ready', 'shutdown', 'distraction', 'reminding', 'unavailable'])
def test_paused_preview_is_cleared_when_camera_monitoring_starts(expression):
    app, clock, detection = harness()
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        ws.receive_json()
        state = send(ws, 'preview_display', display=expression)
        assert state['display'] == expression and state['preview_active'] is True
        assert state['reminder']['id'] == 0
        state = send(ws, 'set_monitoring', enabled=True)
        token = state['camera_session']
        assert state['preview_active'] is False and state['display'] == 'unavailable'
        assert send(ws, 'preview_display', display=expression)['type'] == 'error'
        assert upload(client, token).status_code == 200
        state = ws.receive_json()
        assert state['reminder']['id'] == 0 and state['preview_active'] is False
        state = send(ws, 'camera_failed')
        assert state['camera_capture_status'] == 'unavailable'
        assert state['monitoring_enabled'] is True and state['display'] == 'unavailable'
        assert state['camera_session'] is None and state['reminder']['active'] is False


def test_initial_no_face_is_unarmed_and_does_not_create_an_absence_reminder():
    app, clock, detection = harness()
    detection['presence'] = 'not_detected'
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        for index in range(10):
            state = driver.frame(advance=0 if index == 0 else 0.25)
            assert state['camera_observation']['presence'] == 'not_detected'
            assert state['camera_armed'] is False
            assert state['reminder']['active'] is False and state['reminder']['id'] == 0
            assert state['absence_duration_seconds'] == 0
            assert state['camera_absence_duration_seconds'] == pytest.approx(index * 0.25)
            assert state['camera_tracking_status'] == (
                'tracking_loss' if index == 0 else 'possible_absence')
            assert state['display'] == 'unavailable'
        state = driver.frame('unknown')
        assert state['camera_tracking_status'] == 'uncertain'
        assert state['absence_duration_seconds'] == 0
        assert state['camera_absence_duration_seconds'] == 0


def test_camera_owner_failure_and_retry_then_power_cycle_reject_old_frames():
    app, clock, detection = harness()
    with TestClient(app) as client, client.websocket_connect('/ws') as ws:
        driver = CameraDriver(client, ws, clock, detection)
        active = driver.remind()
        old_observation_session = active['observation_session']
        state = send(ws, 'camera_failed')
        assert state['monitoring_enabled'] is True and state['display'] == 'unavailable'
        assert state['camera_session'] is None and state['reminder']['active'] is False
        assert state['observation_session'] != old_observation_session
        assert state['cooldown_remaining_seconds'] > 0
        assert upload(client, driver.token, driver.sequence).status_code == 409
        state = send(ws, 'set_monitoring', enabled=True)
        retry_token = state['camera_session']
        assert retry_token and retry_token != driver.token
        state = send(ws, 'set_power', enabled=False)
        assert state['display'] == 'shutdown' and state['monitoring_enabled'] is False
        assert state['camera_session'] is None and state['cooldown_remaining_seconds'] == 0
        assert upload(client, retry_token).status_code == 409
        state = send(ws, 'set_power', enabled=True)
        assert state['display'] == 'ready' and state['monitoring_enabled'] is False
        assert state['camera_observation'] is None


def test_camera_viewer_reconnect_preserves_active_reminder_but_owner_disconnect_clears_it():
    app, clock, detection = harness()
    with TestClient(app) as client, client.websocket_connect('/ws') as owner:
        driver = CameraDriver(client, owner, clock, detection)
        state = driver.remind()
        cue_ids = [e['id'] for e in state['events'] if e['kind'] == 'reminder_triggered']
        with client.websocket_connect('/ws') as viewer:
            reconnected = viewer.receive_json()
            assert reconnected['reminder'] == state['reminder']
            assert reconnected['camera_session'] is None
            assert [e['id'] for e in reconnected['events']
                    if e['kind'] == 'reminder_triggered'] == cue_ids
            owner.close()
            failed = viewer.receive_json()
            assert failed['display'] == 'unavailable' and failed['monitoring_enabled'] is True
            assert failed['reminder']['active'] is False and failed['camera_session'] is None
            assert upload(client, driver.token, driver.sequence).status_code == 409
