"""Shared reminder policy with browser-camera transport and explicit source ownership."""

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import math
from pathlib import Path
import secrets
import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, TypeAdapter, ValidationError

from backend.config import BehaviourConfig, CameraConfig, PerceptionConfig
from backend.observations import Observation, Presence
from backend.policy import PolicyConfig, ReminderEngine

LOG = logging.getLogger("pomo")
PROTOCOL_VERSION = 9
Display = Literal["happy", "idle", "sad", "surprised", "bored"]


class StrictCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SetMonitoring(StrictCommand):
    type: Literal["set_monitoring"]
    enabled: StrictBool


class SetPower(StrictCommand):
    type: Literal["set_power"]
    enabled: StrictBool


class SetMuted(StrictCommand):
    type: Literal["set_muted"]
    muted: StrictBool


class SetInputSource(StrictCommand):
    type: Literal["set_input_source"]
    source: Literal["camera", "simulated"]


class CameraFailed(StrictCommand):
    type: Literal["camera_failed"]


class DismissReminder(StrictCommand):
    type: Literal["dismiss_reminder"]
    reminder_id: Annotated[StrictInt, Field(ge=1)]


class PreviewDisplay(StrictCommand):
    type: Literal["preview_display"]
    display: Display


class ClearPreview(StrictCommand):
    type: Literal["clear_preview"]


class SubmitObservation(StrictCommand):
    type: Literal["submit_observation"]
    presence: Presence
    source: Literal["simulated", "camera"]
    observed_at: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    session_id: Annotated[str, Field(min_length=1, max_length=100)]


Command = Annotated[
    SetMonitoring | SetPower | SetMuted | SetInputSource | CameraFailed
    | DismissReminder | PreviewDisplay | ClearPreview | SubmitObservation,
    Field(discriminator="type"),
]
COMMANDS = TypeAdapter(Command)


