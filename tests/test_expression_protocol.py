"""Exercise renamed expressions through the shared command and snapshot path."""
import asyncio

import pytest
from pydantic import ValidationError

from backend.app import COMMANDS, create_app
from backend.policy import PolicyConfig


class Peer:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        if message.get('type') == 'state':
            assert message['camera_observation']['presence'] == message['observation']['presence']
        self.messages.append(message)


def test_expression_commands_and_state_transitions():
    async def exercise():
        now = [1000.0]
        app = create_app(config=PolicyConfig(absence_seconds=2, observation_timeout_seconds=3),
                         clock=lambda: now[0], wall_clock=lambda: now[0], run_ticker=False)
        runtime = app.state.runtime
        peer = Peer()
        await runtime.connect(peer)
        assert peer.messages[-1]['protocol_version'] == 9
        assert peer.messages[-1]['display'] == 'happy'

        async def send(**payload):
            await runtime.dispatch(COMMANDS.validate_python(payload), peer)
            return peer.messages[-1]

        for expression in ('happy', 'sad', 'surprised', 'bored', 'idle'):
            state = await send(type='preview_display', display=expression)
            assert state['display'] == expression
            assert state['behavior_state'] == 'happy'
            assert not state['reminder']['active']
        for legacy in ('ready', 'distraction', 'reminding', 'unavailable', 'shutdown'):
            with pytest.raises(ValidationError):
                COMMANDS.validate_python({'type': 'preview_display', 'display': legacy})

        await send(type='set_input_source', source='simulated')
        state = await send(type='set_monitoring', enabled=True)
        assert state['display'] == state['behavior_state'] == 'bored'

        async def observe(presence):
            now[0] += 0.5
            return await send(type='submit_observation', presence=presence, source='simulated',
                              observed_at=now[0], session_id=runtime.engine.observation_session)

        assert (await observe('present'))['display'] == 'happy'
        assert (await observe('absent'))['display'] == 'sad'
        for _ in range(4):
            state = await observe('absent')
        assert state['display'] == 'surprised' and state['reminder']['active']
        assert (await observe('uncertain'))['display'] == 'bored'
        state = await observe('unavailable')
        assert state['observation']['presence'] == 'unavailable'
        assert state['camera_observation']['presence'] == 'unavailable'
        with pytest.raises(ValidationError):
            COMMANDS.validate_python({'type': 'submit_observation', 'presence': 'unknown',
                                      'source': 'simulated', 'observed_at': now[0],
                                      'session_id': runtime.engine.observation_session})
        state = await send(type='set_power', enabled=False)
        assert state['display'] == state['behavior_state'] == 'idle'
        await runtime.disconnect(peer)

    asyncio.run(exercise())


def test_websocket_protocol_v9_preview_and_legacy_rejection():
    import json

    async def exercise():
        app = create_app(run_ticker=False)
        inbound, outbound = asyncio.Queue(), asyncio.Queue()
        scope = {
            'type': 'websocket', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
            'http_version': '1.1', 'scheme': 'ws', 'path': '/ws', 'raw_path': b'/ws',
            'query_string': b'', 'headers': [], 'client': ('127.0.0.1', 1234),
            'server': ('127.0.0.1', 8000), 'subprotocols': [], 'root_path': '',
        }
        await inbound.put({'type': 'websocket.connect'})
        task = asyncio.create_task(app(scope, inbound.get, outbound.put))
        try:
            assert (await asyncio.wait_for(outbound.get(), 2))['type'] == 'websocket.accept'

            async def receive():
                message = await asyncio.wait_for(outbound.get(), 2)
                assert message['type'] == 'websocket.send'
                return json.loads(message['text'])

            initial = await receive()
            assert initial['protocol_version'] == 9 and initial['display'] == 'happy'
            assert initial['observation']['presence'] == initial['camera_observation']['presence'] == 'unavailable'
            await inbound.put({'type': 'websocket.receive', 'text': json.dumps(
                {'type': 'preview_display', 'display': 'sad'})})
            state = await receive()
            assert state['display'] == 'sad' and state['behavior_state'] == 'happy'
            await inbound.put({'type': 'websocket.receive', 'text': json.dumps(
                {'type': 'preview_display', 'display': 'distraction'})})
            assert (await receive())['type'] == 'error'
        finally:
            await inbound.put({'type': 'websocket.disconnect', 'code': 1000})
            await asyncio.wait_for(task, 2)

    asyncio.run(exercise())
