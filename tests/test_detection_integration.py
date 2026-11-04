"""Synthetic detections through the real HTTP/WebSocket and policy integration."""
import pytest

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import BehaviourConfig
from tests.camera_helpers import DecodeProcessor
from tests.test_camera import start, upload


def harness():
    now = [100.0]
    detection = {'presence': 'present', 'head_pose': {'yaw': 0, 'pitch': 0, 'roll': 0}}
    class ScriptedProcessor(DecodeProcessor):
        def analyse(self, rgb):
            return dict(detection)
    app = create_app(processor_factory=ScriptedProcessor, clock=lambda: now[0],
                     behaviour_config=BehaviourConfig(absence_seconds=1,
                         tracking_loss_grace_seconds=0.25, return_seconds=0.25))
    return app, now, detection


def test_observations_absence_reminder_dismissal_and_pause():
    app, now, detection = harness()
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            seq = 0
            def frame(presence='present'):
                nonlocal seq
                detection['presence'] = presence
                assert upload(client, token, seq).status_code == 200
                seq += 1
                return ws.receive_json()
            initial = frame()
            assert initial['observation']['presence'] == 'present'
            assert initial['head_direction'] == 'forward'
            detection['head_pose']['yaw'] = 40
            now[0] += 0.25
            state = frame()
            assert state['head_direction'] == 'left' and state['behaviour']['armed']
            assert not state['behaviour']['reminder_active']
            now[0] += 0.25
            assert frame('not_detected')['behaviour']['status'] == 'tracking_loss'
            now[0] += 0.25
            assert frame('not_detected')['behaviour']['status'] == 'possible_absence'
            for _ in range(3):
                now[0] += 0.25
                state = frame('not_detected')
            assert state['behaviour']['status'] == 'reminding'
            ws.send_json({'type': 'dismiss_reminder'})
            assert not ws.receive_json()['behaviour']['reminder_active']
            now[0] += 0.25
            assert not frame('not_detected')['behaviour']['reminder_active']
            now[0] += 0.25
            state = frame('unknown')
            assert state['camera_status'] == 'available' and state['behaviour']['status'] == 'uncertain'
            assert not state['behaviour']['armed']
            ws.send_json({'type': 'set_monitoring', 'enabled': False})
            state = ws.receive_json()
            assert state['observation'] is None and state['display'] == 'ready'
            assert upload(client, token, seq).status_code == 409


def test_watchdog_stales_observation_before_transport_timeout():
    app, now, _ = harness()
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            assert upload(client, token).status_code == 200
            ws.receive_json()
            now[0] += 1.1
            state = ws.receive_json()
            assert state['behaviour']['status'] == 'stale'
            assert state['camera_status'] == 'available' and state['monitoring_enabled']
            assert state['observation'] is None and state['behaviour']['status'] == 'stale'


def test_manual_preview_dismissal_does_not_mutate_state():
    app, _, _ = harness()
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            ws.receive_json()
            ws.send_json({'type': 'preview_display', 'display': 'reminding'})
            assert not ws.receive_json()['behaviour']['reminder_active']
            ws.send_json({'type': 'dismiss_reminder'})
            assert ws.receive_json()['type'] == 'error'
        with client.websocket_connect('/ws') as ws:
            state = ws.receive_json()
            assert state['revision'] == 1 and state['display'] == 'reminding'


def test_late_inference_is_unknown_even_when_frame_transport_succeeds():
    now = [100.0]
    class DelayedProcessor(DecodeProcessor):
        def analyse(self, rgb):
            now[0] += 1.1
            return {'presence': 'present', 'head_pose': {'yaw': 0, 'pitch': 0, 'roll': 0}}
    with TestClient(create_app(processor_factory=DelayedProcessor, clock=lambda: now[0])) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            assert upload(client, token).status_code == 200
            state = ws.receive_json()
            assert state['camera_status'] == 'available'
            assert state['observation']['presence'] == 'unknown'
            assert state['observation']['reason'] == 'stale'
            assert state['head_direction'] == 'unknown'
            assert not state['behaviour']['armed']


