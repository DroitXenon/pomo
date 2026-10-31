# Pomo

Pomo is a small desktop robot designed to be a friendly study companion. It aims to support consistent study habits through simple facial expressions and gentle reminders.

## Phase

### Phase 1: Set Up the Env

Establish the prototype scope, select and document libraries, organise the repository, configure ports and connect the simulator to the backend.

The current foundation includes:

- A `pomo` Conda environment, repeatable setup and configurable startup.
- FastAPI HTTP routes and a WebSocket transport with strict command validation.
- A monochrome simulator with a placeholder robot face, monitoring control and four manual expression previews.
- Shared state broadcasts, connection status, automatic reconnection and a bounded connection journal.
- Integration tests covering routes, commands, broadcasts and state recovery.

The prototype scope is camera detection, robot display and reminders. Pomodoro timing, session controls and voice recognition are deferred.

### Phase 2: Add Basic Functions

Introduce a configurable webcam source and camera availability reporting. The first detection target is whether the user leaves the frame. Presence observations indicate possible absence; they do not establish concentration or distraction.

Connect observations to a backend state machine with configurable duration thresholds, reminder dismissal, cooldowns and monitoring pause/resume. Keep connection health independent of detection state. Provide distinct display states, simulated observation inputs, diagnostic logs and an optional sound cue with mute control.

Completion requires the camera or simulated observations to drive backend decisions and simulator expressions, including recovery from unavailable or stale input. Raw camera images and video should not be stored by default.

### Phase 3: Test and Validate

Validate camera lifecycle and permissions, detection under different lighting and user positions, state transitions, reminder timing and interruption recovery. Add deterministic tests for thresholds, cooldowns, dismissal and pause/resume using simulated observations.

Run a reproducible end-to-end demonstration, conduct a small teammate usability check, verify installation on another machine and document false reminders, missed events and known limitations. Record the next steps for physical robot integration and review working changes before merging into `main`.

## Architecture

### Current data flow

```text
Browser simulator
  │ JSON commands over /ws
  ▼
FastAPI command validation
  ▼
Shared in-memory state + revision counter
  │ complete state snapshots
  ▼
All connected simulator clients
```

One Uvicorn process serves the static interface, health endpoint and WebSocket route on the same host and port. The simulator derives its WebSocket URL from the page origin and uses `wss` when served over HTTPS.

State changes and broadcasts are serialised with an `asyncio.Lock`. Each accepted command increments the revision counter. Broadcast sends have a two-second timeout per client; failed clients are removed from the active set.

All clients control the same robot state. State is process-local and resets on restart, so run a single backend worker. Persistence, separate user sessions and cross-process state synchronisation are not implemented.

### Planned detection flow

```text
Configurable camera source or simulated observations
  → presence detection and timestamped observations
  → backend behaviour policy: duration, cooldown, dismissal
  → display state
  → browser simulator / future physical robot adapter
```

The observation pipeline and behaviour policy belong to Phase 2. The `firmware/` directory currently contains integration notes; it does not contain a working hardware adapter.

## Runtime and Dependencies

| Component | Current choice | Responsibility |
| --- | --- | --- |
| Runtime | Python 3.13 in Conda | Backend execution and future perception processing |
| HTTP and validation | FastAPI 0.162.0, Pydantic 2.14.1 | Routes, command schema and input validation |
| Server and transport | Uvicorn 0.54.0, websockets 17.3 | ASGI serving and WebSocket connections |
| Interface | Plain HTML, CSS and JavaScript | Robot rendering and development controls |
| Configuration | python-dotenv 1.2.4 | Local configuration with environment overrides |
| Tests | pytest 9.1.1, HTTPX 0.28.1 | HTTP/WebSocket integration checks |

[`environment.yml`](environment.yml) is the dependency definition. Conda resolves Python 3.13 and pip from `conda-forge`; its `pip` section pins the existing application, transitive and test packages. Python patch releases and pip are not locked to exact versions.

No frontend build step or Node.js runtime is required. Camera-processing libraries have not been added. See [stack choices](docs/stack.md) for the implementation rationale.

## Setup and Run

