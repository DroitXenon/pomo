from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import anyio
import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app as app_factory
from backend.config import CameraConfig
from tests.camera_helpers import DecodeProcessor


def create_app(*args, **kwargs):
    kwargs.setdefault("run_ticker", False)
    return app_factory(*args, **kwargs)


def jpeg(width=64, height=48):
    return cv2.imencode('.jpg', np.zeros((height, width, 3), dtype=np.uint8))[1].tobytes()


def start(ws):
    ws.receive_json()
    ws.send_json({'type': 'set_monitoring', 'enabled': True})
    return ws.receive_json()['camera_session']


def upload(client, token, seq=0, content=None, **headers):
    return client.post('/camera/frame', content=jpeg() if content is None else content,
                       headers={'content-type': 'image/jpeg', 'x-camera-session': token,
                                'x-frame-sequence': str(seq), **headers})


def close_owner(client, ws):
    """Let the actual disconnect finish before TestClient cancels its task."""
    ws.close()

    async def wait_for_release():
        with anyio.fail_after(2):
            while client.app.state.runtime.camera_owner is not None:
                await anyio.lowlevel.checkpoint()

    client.portal.call(wait_for_release)


def test_owner_upload_and_other_tab_cannot_take_over():
    with TestClient(create_app(processor_factory=DecodeProcessor)) as client:
        with client.websocket_connect('/ws') as owner, client.websocket_connect('/ws') as viewer:
            token = start(owner)
            assert viewer.receive_json()['camera_session'] is None
            assert viewer.receive_json()['camera_session'] is None
            viewer.send_json({'type': 'set_monitoring', 'enabled': True})
            assert viewer.receive_json()['type'] == 'error'
            assert upload(client, 'wrong').status_code == 409
            assert upload(client, token).json() == {'accepted': True, 'sequence': 0}
            state = owner.receive_json()
            assert state['last_frame'] == {'width': 64, 'height': 48, 'sequence': 0}
            assert state['camera_capture_status'] == 'available'
            assert viewer.receive_json()['frames_received'] == 1
            assert upload(client, token).status_code == 409
            viewer.send_json({'type': 'set_monitoring', 'enabled': False})
            assert viewer.receive_json()['camera_capture_status'] == 'paused'
            assert owner.receive_json()['camera_session'] is None
            assert upload(client, token, 1).status_code == 409


def test_default_camera_source_and_private_session_are_not_broadcast_to_viewers():
    with TestClient(create_app(processor_factory=DecodeProcessor)) as client:
        with client.websocket_connect('/ws') as owner:
            initial = owner.receive_json()
            assert initial['input_source'] == 'camera'
            assert initial['camera_session'] is None
            assert initial['protocol_version'] == 7
            owner.send_json({'type': 'set_monitoring', 'enabled': True})
            active = owner.receive_json()
            assert active['camera_session']
            with client.websocket_connect('/ws') as viewer:
                snapshot = viewer.receive_json()
                assert snapshot['camera_session'] is None
                assert snapshot['monitoring_enabled'] is True
                assert snapshot['observation_session'] == active['observation_session']
                viewer.send_json({'type': 'camera_failed'})
                assert viewer.receive_json()['type'] == 'error'
                assert upload(client, active['camera_session']).status_code == 200
                assert owner.receive_json()['frames_received'] == 1
                assert viewer.receive_json()['frames_received'] == 1


@pytest.mark.parametrize('content,headers,expected', [
    (b'', {}, 400), (b'not jpeg', {}, 400),
    (jpeg(641, 20), {}, 400), (b'x' * 524289, {}, 413),
    (jpeg(), {'content-type': 'image/png'}, 415),
    (jpeg(), {'x-frame-sequence': '-1'}, 400),
    (jpeg(), {'x-frame-sequence': '9' * 17}, 400),
])
def test_invalid_frames_do_not_become_available(content, headers, expected):
    with TestClient(create_app(processor_factory=DecodeProcessor)) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            assert upload(client, token, content=content, **headers).status_code == expected
            close_owner(client, ws)
        with client.websocket_connect('/ws') as observer:
            state = observer.receive_json()
            assert state['monitoring_enabled'] is True
            assert state['display'] == 'unavailable'