def test_first_turned_face_gets_automatic_direction():
    app, _, detection = harness()
    detection['head_pose']['yaw'] = 45
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            assert upload(client, token).status_code == 200
            state = ws.receive_json()
            assert state['head_direction'] == 'left'
            assert state['observation']['head_pose']['yaw'] == 45


def test_eye_observations_reach_clients_without_driving_reminders():
    app, now, detection = harness()
    detection['eye_movement'] = {'eyeLeft': {'direction':'left','horizontal':0.8,'vertical':0.5,'reason':'usable'},
                                'eyeRight': {'direction':'down','horizontal':0.5,'vertical':0.8,'reason':'usable'}}
    detection['blendshapes'] = {'eyeBlinkLeft':0.55,'eyeBlinkRight':0.48,'jawOpen':0}
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            assert upload(client, token).status_code == 200
            state = ws.receive_json()
            assert state['observation']['eye_movement']['eyeLeft']['direction'] == 'left'
            assert state['observation']['eye_movement']['eyeRight']['direction'] == 'down'
            assert state['observation']['blendshapes']['eyeBlinkRight'] == 0.48
            assert not state['behaviour']['reminder_active']
            for sequence in range(1, 49):
                now[0] += 0.25
                assert upload(client, token, sequence).status_code == 200
                state = ws.receive_json()
                assert not state['behaviour']['reminder_active']
                assert state['display'] == 'ready'
            assert state['behaviour']['armed']


def test_closed_eye_label_and_raw_blink_score_reach_clients():
    app, _, detection=harness()
    detection['eye_movement']={'eyeLeft':{'direction':'closed','reason':'blink'},
                               'eyeRight':{'direction':'center','horizontal':0.5,'vertical':0.5,'reason':'usable'}}
    detection['blendshapes']={'eyeBlinkLeft':0.6,'eyeBlinkRight':0.12}
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token=start(ws)
            assert upload(client,token).status_code==200
            state=ws.receive_json()
            assert state['observation']['eye_movement']['eyeLeft']['direction']=='closed'
            assert state['observation']['blendshapes']['eyeBlinkLeft']==0.6
            assert not state['behaviour']['reminder_active']


@pytest.mark.parametrize('expression',['ready','possible_absence','reminding','unavailable'])
def test_manual_expression_survives_detections_dismissal_stale_input_and_camera_failure(expression):
    app,now,detection=harness()
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token=start(ws)
            ws.send_json({'type':'preview_display','display':expression})
            assert ws.receive_json()['display']==expression
            sequence=0
            def frame(presence):
                nonlocal sequence
                detection['presence']=presence
                now[0]+=0.25
                assert upload(client,token,sequence).status_code==200
                sequence+=1
                snapshot=ws.receive_json()
                assert snapshot['display']==expression
                return snapshot
            frame('present')
            frame('present')
            for _ in range(5):
                snapshot=frame('not_detected')
            assert snapshot['behaviour']['reminder_active']
            ws.send_json({'type':'dismiss_reminder'})
            assert ws.receive_json()['display']==expression
            frame('unknown')
            now[0]+=1.1
            stale=ws.receive_json()
            assert stale['behaviour']['status']=='stale' and stale['display']==expression
            ws.send_json({'type':'camera_failed'})
            failed=ws.receive_json()
            assert failed['camera_status']=='unavailable' and failed['display']==expression


def test_initial_no_face_counts_and_triggers_possible_absence_without_baseline():
    app,now,detection=harness()
    detection['presence']='not_detected'
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as ws:
            token=start(ws)
            ws.send_json({'type':'preview_display','display':'ready'})
            ws.receive_json()
            for sequence in range(9):
                now[0]=100+sequence*.25
                assert upload(client,token,sequence).status_code==200
                state=ws.receive_json()
                assert state['behaviour']['absence_seconds']==sequence*.25
                assert state['behaviour']['status']==('tracking_loss' if sequence==0 else 'possible_absence')
                assert not state['behaviour']['armed']
                assert not state['behaviour']['reminder_active']
                assert state['display']=='ready'
            detection['presence']='unknown'
            now[0]+=.25
            assert upload(client,token,9).status_code==200
            state=ws.receive_json()
            assert state['behaviour']['absence_seconds']==0
            assert state['behaviour']['status']=='uncertain'