Install Conda through Miniconda or Miniforge, then run from the repository root:

```sh
sh scripts/setup.sh
sh scripts/dev.sh
```

Setup creates or updates the named `pomo` environment. Startup uses `conda run` to select it automatically and streams server logs to the terminal.

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Stop the backend with Ctrl+C.

For local configuration, copy `.env.example` to `.env` once and edit the values. Preserve an existing `.env` when rerunning setup; defaults work without this file.

### Direct Conda commands

These commands also provide the setup path for Windows:

```sh
conda env create --file environment.yml
conda activate pomo
python -m backend
```

For an existing environment, update it instead of creating it again:

```sh
conda env update --name pomo --file environment.yml --prune
```

The Conda setup has been verified on macOS ARM64. Windows and Linux installations still require validation.

## Configuration

The backend reads `.env` from the repository root. Existing process environment variables take precedence.

| Variable | Default | Behaviour |
| --- | --- | --- |
| `POMO_HOST` | `127.0.0.1` | Uvicorn bind address |
| `POMO_PORT` | `8000` | Shared HTTP/WebSocket port; accepts 1–65535 |
| `POMO_DEV_CONTROLS` | `true` | Allows manual expression commands; accepts `true` or `false`, case-insensitively |

Example shell override:

```sh
POMO_PORT=8001 POMO_DEV_CONTROLS=false sh scripts/dev.sh
```

Disabling development controls rejects expression-preview commands. Monitoring remains a stored simulation flag; enabling it does not start a camera or trigger automatic reminders.

## HTTP and WebSocket Interface

| Endpoint | Transport | Contract |
| --- | --- | --- |
| `/` | HTTP GET | Simulator HTML; static assets are served from the same origin |
| `/health` | HTTP GET | `{"status":"ok","phase":1}` |
| `/ws` | WebSocket | JSON text commands, state snapshots and validation errors |

### State snapshot

A client receives the current snapshot on connection. Every accepted command broadcasts a new snapshot to all connected clients.

```json
{
  "type": "state",
  "protocol_version": 1,
  "monitoring_enabled": false,
  "display": "ready",
  "camera_status": "not_implemented",
  "revision": 0,
  "dev_controls": true
}
```

Display values are `ready`, `possible_absence`, `reminding` and `unavailable`. These are currently manual display previews. A `reminding` display does not imply that reminder logic has run, and an `unavailable` display is separate from WebSocket connection status.

### Commands

```json
{"type":"set_monitoring","enabled":true}
{"type":"set_monitoring","enabled":false}
{"type":"preview_display","display":"possible_absence"}
```

`set_monitoring` requires a strict boolean and resets the display to `ready` for both enable and pause commands. Manual previews are allowed while monitoring is paused when development controls are enabled.

Unknown commands, extra fields, invalid JSON and binary messages produce an error without changing state:

```json
{"type":"error","code":"invalid_command","message":"Explanation"}
```

The startup configuration limits WebSocket message size to 4,096 bytes. The application also validates incoming command shape and text length. Oversized messages may close the connection.

### Reconnection and reset semantics

The simulator retries connections after 1, 2, 4 and 8 seconds, then at most every 10 seconds. Receiving a valid snapshot resets the retry delay. Controls stay disabled until a snapshot arrives, and disconnection marks the displayed state as potentially stale.

Reconnecting clients receive the current state. Backend restart resets monitoring to paused, display to `ready` and revision to zero. Offline commands are not queued or replayed.

See [protocol v1](docs/protocol.md) for the transport contract.

## Verification

Run the integration suite and check installed package consistency:

```sh
conda run --name pomo python -m pytest -q
conda run --name pomo python -m pip check
```

The current four tests cover static/health routes, multi-client broadcasts, reconnect/restart state, malformed commands and disabled previews. They do not validate camera detection, reminder timing or physical hardware.

Recorded checks include fresh and repeated Conda setup, four passing integration tests, dependency consistency and live HTTP/WebSocket communication on macOS ARM64. The current test adapter emits a Starlette/HTTPX deprecation warning. See [verification records](docs/verification.md) for dates and limitations.