def test_disconnect_invalidates_owner_session():
    with TestClient(create_app(processor_factory=DecodeProcessor)) as client:
        with client.websocket_connect('/ws') as observer:
            observer.receive_json()
            with client.websocket_connect('/ws') as owner:
                token = start(owner)
                observer.receive_json()
                close_owner(client, owner)
            state = observer.receive_json()
            assert state['camera_capture_status'] == 'unavailable'
            assert state['monitoring_enabled']
            assert state['display'] == 'unavailable'
            assert upload(client, token).status_code == 409
            observer.send_json({'type': 'set_monitoring', 'enabled': True})
            assert observer.receive_json()['camera_session'] != token


def test_watchdog_expires_session_without_new_frames():
    now = [100.0]
    with TestClient(create_app(processor_factory=DecodeProcessor, clock=lambda: now[0])) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            now[0] += 31
            client.portal.call(client.app.state.runtime.tick)
            assert ws.receive_json()['camera_capture_status'] == 'unavailable'
            assert upload(client, token).status_code == 409


def test_single_worker_backpressure_and_pause_during_processing():
    entered, release = Event(), Event()
    threads = []

    class BlockingProcessor(DecodeProcessor):
        def open(self):
            threads.append(get_ident())

        def process(self, encoded):
            threads.append(get_ident())
            entered.set()
            assert release.wait(5)
            return super().process(encoded)

        def close(self):
            threads.append(get_ident())

    with TestClient(create_app(processor_factory=BlockingProcessor)) as client:
        with client.websocket_connect('/ws') as ws, ThreadPoolExecutor(1) as pool:
            token = start(ws)
            pending = pool.submit(upload, client, token)
            try:
                assert entered.wait(3)
                assert upload(client, token, 1).status_code == 429
                assert client.get('/health').status_code == 200
                ws.send_json({'type': 'set_monitoring', 'enabled': False})
                assert ws.receive_json()['camera_capture_status'] == 'paused'
            finally:
                release.set()
            assert pending.result(3).status_code == 409
    assert len(threads) == 3 and len(set(threads)) == 1


def test_initialization_failure_is_reported_without_crashing_server():
    class BrokenProcessor(DecodeProcessor):
        def open(self):
            raise RuntimeError('missing model')
    with TestClient(create_app(processor_factory=BrokenProcessor)) as client:
        assert not client.get('/health').json()['camera_processor_ready']
        with client.websocket_connect('/ws') as ws:
            assert ws.receive_json()['camera_capture_status'] == 'unavailable'
            ws.send_json({'type': 'set_monitoring', 'enabled': True})
            assert ws.receive_json()['type'] == 'error'
            ws.send_json({'type': 'set_input_source', 'source': 'simulated'})
            selected = ws.receive_json()
            assert selected['input_source'] == 'simulated'
            ws.send_json({'type': 'set_monitoring', 'enabled': True})
            assert ws.receive_json()['monitoring_enabled'] is True


def test_processing_timeout_keeps_worker_slot_until_job_finishes():
    entered, release, completed = Event(), Event(), Event()

    class SlowProcessor(DecodeProcessor):
        def process(self, encoded):
            entered.set()
            assert release.wait(5)
            try:
                return super().process(encoded)
            finally:
                completed.set()

    config = CameraConfig(timeout_seconds=0.1)
    with TestClient(create_app(camera_config=config, processor_factory=SlowProcessor)) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            try:
                assert upload(client, token).status_code == 408
                assert entered.is_set()
                failed = ws.receive_json()
                assert failed['camera_session'] is None
                assert failed['monitoring_enabled'] is True
                assert failed['display'] == 'unavailable'
                assert upload(client, token, 1).status_code == 409
                ws.send_json({'type': 'set_monitoring', 'enabled': True})
                retry_token = ws.receive_json()['camera_session']
                assert retry_token and retry_token != token
                assert upload(client, retry_token).status_code == 429
                ws.send_json({'type': 'set_monitoring', 'enabled': False})
                assert ws.receive_json()['camera_capture_status'] == 'paused'
            finally:
                release.set()
            assert completed.wait(3)


def test_worker_error_invalidates_session():
    class BrokenDecode(DecodeProcessor):
        def process(self, encoded):
            raise RuntimeError('decoder failed')
    with TestClient(create_app(processor_factory=BrokenDecode)) as client:
        with client.websocket_connect('/ws') as ws:
            token = start(ws)
            assert upload(client, token).status_code == 503
            state = ws.receive_json()
            assert state['camera_capture_status'] == 'unavailable'
            assert state['camera_session'] is None
            assert upload(client, token, 1).status_code == 409
