# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The full repository rules (scope, code boundaries, protocol/state contracts, simulator design, validation and team workflow) live in AGENTS.md and apply here:

@AGENTS.md

## Commands

All Python runs in the `pomo` Conda environment (Python 3.13). Run from the repository root.

```sh
sh scripts/setup.sh                 # create/update env, download and checksum models/face_landmarker.task
sh scripts/dev.sh                   # start server (http://127.0.0.1:8000/) with live logs
POMO_PORT=8001 sh scripts/dev.sh    # temporary server on a free port

conda run --name pomo python -m pytest -q                                   # full backend suite
conda run --name pomo python -m pytest -q tests/test_policy.py              # one file
conda run --name pomo python -m pytest -q tests/test_policy.py::test_reminder_triggers_at_sustained_threshold_with_fresh_heartbeats
conda run --name pomo python -m pip check                                   # after dependency changes

# Simulator checks (Node optional, not a runtime dependency)
node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs
node --check simulator/app.js && node --check simulator/camera.js
sh -n scripts/setup.sh scripts/dev.sh
```

There is no linter configuration and no frontend build step.

## Architecture

Single process, single worker: FastAPI serves the static simulator at `/`, `/health`, the `/ws` JSON command/snapshot channel and `POST /camera/frame` for JPEG uploads. All clients share one in-memory robot; restart resets everything.

- `backend/policy.py` `ReminderEngine` is the only live behaviour policy. It is camera-independent, takes an injected monotonic clock, and owns observation freshness, the uncertain-to-absent timer (`POMO_UNCERTAINTY_SECONDS`), the absence-to-reminder timer (`POMO_ABSENCE_SECONDS`), dismissal, cooldown, monitoring/power/mute, previews and the bounded event log. Its `snapshot()` produces the policy part of the broadcast state.
- `backend/app.py` `Runtime` is the transport/adapter layer. It validates commands with strict Pydantic models (`StrictCommand` subclasses, one per `type`), serialises every engine operation and broadcast under one `asyncio.Lock`, runs a 250 ms `tick()` loop for timer expiry, tracks which WebSocket owns the camera session/upload token, and on `/camera/frame` streams and size-checks the body, runs `FrameProcessor` off the event loop, then normalises the raw camera observation (`_normalized_presence`: return-baseline, tracking-loss grace, max age) before calling `engine.observe`. Each accepted change bumps the revision and broadcasts a complete snapshot.
- `backend/camera.py` (`FrameProcessor`) decodes JPEG and calls `backend/perception.py` (MediaPipe Face Landmarker, brightness/blur gating, head pose with hysteresis) and `backend/eyes.py` (iris/blink diagnostics). Output models are in `backend/observations.py`. Eye/head data is diagnostic only and never drives reminders.
- `backend/config.py` builds validated config dataclasses from `.env` plus process env (env wins); invalid values fail at startup. `backend/__main__.py` loads config and starts Uvicorn.
- `backend/behaviour.py` is a legacy standalone policy kept only for historical regression tests (`tests/test_behaviour.py`); do not wire it into the app.
- `simulator/app.js` renders backend snapshots and sends commands (no client-side state machine); `simulator/camera.js` handles `getUserMedia` capture and sequential JPEG uploads for the owning tab. Node tests drive them with fake DOM/WebSocket helpers in `tests/simulator_helpers.cjs`.
- `backend/hardware.py` (`SerialDisplay`) is the optional one-way USB serial adapter (`POMO_SERIAL_PORT`): each broadcast snapshot becomes a JSON line written from its own thread. `firmware/robot-adapter` renders those lines on the CoreS3; `display-test/` and `camera-test/` are standalone tests.

Policy tests (`tests/test_policy.py`) use synthetic observations and a fake clock; app/WebSocket tests use FastAPI's TestClient and `tests/camera_helpers.py` instead of a real camera or model.

When changing a shared contract (command types, snapshot fields, display identifiers, protocol version, currently 9), update `backend/app.py`, `backend/policy.py`, `simulator/`, tests and `docs/protocol.md` together. New settings go in `backend/config.py`, `.env.example` and the README configuration tables.