Manual simulator check:

1. Open the interface and confirm `Connected`.
2. Enable monitoring and confirm the simulation-only status.
3. Select each expression and verify its label and face.
4. Open another tab and verify both clients receive the same state.
5. Stop and restart the backend; verify controls disable, reconnect and restore the restart defaults.

## Deployment Constraints

For a cloud development workspace, install Conda, run setup and start the server with:

```sh
POMO_HOST=0.0.0.0 sh scripts/dev.sh
```

Forward the configured port privately through the workspace provider. The proxy must support WebSocket upgrades and serve the application at the URL root; a path-prefix proxy is not configured. Forwarded HTTPS/WSS access requires validation in the target workspace.

The development server has no authentication, and every connected client can control the shared robot. Keep access restricted through the workspace's access controls.

A remote backend cannot directly open a laptop webcam. Phase 2 must either run capture and processing locally or explicitly implement browser capture and transport.

## Repository Structure

```text
backend/
  app.py              FastAPI factory, command validation and shared state
  __main__.py         Configuration loading and Uvicorn entry point
simulator/
  index.html          Robot display and simulator controls
  app.js              WebSocket client, rendering and reconnection
  style.css           Responsive monochrome interface
firmware/
  README.md           Future hardware integration notes
docs/
  protocol.md         Current WebSocket message contract
  stack.md            Technology decisions
  verification.md     Recorded checks and limitations
scripts/
  setup.sh            Create/update the pomo Conda environment
  dev.sh              Start the backend inside that environment
tests/
  test_backend.py     HTTP/WebSocket integration tests
environment.yml       Conda runtime and pinned Python packages
.env.example          Configuration defaults
```

## Team Discussion

Use [docs/agent-discussion.md](docs/agent-discussion.md) to exchange ideas, questions, decisions and handoffs between teammates and their agents. It includes a reusable entry template and Git sharing instructions. [AGENTS.md](AGENTS.md) directs agents to read relevant entries before working and append replies when there is something to share.

Discussion updates are shared through commits and pull requests. Teammates must bring those changes into their checkout to see them.

## TODO

### Phase 2: Add Basic Functions

- [ ] Add configurable webcam capture with start/stop lifecycle, development preview and availability/error reporting.
- [ ] Select and document the detection libraries; implement presence/absence observations for the initial prototype.
- [ ] Add timestamps and observation freshness checks; handle poor lighting, uncertain results and temporary tracking loss.
- [ ] Define backend state transitions and configurable sustained-absence thresholds.
- [ ] Connect observations to backend decisions and broadcast the resulting display state.
- [ ] Implement reminder dismissal, cooldown, pause/resume and recovery when the user returns.
- [ ] Add an optional sound cue with mute control.
- [ ] Add simulated observation events and diagnostics for observation duration, cooldown, reminders and errors.
- [ ] Stop reminders on unavailable input and discard stale observations after interruptions; keep camera recording disabled by default.

### Phase 3: Test and Validate

- [ ] Test missing/busy cameras, denied permission, resource release and recovery after interruption.
- [ ] Evaluate leaving the frame, looking away and reading notes across lighting conditions, distances and head positions; record false reminders and missed events.
- [ ] Add camera-independent tests for thresholds, cooldown, dismissal, pause/resume and unavailable input.
- [ ] Validate backend, simulator and camera restart/disconnection sequences without replaying old reminders.
- [ ] Demonstrate enable monitoring → observations → sustained absence → reminder → dismissal → recovery, using both camera and simulated input.
- [ ] Have teammates test installation and usability; record whether controls and reminder frequency are understandable and acceptable.
- [ ] Validate Windows/Linux setup and private HTTPS/WSS forwarding where those environments are used.
- [ ] Record a short demo, configuration instructions, detection limitations and validation results; review and merge working changes into `main`.

### Physical Integration and Deferred Features

- [ ] Define and validate the physical display, button interface and hardware transport against the documented backend contract.
- [ ] Document the hardware adapter and end-to-end integration steps after the software prototype is validated.
- [ ] Revisit Pomodoro/session controls and voice recognition after the prototype scope is complete.