class Runtime:
    """Serialize commands, camera results, timer ticks and complete snapshots.

    The camera adapter only normalizes trusted perception results. ReminderEngine
    remains the sole owner of display states, reminders, cooldown and mute.
    """

    def __init__(self, engine, dev_controls, *, camera_config, perception_config,
                 behaviour_config, processor_factory, clock, wall_clock):
        self.engine = engine
        self.dev_controls = dev_controls
        self.instance_id = str(uuid4())
        self.revision = 0
        self.clients: set[WebSocket] = set()
        self.producer: WebSocket | None = None
        self.lock = asyncio.Lock()
        self.clock, self.wall_clock = clock, wall_clock
        self.camera_config = camera_config
        self.perception_config = perception_config
        self.behaviour_config = behaviour_config
        self.processor_factory = processor_factory
        self.processor = None
        self.head = None
        self.worker_ready = False
        self.input_source = "camera"
        self.camera_owner = None
        self.camera_session = None
        self.camera_capture_status = "paused"
        self.last_sequence = -1
        self.last_input = None
        self.frames_received = 0
        self.last_frame = None
        self.camera_observation = None
        self.head_direction = "unknown"
        self.busy = False
        self.active_job = None
        self._last_logged = 0
        self._reset_tracking()
        self._last_snapshot = self.snapshot()

    def _reset_tracking(self):
        self.camera_armed = False
        self.camera_tracking_status = "paused"
        self._present_since = None
        self._lost_since = None
        self._last_camera_observed = None
        if self.head is not None:
            self.head.reset()

    def _release_camera(self, status="paused"):
        """Drop the upload token so in-flight/old-generation results cannot apply."""
        self.camera_owner = None
        self.camera_session = None
        self.camera_capture_status = status
        self.last_sequence = -1
        self.last_input = None
        self.frames_received = 0
        self.last_frame = None
        self.camera_observation = None
        self.head_direction = "unknown"
        self._reset_tracking()
        self.camera_tracking_status = status

    def _camera_failed(self, reason):
        self._release_camera("unavailable")
        self.producer = None
        self.engine.invalidate_observations(reason)

    def snapshot(self, peer=None):
        engine_snapshot = self.engine.snapshot()
        # Presence has one policy meaning in both fields, including without a
        # camera frame. Retain detector metadata only when a frame exists.
        camera_observation = dict(self.camera_observation or {"reason": "no_camera_data"})
        camera_observation["presence"] = engine_snapshot["observation"]["presence"]
        return {
            "type": "state", "protocol_version": PROTOCOL_VERSION,
            "instance_id": self.instance_id, "revision": self.revision,
            "dev_controls": self.dev_controls, **engine_snapshot,
            "input_source": self.input_source,
            "camera_processor_ready": self.worker_ready,
            "camera_capture_status": self.camera_capture_status,
            "camera_settings": self.camera_config.browser_settings(),
            "camera_session": (self.camera_session if peer is self.camera_owner else None),
            "frames_received": self.frames_received,
            "last_frame": self.last_frame,
            "camera_observation": camera_observation,
            "head_direction": self.head_direction,
            "camera_armed": self.camera_armed,
            "camera_tracking_status": self.camera_tracking_status,
            "camera_absence_duration_seconds": (
                round(max(0.0, self._last_camera_observed - self._lost_since), 3)
                if self._last_camera_observed is not None and self._lost_since is not None
                else 0.0
            ),
        }

    def _log_events(self):
        for event in self.engine.snapshot()["events"]:
            if event["id"] > self._last_logged:
                level = {"error": logging.ERROR, "warning": logging.WARNING}.get(
                    event["level"], logging.INFO,
                )
                LOG.log(level, "%s: %s", event["kind"], event["message"])
                self._last_logged = event["id"]

    async def _send(self, ws, payload):
        await asyncio.wait_for(ws.send_json(payload), timeout=2)

    async def _broadcast_locked(self):
        """Caller holds lock; each peer receives only its own camera capability."""
        while True:
            self._last_snapshot = self.snapshot()
            self._log_events()
            peers = tuple(self.clients)
            results = await asyncio.gather(
                *(self._send(peer, self.snapshot(peer)) for peer in peers),
                return_exceptions=True,
            )
            failed = {peer for peer, result in zip(peers, results)
                      if isinstance(result, BaseException)}
            self.clients.difference_update(failed)
            if self.camera_owner is not None and self.camera_owner in failed:
                self._camera_failed("Camera source disconnected.")
                self.revision += 1
                continue
            if self.producer is not None and self.producer in failed:
                self.producer = None
                self.engine.invalidate_observations("Observation source disconnected.")
                self.revision += 1
                continue
            break

    def _tick_locked(self):
        before_session = self.engine.observation_session
        if self.camera_owner is not None:
            limit = (self.camera_config.startup_seconds
                     if self.camera_capture_status == "starting"
                     else self.camera_config.timeout_seconds)
            if (self.camera_owner not in self.clients or self.last_input is None
                    or self.clock() - self.last_input >= limit):
                self._camera_failed("Camera input timed out or disconnected.")
            elif (self._last_camera_observed is not None
                  and self.clock() - self._last_camera_observed
                  >= self.behaviour_config.observation_max_age_seconds):
                self.camera_observation = None
                self.head_direction = "unknown"
                self._reset_tracking()
                self.camera_tracking_status = "stale"
                self.engine.invalidate_observations("Camera observation became stale.")
        self.engine.tick()
        if before_session != self.engine.observation_session:
            self.producer = None

    async def connect(self, ws):
        async with self.lock:
            before = self.snapshot()
            self._tick_locked()
            if self.snapshot() != before:
                self.revision += 1
                await self._broadcast_locked()
            self.clients.add(ws)
            self.engine.record("client_connected", "Simulator/producer connected.")
            self._log_events()
            await self._send(ws, self.snapshot(ws))

    async def disconnect(self, ws):
        async with self.lock:
            self.clients.discard(ws)
            self.engine.record("client_disconnected", "Simulator/producer disconnected.")
            if self.camera_owner is ws:
                self._camera_failed("Camera source disconnected.")
                self.revision += 1
                await self._broadcast_locked()
            elif self.producer is ws:
                self.producer = None
                self.engine.invalidate_observations("Observation source disconnected.")
                self.revision += 1
                await self._broadcast_locked()
            self._log_events()

    async def reject(self, ws, message="Invalid command. Check its type, fields and value types."):
        async with self.lock:
            self.engine.record("command_rejected", message, level="warning")
            self._log_events()
            await self._send(ws, {"type": "error", "code": "invalid_command", "message": message})

    def _set_monitoring(self, enabled, ws):
        if not enabled:
            self.engine.set_monitoring(False)
            self._release_camera()
            self.producer = None
            return
        if self.input_source != "camera":
            self.engine.set_monitoring(True)
            return
        if not self.engine.powered_on:
            raise ValueError("Power on Pomo before enabling monitoring")
        if not self.worker_ready:
            raise ValueError("Camera processor unavailable; check model setup or select simulated input")
        if self.camera_owner is not None:
            if self.camera_owner is not ws:
                raise ValueError("Camera is already owned by another monitoring tab")
            return
        changed = self.engine.set_monitoring(True)
        if not changed:
            self.engine.invalidate_observations("Camera input restarted", level="info")
        self._release_camera("starting")
        self.camera_owner = ws
        self.camera_session = secrets.token_urlsafe(32)
        self.last_input = self.clock()
        self.camera_tracking_status = "awaiting_face"
        self.engine.record("camera_started", "Camera capture requested from the monitoring tab.")

    async def dispatch(self, command, ws):
        async with self.lock:
            old_session = self.engine.observation_session
            try:
                if isinstance(command, SetMonitoring):
                    self._set_monitoring(command.enabled, ws)
                elif isinstance(command, SetPower):
                    if self.engine.set_power(command.enabled):
                        self._release_camera()
                        self.producer = None
                elif isinstance(command, SetMuted):
                    self.engine.set_muted(command.muted)
                elif isinstance(command, SetInputSource):
                    if not self.engine.powered_on or self.engine.monitoring_enabled:
                        raise ValueError("Input changes require power on and monitoring paused")
                    if command.source == "simulated" and not self.dev_controls:
                        raise ValueError("Simulated observations are disabled")
                    if command.source != self.input_source:
                        self.input_source = command.source
                        self._release_camera()
                        self.producer = None
                        self.engine.clear_preview()
                        self.engine.invalidate_observations("Input source changed", level="info")
                        self.engine.record("input_source_changed", f"Input source: {command.source}")
                elif isinstance(command, CameraFailed):
                    if self.camera_owner is not ws:
                        raise ValueError("Only the camera owner can report capture failure")
                    self._camera_failed("Camera capture failed; pause and enable monitoring to retry.")
                elif isinstance(command, DismissReminder):
                    self.engine.dismiss(command.reminder_id)
                elif isinstance(command, (PreviewDisplay, ClearPreview)):
                    if not self.dev_controls:
                        raise ValueError("Development controls are disabled.")
                    if isinstance(command, PreviewDisplay):
                        self.engine.preview(command.display)
                    else:
                        self.engine.clear_preview()
                elif isinstance(command, SubmitObservation):
                    if command.source != "simulated":
                        raise ValueError("Camera observations must come from the camera frame processor")
                    if not self.dev_controls:
                        raise ValueError("Simulated observations are disabled.")
                    if self.input_source != "simulated":
                        raise ValueError("Select simulated input while monitoring is paused")
                    self.engine.observe(command.presence, command.source,
                                        command.observed_at, command.session_id)
                    self.producer = ws
            except ValueError as error:
                message = str(error)[:250]
                self.engine.record("command_rejected", message, level="warning")
                self._log_events()
                await self._send(ws, {"type": "error", "code": "invalid_command", "message": message})
                return
            if old_session != self.engine.observation_session:
                self.producer = ws if isinstance(command, SubmitObservation) else None
            self.revision += 1
            await self._broadcast_locked()

    async def tick(self):
        async with self.lock:
            self._tick_locked()
            if self.snapshot() != self._last_snapshot:
                self.revision += 1
                await self._broadcast_locked()

    async def run(self, interval):
        while True:
            await asyncio.sleep(interval)
            await self.tick()

    async def open_camera(self):
        """Optional dependencies/model failures leave the simulator usable."""
        try:
            from backend.perception import HeadDirection
            if self.processor_factory is None:
                from backend.camera import FrameProcessor
                self.processor = FrameProcessor(self.camera_config, self.perception_config)
            else:
                self.processor = self.processor_factory(self.camera_config)
            self.head = HeadDirection(self.perception_config)
            await asyncio.get_running_loop().run_in_executor(
                self.processor.executor, self.processor.open,
            )
            self.worker_ready = True
        except Exception:
            LOG.exception("Camera processor initialization failed; check dependencies and model setup")
            self.camera_capture_status = "unavailable"
            self.camera_tracking_status = "unavailable"
            self.engine.record("camera_unavailable", "Camera processor unavailable; simulated input remains usable.",
                               level="error")
        self._last_snapshot = self.snapshot()

    def _normalized_presence(self, observation, now):
        """Require a visible baseline and grace before treating tracking loss as absence."""
        at = observation.observed_at
        if (now - at >= self.behaviour_config.observation_max_age_seconds
                or (self._last_camera_observed is not None
                    and at - self._last_camera_observed
                    >= self.behaviour_config.observation_max_age_seconds)):
            self._reset_tracking()
        self._last_camera_observed = at
        if observation.presence in ("uncertain", "unavailable"):
            self._reset_tracking()
            self._last_camera_observed = at
            self.camera_tracking_status = (
                "uncertain" if observation.presence == "uncertain"
                else "stale" if observation.reason == "stale" else "unavailable"
            )
            return observation.presence
        if observation.presence == "present":
            self._lost_since = None
            if self._present_since is None:
                self._present_since = at
            if at - self._present_since >= self.behaviour_config.return_seconds:
                self.camera_armed = True
            self.camera_tracking_status = "present" if self.camera_armed else "confirming_face"
            return "present"
        self._present_since = None
        if self._lost_since is None:
            self._lost_since = at
        if not self.camera_armed:
            self.camera_tracking_status = (
                "tracking_loss" if at - self._lost_since < self.behaviour_config.tracking_loss_grace_seconds
                else "possible_absence"
            )
            return "uncertain"
        if at - self._lost_since < self.behaviour_config.tracking_loss_grace_seconds:
            self.camera_tracking_status = "tracking_loss"
            return "uncertain"
        self.camera_tracking_status = "absence"
        return "absent"

    async def camera_frame(self, request):
        token = request.headers.get("x-camera-session", "")
        sequence_text = request.headers.get("x-frame-sequence", "")
        if (not sequence_text.isascii() or not sequence_text.isdecimal()
                or len(sequence_text) > 16):
            raise HTTPException(400, "Invalid frame sequence")
        sequence = int(sequence_text)
        async with self.lock:
            if (not self.camera_session or not token.isascii()
                    or not secrets.compare_digest(token, self.camera_session)):
                raise HTTPException(409, "Camera session expired or not owned")
            if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
                raise HTTPException(415, "Expected image/jpeg")
            if sequence <= self.last_sequence:
                raise HTTPException(409, "Stale frame sequence")
            if self.busy:
                raise HTTPException(429, "Camera processor busy")
            limit = (self.camera_config.startup_seconds
                     if self.camera_capture_status == "starting"
                     else self.camera_config.timeout_seconds)
            if self.last_input is None or self.clock() - self.last_input >= limit:
                self._camera_failed("Camera upload session expired.")
                self.revision += 1
                await self._broadcast_locked()
                raise HTTPException(409, "Camera session expired")
            self.busy = True
            observation_session = self.engine.observation_session
        received, received_wall = self.clock(), self.wall_clock()
        job = None
        try:
            async with asyncio.timeout(self.camera_config.timeout_seconds):
                encoded = bytearray()
                async for chunk in request.stream():
                    if len(encoded) + len(chunk) > self.camera_config.max_bytes:
                        raise HTTPException(413, "Frame exceeds configured size")
                    encoded.extend(chunk)
                if not encoded:
                    raise HTTPException(400, "Empty frame")
                async with self.lock:
                    if token != self.camera_session:
                        raise HTTPException(409, "Camera session expired")
                    self.last_sequence = sequence
                job = asyncio.get_running_loop().run_in_executor(
                    self.processor.executor, self.processor.process, bytes(encoded),
                )
                self.active_job = job
                result = await asyncio.shield(job)
            async with self.lock:
                now = self.clock()
                if (token != self.camera_session or observation_session != self.engine.observation_session
                        or now - received >= self.camera_config.timeout_seconds):
                    raise HTTPException(409, "Frame expired during processing")
                raw = result.get("observation", {"presence": "unavailable", "reason": "missing_result"})
                if now - received >= self.behaviour_config.observation_max_age_seconds:
                    raw = {"presence": "unavailable", "reason": "stale"}
                observation = Observation(observed_at=received, processed_at=now, **raw)
                tracking = (self.camera_armed, self.camera_tracking_status,
                            self._present_since, self._lost_since, self._last_camera_observed,
                            self.head.direction)
                try:
                    presence = self._normalized_presence(observation, now)
                    self.engine.observe(
                        presence, "camera", received_wall, observation_session,
                        transient_loss=(self.camera_armed and
                                        self.camera_tracking_status == "tracking_loss"),
                    )
                except ValueError as error:
                    # Validation rejects duplicates/expired input before policy mutation.
                    # Keep the perception adapter equally atomic on that rejected frame.
                    (self.camera_armed, self.camera_tracking_status,
                     self._present_since, self._lost_since, self._last_camera_observed,
                     self.head.direction) = tracking
                    raise HTTPException(409, "Camera observation expired; restart monitoring") from error
                self.last_input = now
                self.camera_capture_status = "available"
                self.frames_received += 1
                self.last_frame = {"width": result["width"], "height": result["height"], "sequence": sequence}
                self.camera_observation = observation.model_dump()
                self.camera_observation["presence"] = presence
                self.head_direction = self.head.classify(
                    observation.head_pose if observation.presence == "present" else None,
                )
                self.revision += 1
                await self._broadcast_locked()
            return {"accepted": True, "sequence": sequence}
        except TimeoutError as error:
            async with self.lock:
                if token == self.camera_session:
                    self._camera_failed("Camera frame processing timed out.")
                    self.revision += 1
                    await self._broadcast_locked()
            raise HTTPException(408, "Frame processing timed out") from error
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(400, "Invalid camera frame or observation") from error
        except Exception as error:
            LOG.exception("Camera frame processor failed")
            async with self.lock:
                if token == self.camera_session:
                    self._camera_failed("Camera frame processing failed.")
                    self.revision += 1
                    await self._broadcast_locked()
            raise HTTPException(503, "Camera processing unavailable") from error
        finally:
            # Cancellation/timeout cannot queue new jobs behind a still-running inference.
            if job is not None and not job.done():
                def finished(future):
                    self.busy = False
                    if not future.cancelled():
                        future.exception()
                job.add_done_callback(finished)
            else:
                self.busy = False

    async def close(self):
        async with self.lock:
            self._release_camera()
            await asyncio.gather(
                *(asyncio.wait_for(ws.close(code=1001), timeout=2)
                  for ws in tuple(self.clients)), return_exceptions=True,
            )
            self.clients.clear()
            self.producer = None
        if self.active_job is not None:
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(self.active_job)
        if self.processor is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    self.processor.executor, self.processor.close,
                )
            finally:
                self.processor.executor.shutdown(wait=True, cancel_futures=True)


