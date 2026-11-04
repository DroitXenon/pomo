from fastapi.testclient import TestClient
from backend.app import create_app as app_factory
from tests.camera_helpers import DecodeProcessor


def create_app(*args):
    return app_factory(*args, processor_factory=DecodeProcessor)


def test_health_and_static():
    with TestClient(create_app()) as c:
        assert c.get('/health').json() == {'status': 'ok', 'phase': 2, 'camera_processor_ready': True}
        assert 'Pomo' in c.get('/').text
        assert c.get('/app.js').status_code == 200


def test_broadcast_reconnect_and_restart():
    with TestClient(create_app()) as c:
        with c.websocket_connect('/ws') as a, c.websocket_connect('/ws') as b:
            assert a.receive_json()['monitoring_enabled'] is False
            b.receive_json()
            a.send_json({'type': 'set_monitoring', 'enabled': True})
            state = a.receive_json()
            peer_state = b.receive_json()
            assert state['camera_session']
            assert peer_state['camera_session'] is None
            assert {**state, 'camera_session': None} == peer_state
            assert state['monitoring_enabled'] is True
            a.send_json({'type': 'preview_display', 'display': 'reminding'})
            assert a.receive_json()['display'] == 'reminding'
            b.receive_json()
            a.send_json({'type': 'set_monitoring', 'enabled': False})
            assert a.receive_json()['display'] == 'ready'
            b.receive_json()
        with c.websocket_connect('/ws') as ws:
            assert ws.receive_json()['revision'] == 3
    with TestClient(create_app()) as c, c.websocket_connect('/ws') as ws:
        assert ws.receive_json()['revision'] == 0


def test_invalid_commands():
    with TestClient(create_app()) as c, c.websocket_connect('/ws') as ws:
        ws.receive_json()
        for payload in ['bad json', '[]', '{"type":"unknown"}',
                        '{"type":"set_monitoring","enabled":"false"}',
                        '{"type":"preview_display","display":"wrong"}',
                        '{"type":"set_monitoring","enabled":true,"extra":1}',
                        '{"type":"set_monitoring"}']:
            ws.send_text(payload)
            assert ws.receive_json()['type'] == 'error'
        ws.send_bytes(b'bad binary')
        assert ws.receive_json()['type'] == 'error'
        ws.send_json({'type': 'set_monitoring', 'enabled': True})
        assert ws.receive_json()['revision'] == 1


def test_preview_disabled():
    with TestClient(create_app(False)) as c, c.websocket_connect('/ws') as ws:
        assert ws.receive_json()['dev_controls'] is False
        ws.send_json({'type': 'preview_display', 'display': 'reminding'})
        assert ws.receive_json()['type'] == 'error'
