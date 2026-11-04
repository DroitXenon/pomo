"""HTTP/WebSocket transport for Pomo's shared reminder policy."""

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import math
from pathlib import Path
import time
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, TypeAdapter, ValidationError

from backend.policy import PolicyConfig, ReminderEngine

LOG = logging.getLogger("pomo")
Display = Literal["ready", "shutdown", "distraction", "reminding", "unavailable"]


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
    presence: Literal["present", "absent", "unknown", "unavailable"]
    source: Literal["simulated", "camera"]
    observed_at: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    session_id: Annotated[str, Field(min_length=1, max_length=100)]


Command = Annotated[
    SetMonitoring | SetPower | SetMuted | DismissReminder | PreviewDisplay
    | ClearPreview | SubmitObservation,
    Field(discriminator="type"),
]
COMMANDS = TypeAdapter(Command)


class Runtime:
    """Serialize policy operations, timer ticks and complete-state broadcasts."""

    def __init__(self, engine: ReminderEngine, dev_controls: bool):
        self.engine = engine
        self.dev_controls = dev_controls
        self.instance_id = str(uuid4())
        self.revision = 0
        self.clients: set[WebSocket] = set()
        self.producer: WebSocket | None = None
        self.lock = asyncio.Lock()
        self._last_snapshot = engine.snapshot()
        self._last_logged = 0

    def snapshot(self):
        return {
            "type": "state", "protocol_version": 2,
            "instance_id": self.instance_id, "revision": self.revision,
            "dev_controls": self.dev_controls, **self.engine.snapshot(),
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
        """Caller holds lock; a failed producer invalidates its last observation."""
        while True:
            payload = self.snapshot()
            self._last_snapshot = self.engine.snapshot()
            self._log_events()
            peers = tuple(self.clients)
            results = await asyncio.gather(
                *(self._send(peer, payload) for peer in peers), return_exceptions=True,
            )
            failed = {peer for peer, result in zip(peers, results)
                      if isinstance(result, BaseException)}
            self.clients.difference_update(failed)
            if self.producer is not None and self.producer in failed:
                self.producer = None
                self.engine.invalidate_observations("Observation source disconnected.")
                self.revision += 1
                continue
            break

    async def connect(self, ws):
        async with self.lock:
            old_session = self.engine.snapshot()["observation_session"]
            changed = self.engine.tick()
            if old_session != self.engine.snapshot()["observation_session"]:
                self.producer = None
            if changed:
                self.revision += 1
                await self._broadcast_locked()
            self.clients.add(ws)
            self.engine.record("client_connected", "Simulator/producer connected.")
            self._log_events()
            await self._send(ws, self.snapshot())

    async def disconnect(self, ws):
        async with self.lock:
            self.clients.discard(ws)
            self.engine.record("client_disconnected", "Simulator/producer disconnected.")
            if self.producer is ws:
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

    async def dispatch(self, command, ws):
        async with self.lock:
            old_session = self.engine.snapshot()["observation_session"]
            try:
                if isinstance(command, SetMonitoring):
                    self.engine.set_monitoring(command.enabled)
                elif isinstance(command, SetPower):
                    self.engine.set_power(command.enabled)
                elif isinstance(command, SetMuted):
                    self.engine.set_muted(command.muted)
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
                    if command.source == "simulated" and not self.dev_controls:
                        raise ValueError("Simulated observations are disabled.")
                    self.engine.observe(
                        command.presence, command.source,
                        command.observed_at, command.session_id,
                    )
                    self.producer = ws
            except ValueError as error:
                message = str(error)[:250]
                self.engine.record("command_rejected", message, level="warning")
                self._log_events()
                await self._send(ws, {"type": "error", "code": "invalid_command", "message": message})
                return
            if old_session != self.engine.snapshot()["observation_session"]:
                self.producer = ws if isinstance(command, SubmitObservation) else None
            self.revision += 1
            await self._broadcast_locked()

    async def tick(self):
        async with self.lock:
            old_session = self.engine.snapshot()["observation_session"]
            self.engine.tick()
            snapshot = self.engine.snapshot()
            if old_session != snapshot["observation_session"]:
                self.producer = None
            if snapshot != self._last_snapshot:
                self.revision += 1
                await self._broadcast_locked()

    async def run(self, interval):
        while True:
            await asyncio.sleep(interval)
            await self.tick()

    async def close(self):
        async with self.lock:
            await asyncio.gather(
                *(asyncio.wait_for(ws.close(code=1001), timeout=2)
                  for ws in tuple(self.clients)), return_exceptions=True,
            )
            self.clients.clear()
            self.producer = None


def create_app(
    dev_controls: bool = True, *, config: PolicyConfig | None = None,
    clock=time.monotonic, wall_clock=time.time, initially_muted: bool = True,
    tick_interval: float = 0.25, run_ticker: bool = True,
) -> FastAPI:
    if not math.isfinite(tick_interval) or tick_interval <= 0:
        raise ValueError("tick_interval must be finite and positive")
    engine = ReminderEngine(
        config, clock=clock, wall_clock=wall_clock, initially_muted=initially_muted,
    )
    runtime = Runtime(engine, dev_controls)

    @asynccontextmanager
    async def lifespan(app):
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
        return {"status": "ok", "phase": 2, "protocol_version": 2}

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