def create_app(
    dev_controls: bool = True, *, config: PolicyConfig | None = None,
    clock=time.monotonic, wall_clock=time.time, initially_muted: bool = True,
    tick_interval: float = 0.25, run_ticker: bool = True,
    camera_config: CameraConfig | None = None,
    perception_config: PerceptionConfig | None = None,
    behaviour_config: BehaviourConfig | None = None, processor_factory=None,
) -> FastAPI:
    if not math.isfinite(tick_interval) or tick_interval <= 0:
        raise ValueError("tick_interval must be finite and positive")
    if config is None and behaviour_config is not None:
        config = PolicyConfig(absence_seconds=behaviour_config.absence_seconds)
    engine = ReminderEngine(config, clock=clock, wall_clock=wall_clock,
                            initially_muted=initially_muted)
    runtime = Runtime(engine, dev_controls, camera_config=camera_config or CameraConfig(),
                      perception_config=perception_config or PerceptionConfig(),
                      behaviour_config=behaviour_config or BehaviourConfig(),
                      processor_factory=processor_factory, clock=clock, wall_clock=wall_clock)

    @asynccontextmanager
    async def lifespan(app):
        await runtime.open_camera()
        ticker = asyncio.create_task(runtime.run(tick_interval)) if run_ticker else None
        try:
            yield
        finally:
            if ticker is not None:
                ticker.cancel()
                with suppress(asyncio.CancelledError):
                    await ticker
            await runtime.close()

    app = FastAPI(title="Pomo simulator", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.engine = engine

    @app.get("/health")
    async def health():
        return {"status": "ok", "phase": 2, "protocol_version": PROTOCOL_VERSION,
                "camera_processor_ready": runtime.worker_ready}

    @app.post("/camera/frame")
    async def camera_frame(request: Request):
        return await runtime.camera_frame(request)

    @app.websocket("/ws")
    async def websocket(ws: WebSocket):
        await ws.accept()
        try:
            await runtime.connect(ws)
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                raw = message.get("text")
                try:
                    if raw is None or len(raw) > 4096:
                        raise ValueError("Expected a bounded JSON text command")
                    command = COMMANDS.validate_python(json.loads(raw))
                except (ValueError, ValidationError, RecursionError):
                    await runtime.reject(ws)
                    continue
                await runtime.dispatch(command, ws)
        except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
            pass
        finally:
            await runtime.disconnect(ws)

    app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "simulator",
                              html=True), name="simulator")
    return app
