"""Shared robot transport, camera lifecycle and observation-driven behaviour."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from .camera import FrameProcessor
from .config import CameraConfig, PerceptionConfig, BehaviourConfig
from .observations import Observation
from .perception import HeadDirection
from .behaviour import Behaviour

LOG = logging.getLogger('pomo')
Display = Literal['ready', 'possible_absence', 'reminding', 'unavailable']


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['set_monitoring', 'preview_display', 'camera_failed', 'dismiss_reminder']
    enabled: StrictBool | None = None
    display: Display | None = None


def create_app(dev_controls: bool = True, *, camera_config: CameraConfig | None = None,
               processor_factory=None, clock=time.monotonic,
               perception_config: PerceptionConfig | None = None,
               behaviour_config: BehaviourConfig | None = None) -> FastAPI:
    config = camera_config or CameraConfig()
    perception_config = perception_config or PerceptionConfig()
    policy = Behaviour(behaviour_config or BehaviourConfig())
    head = HeadDirection(perception_config)
    processor = (processor_factory(config) if processor_factory else
                 FrameProcessor(config, perception_config))
    state = {'monitoring_enabled': False, 'display': 'ready',
             'camera_status': 'paused', 'revision': 0, 'frames_received': 0,
             'last_frame': None, 'observation': None, 'head_direction': 'unknown'}
    clients: set[WebSocket] = set()
    lock = asyncio.Lock()
    owner = None
    session = None
    last_sequence = -1
    last_input = 0.0
    busy = False
    worker_ready = False
    active_job = None

    def snapshot(peer=None):
        return {'type': 'state', 'protocol_version': 6, **state,
                'dev_controls': dev_controls, 'camera_settings': config.browser_settings(),
                'behaviour': policy.snapshot(),
                'camera_session': session if peer is owner else None}

    async def broadcast():
        # Caller holds lock, preserving revision/send ordering.
        for peer in tuple(clients):
            try:
                await asyncio.wait_for(peer.send_json(snapshot(peer)), timeout=2)
            except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
                clients.discard(peer)

    def reset(status):
        nonlocal owner, session, last_sequence
        owner = session = None
        last_sequence = -1
        policy.reset(unavailable=status == 'unavailable')
        head.reset()
        state.update(monitoring_enabled=False, camera_status=status,
                     frames_received=0, last_frame=None,
                     observation=None, head_direction='unknown')
        if status == 'paused':
            state['display'] = 'ready'

    async def watchdog():
        while True:
            await asyncio.sleep(0.1)
            async with lock:
                limit = (config.startup_seconds if state['camera_status'] == 'starting'
                         else config.timeout_seconds)
                if owner is not None and (owner not in clients or clock() - last_input > limit):
                    reset('unavailable')
                    state['revision'] += 1
                    await broadcast()
                previous_status = policy.status
                policy.tick(clock())
                if policy.status != previous_status:
                    state.update(observation=None, head_direction='unknown')
                    head.classify(None)
                    state['revision'] += 1
                    await broadcast()

    @asynccontextmanager
    async def lifespan(app):
        nonlocal worker_ready
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(processor.executor, processor.open)
            worker_ready = True
        except Exception:
            LOG.exception('Camera processor initialization failed; check dependencies and model')
            policy.reset(unavailable=True)
            state.update(camera_status='unavailable')
        timer = asyncio.create_task(watchdog())
        try:
            yield
        finally:
            timer.cancel()
            with suppress(asyncio.CancelledError):
                await timer
            reset('paused')
            if active_job is not None:
                with suppress(Exception):
                    await asyncio.shield(active_job)
            await loop.run_in_executor(processor.executor, processor.close)
            processor.executor.shutdown(wait=True, cancel_futures=True)

    app = FastAPI(title='Pomo prototype', lifespan=lifespan)

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'phase': 2, 'camera_processor_ready': worker_ready}

    @app.post('/camera/frame')
    async def camera_frame(request: Request):
        nonlocal busy, last_sequence, last_input, active_job
        token = request.headers.get('x-camera-session', '')
        sequence_text = request.headers.get('x-frame-sequence', '')
        if not sequence_text.isascii() or not sequence_text.isdecimal() or len(sequence_text) > 16:
            raise HTTPException(400, 'Invalid frame sequence')
        sequence = int(sequence_text)
        if not session or not token.isascii() or not secrets.compare_digest(token, session):
            raise HTTPException(409, 'Camera session expired or not owned')
        if request.headers.get('content-type', '').split(';')[0] != 'image/jpeg':
            raise HTTPException(415, 'Expected image/jpeg')
        if sequence <= last_sequence:
            raise HTTPException(409, 'Stale frame sequence')
        if busy:
            raise HTTPException(429, 'Camera processor busy')
        busy = True
        job = None
        received = clock()
        try:
            async with asyncio.timeout(config.timeout_seconds):
                encoded = bytearray()
                async for chunk in request.stream():
                    if len(encoded) + len(chunk) > config.max_bytes:
                        raise HTTPException(413, 'Frame exceeds configured size')
                    encoded.extend(chunk)
                if not encoded:
                    raise HTTPException(400, 'Empty frame')
                if token != session:
                    raise HTTPException(409, 'Camera session expired')
                last_sequence = sequence
                job = asyncio.get_running_loop().run_in_executor(
                    processor.executor, processor.process, bytes(encoded))
                active_job = job
                result = await asyncio.shield(job)
            async with lock:
                if token != session or clock() - received > config.timeout_seconds:
                    raise HTTPException(409, 'Frame expired during processing')
                observation = Observation(observed_at=received, processed_at=clock(),
                                          **result.get('observation', {'presence': 'unknown',
                                                                      'reason': 'missing_result'}))
                last_input = clock()
                if last_input - received > policy.config.observation_max_age_seconds:
                    observation = Observation(observed_at=received, processed_at=last_input,
                                              presence='unknown', reason='stale')
                policy.observe(observation, last_input)
                direction = head.classify(observation.head_pose if observation.presence == 'present' else None)
                state.update(observation=observation.model_dump(),
                             head_direction=direction)
                state.update(camera_status='available', frames_received=state['frames_received'] + 1,
                             last_frame={'width': result['width'], 'height': result['height'], 'sequence': sequence})
                state['revision'] += 1
                await broadcast()
            return {'accepted': True, 'sequence': sequence}
        except TimeoutError as error:
            raise HTTPException(408, 'Frame processing timed out') from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except HTTPException:
            raise
        except Exception as error:
            LOG.exception('Camera frame processor failed')
            async with lock:
                if token == session:
                    reset('unavailable')
                    state['revision'] += 1
                    await broadcast()
            raise HTTPException(503, 'Camera processing unavailable') from error
        finally:
            # A timed-out/cancelled request must not queue more work behind its worker.
            if job is not None and not job.done():
                def finished(future):
                    nonlocal busy
                    busy = False
                    if not future.cancelled():
                        future.exception()
                job.add_done_callback(finished)
            else:
                busy = False

    @app.websocket('/ws')
    async def websocket(ws: WebSocket):
        nonlocal owner, session, last_sequence, last_input
        await ws.accept()
        try:
            async with lock:
                clients.add(ws)
                await ws.send_json(snapshot(ws))
            while True:
                message = await ws.receive()
                if message['type'] == 'websocket.disconnect':
                    break
                try:
                    raw = message.get('text')
                    if raw is None or len(raw) > 4096:
                        raise ValueError('Expected a JSON text command under 4096 characters')
                    command = Command.model_validate(json.loads(raw))
                    if command.type == 'set_monitoring':
                        if command.enabled is None or command.display is not None:
                            raise ValueError('set_monitoring requires only enabled (boolean)')
                    elif command.type == 'preview_display':
                        if command.display is None or command.enabled is not None:
                            raise ValueError('preview_display requires only display')
                        if not dev_controls:
                            raise ValueError('Developer controls are disabled')
                    elif command.enabled is not None or command.display is not None:
                        raise ValueError(f'{command.type} accepts no fields')
                    async with lock:
                        if command.type == 'set_monitoring':
                            if command.enabled:
                                if not worker_ready:
                                    raise ValueError('Camera processor unavailable; check model setup')
                                if owner is not None:
                                    raise ValueError('Camera is already owned by a monitoring tab')
                                owner, session = ws, secrets.token_urlsafe(32)
                                last_sequence, last_input = -1, clock()
                                policy.reset(enabled=True)
                                head.reset()
                                state.update(observation=None, head_direction='unknown')
                                state.update(monitoring_enabled=True, display='ready',
                                             camera_status='starting', frames_received=0, last_frame=None)
                            else:
                                reset('paused')
                        elif command.type == 'camera_failed':
                            if owner is not ws:
                                raise ValueError('Only the camera owner can report capture failure')
                            reset('unavailable')
                        elif command.type == 'dismiss_reminder':
                            policy.dismiss()
                        else:
                            state['display'] = command.display
                        state['revision'] += 1
                        await broadcast()
                except (ValueError, ValidationError) as error:
                    async with lock:
                        await ws.send_json({'type': 'error', 'code': 'invalid_command',
                                            'message': str(error)[:500]})
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            async with lock:
                clients.discard(ws)
                if owner is ws:
                    reset('unavailable')
                    state['revision'] += 1
                    await broadcast()

    app.mount('/', StaticFiles(directory=Path(__file__).resolve().parents[1] / 'simulator',
                              html=True), name='simulator')
    return app
