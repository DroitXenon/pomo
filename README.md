# Pomo

Pomo is a small desktop robot designed to be a friendly study companion. It aims to support consistent study habits through simple facial expressions and gentle reminders.

## Phase

### Phase 1: Set Up the Env

Establish the prototype scope, select and document libraries, organise the repository, configure ports and connect the simulator to the backend.

The current foundation includes:

- A `pomo` Conda environment, repeatable setup and configurable startup.
- FastAPI HTTP routes and a WebSocket transport with strict command validation.
- A monochrome simulator with a placeholder robot face, monitoring control and five manual expression previews.
- Shared state broadcasts, connection status, automatic reconnection and a bounded connection journal.
- Integration tests covering routes, commands, broadcasts and state recovery.

The prototype scope is camera detection, robot display and reminders. Pomodoro timing, session controls and voice recognition are deferred.

### Phase 2: Add Basic Functions

Implemented on `agent/feature/states`: the five-state backend policy, sustained-absence reminders, global monitoring and soft power controls, dismissal, configurable cooldown, optional sound/mute and bounded debug logging. Simulated observations drive the complete pipeline without a camera. Camera capture and perception remain a separate integration task.

The first detection target is whether the user leaves the frame. Presence observations do not establish concentration or distraction. Unknown tracking, missing input and disconnected sources lead to detection-unavailable behaviour.

Implementation follows the [Reminders](https://app.notion.com/p/40a66acb0c0380f5bacfc18ac6fa598a), [States Implementation](https://app.notion.com/p/40a66acb0c0380deaf4fd7dbefb28b04) and [Debug Logs](https://app.notion.com/p/40a66acb0c0380078ca4ef9dcfaed7e9) specifications. Defaults are configurable; no camera images or video are captured or stored by this implementation.

### Phase 3: Test and Validate

Automated checks cover policy transitions, timing boundaries, dismissal, cooldown, pause/resume, observation freshness, source disconnect/reconnect, strict message validation, configuration and simulator behaviour. Policy timing uses injected clocks rather than test sleeps or camera hardware.

Remaining validation includes real camera lifecycle/permissions, lighting and position evaluation, usability with teammates, installation on other platforms and physical integration. Record false reminders, missed events and known limitations before making detection-quality claims.

## Architecture

### Current data flow

```text
Browser controls / simulated observations / future camera producer
  │ strict JSON commands and timestamped metadata over /ws
  ▼
FastAPI transport → camera-independent ReminderEngine
  │ monotonic timing, lifecycle tokens, reminder policy
  │ 250 ms timer for expiry, thresholds and live diagnostics
  ▼
Complete shared state snapshots → all connected simulators
```

`backend/policy.py` owns behaviour independently of camera devices and rendering. `backend/app.py` serialises policy operations and broadcasts with an `asyncio.Lock`. `backend/config.py` validates environment settings; `backend/__main__.py` starts Uvicorn.

One process serves static assets, health and WebSocket traffic. Accepted commands and published timer changes advance a revision counter. Failed sends time out after two seconds per client. If the last accepted observation producer disconnects, its input and active reminder are invalidated; a viewer disconnect does not clear another source.

All clients control one in-memory robot. Restart resets state, history and counters and creates a new instance ID. Use one backend worker. Persistence, separate user sessions and cross-process state synchronisation are not implemented.

### Camera integration boundary

A future camera processor sends presence metadata, its Unix observation timestamp and the current observation-session token through the documented `submit_observation` command. The backend rejects stale, out-of-order and old-session input. It decides when to transition or remind, and the simulator renders the resulting state.

Physical capture/perception and the `firmware/` adapter remain unimplemented. The browser simulator provides synthetic observation heartbeats to exercise the policy now. See [protocol v2](docs/protocol.md) for the producer contract.

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

The backend reads `.env` from the repository root. Process environment variables take precedence. Changes to startup settings require a backend restart; monitoring, power and mute controls are shared live.

| Variable | Default | Behaviour |
| --- | --- | --- |
| `POMO_HOST` | `127.0.0.1` | Uvicorn bind address |
| `POMO_PORT` | `8000` | Shared HTTP/WebSocket port; accepts 1–65535 |
| `POMO_DEV_CONTROLS` | `true` | Allows simulated observations and expression previews |
| `POMO_ABSENCE_SECONDS` | `5` | Continuous fresh absence needed before a reminder; finite and greater than zero |
| `POMO_REMINDER_COOLDOWN_SECONDS` | `30` | Quiet period after triggering or dismissing; finite and non-negative |
| `POMO_OBSERVATION_TIMEOUT_SECONDS` | `3` | Maximum observation age; finite and greater than zero |
| `POMO_SOUND_ENABLED` | `false` | Initial shared sound preference; each browser still needs a user gesture for audio |

Boolean settings accept `true` or `false`, case-insensitively. Invalid settings fail at startup. A zero cooldown intentionally permits immediate retriggering after dismissal when continuing absence still qualifies.

Example shell override for a short development demonstration:

```sh
POMO_PORT=8001 POMO_ABSENCE_SECONDS=2 POMO_REMINDER_COOLDOWN_SECONDS=5 sh scripts/dev.sh
```

The browser's simulated input repeats at an interval below the configured freshness timeout. Real producers must also send continuing fresh observations. One absence packet cannot sustain a reminder indefinitely.

## States and Reminders

| Actual state | Meaning |
| --- | --- |
| `ready` | Powered on with monitoring paused, or fresh presence restored |
| `shutdown` | Soft power off; monitoring, input, preview, active reminder and cooldown cleared |
| `distraction` | Fresh absence under evaluation or ongoing absence during cooldown |
| `reminding` | A real visual reminder is active |
| `unavailable` | Monitoring is enabled but input is missing, expired, unavailable or uncertain |

Power off is a reversible policy state, not a server shutdown. Wake returns to ready with monitoring paused. Monitoring changes discard old observations and require fresh input. Pausing, returning presence, unknown input and unavailable input clear active reminders and pending absence duration; remaining cooldown is retained. Power cycling clears cooldown.

An absence must remain continuously supported by fresh observations for the configured threshold. A triggered reminder stays active until dismissed, presence returns, input becomes uncertain/unavailable, monitoring pauses or power turns off. An active reminder never repeatedly retriggers when its original cooldown expires.

Dismissal starts a full new quiet period. If absence continues, a new reminder can appear only after that cooldown. Every real reminder has an increasing ID scoped to the backend instance, so stale dismissals and repeated snapshots cannot replay a previous cue.

Sound is optional and initially muted. Unmute/enable audio through a user gesture in each tab. A newly received real reminder can play one short cue; initial/reconnect snapshots, preview expressions and repeated snapshots do not replay it. Browser audio restrictions or unsupported audio do not prevent visual reminders.

## HTTP and WebSocket Interface

| Endpoint | Transport | Contract |
| --- | --- | --- |
| `/` | HTTP GET | Simulator and same-origin static assets |
| `/health` | HTTP GET | `{"status":"ok","phase":2,"protocol_version":2}` |
| `/ws` | WebSocket | Strict JSON commands, complete state snapshots and validation errors |

Protocol version 2 replaces v1's `possible_absence` display identifier with `distraction`. Update backend and simulator together.

Commands cover `set_monitoring`, `set_power`, `set_muted`, `dismiss_reminder`, `submit_observation`, `preview_display` and `clear_preview`. For example:

```json
{"type":"set_monitoring","enabled":true}
{"type":"set_muted","muted":false}
{"type":"dismiss_reminder","reminder_id":1}
```

Each snapshot includes actual `behavior_state`, rendered `display`, power/monitoring/mute state, camera/input metadata, observation-session token, absence duration, cooldown, active reminder, settings and up to 100 backend events. Manual previews require power on and monitoring paused; they change rendering only and never create reminders or sounds.

Observation producers copy the latest session token, send strictly increasing finite Unix timestamps and discard buffered packets on lifecycle changes or disconnect. A source timeout invalidates the session. Unknown/binary/malformed messages and extra or incorrectly typed fields are rejected without applying a policy operation. Incoming message size is limited to 4,096 bytes. Full schemas, examples and recovery rules are in [protocol v2](docs/protocol.md).

The simulator retries connections with capped exponential backoff and disables controls until a valid snapshot arrives. Disconnect stops simulated heartbeats and local audio. Reconnection restores current shared state but requires a fresh simulated-input selection; offline commands and old sounds are not replayed.

## Verification

Run the Python checks and package-consistency validation:

```sh
conda run --name pomo python -m pytest -q
conda run --name pomo python -m pip check
```

Optional UI behaviour checks use Node.js's built-in test runner, with no npm dependencies:

```sh
node --test tests/test_simulator.js
node --check simulator/app.js
```

Node is needed only for these JavaScript checks, not to run Pomo. The Python suites cover pure policy, WebSocket integration and configuration. The JavaScript suite checks simulated heartbeat lifecycle, control gating, sound deduplication/audio fallback, error handling and safe log rendering.

The existing Starlette/HTTPX test-adapter deprecation warning remains. See [verification records](docs/verification.md) for dated results and material limits.

Manual simulator demonstration:

1. Start the backend, open the simulator and confirm Connected.
2. Enable monitoring. Without input, the actual state is Detection unavailable.
3. Select Absent under simulated input. Continuing fresh observations first show Distraction, then a visual reminder after the threshold.
4. Dismiss it and watch the cooldown. Select Present to clear pending absence; select Uncertain or Unavailable to stop detection-driven reminders.
5. Enable sound through the button to allow local audio for new reminders; mute stops an in-flight cue.
6. Pause monitoring, then preview all five expressions. Previews do not trigger real reminders or sound.
7. Power off and wake Pomo. Verify wake leaves monitoring paused.
8. Open a second tab and check shared state. Reconnect a viewer without replaying sound; disconnect the observation-producing tab and check unavailable state.

The debug panel shows current observation/source/age, absence duration, cooldown, actual state and backend events. Clearing the browser log clears that tab's view only; it does not erase shared backend history.

## Deployment Constraints

For a cloud development workspace, install Conda, run setup and start the server with:

```sh
POMO_HOST=0.0.0.0 sh scripts/dev.sh
```

Forward the configured port privately through the workspace provider. The proxy must support WebSocket upgrades and serve the application at the URL root; a path-prefix proxy is not configured. Forwarded HTTPS/WSS access requires validation in the target workspace.

The development server has no authentication, and every connected client can control the shared robot. Keep access restricted through the workspace's access controls.

A remote backend cannot directly open a laptop webcam. A real camera adapter must either run capture and processing locally or explicitly implement browser capture and transport.

## Repository Structure

```text
backend/
  app.py              FastAPI transport, strict commands, timer and broadcasts
  policy.py           Camera-independent state/reminder policy and bounded events
  config.py           Validated environment configuration
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
  test_policy.py      Fake-clock state/reminder policy tests
  test_config.py      Environment validation tests
  test_simulator.js   Optional dependency-free Node UI behaviour checks
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
- [x] Add timestamp/session freshness validation and explicitly handle unknown, unavailable and expired observation metadata.
- [ ] Evaluate the real detector under poor lighting and temporary tracking loss.
- [x] Define the five backend states and configurable sustained-absence thresholds.
- [x] Connect simulated/producer observation metadata to backend decisions and broadcast the resulting state.
- [ ] Integrate the physical webcam/perception producer with that contract.
- [x] Implement reminder dismissal, cooldown, global pause/resume, soft power and presence recovery.
- [x] Add an optional sound cue with mute/audio-unlock controls and reconnect deduplication.
- [x] Add simulated observation heartbeats, live duration/cooldown diagnostics and bounded reminder/error logs.
- [x] Clear reminders on unavailable input and discard stale/old-session observations after interruptions; no camera recording is added.

### Phase 3: Test and Validate

- [ ] Test missing/busy cameras, denied permission, resource release and recovery after interruption.
- [ ] Evaluate leaving the frame, looking away and reading notes across lighting conditions, distances and head positions; record false reminders and missed events.
- [x] Add camera-independent tests for thresholds, cooldown, dismissal, pause/resume, power, freshness and unavailable input.
- [ ] Validate backend, simulator and camera restart/disconnection sequences without replaying old reminders.
- [ ] Complete the manual browser/audible check and a real-camera demonstration of monitoring → observations → absence → reminder → dismissal → recovery.
- [x] Add automated coverage of the simulated observation and reminder pipeline.
- [ ] Have teammates test installation and usability; record whether controls and reminder frequency are understandable and acceptable.
- [ ] Validate Windows/Linux setup and private HTTPS/WSS forwarding where those environments are used.
- [ ] Record a short demo, configuration instructions, detection limitations and validation results; review and merge working changes into `main`.

### Physical Integration and Deferred Features

- [ ] Define and validate the physical display, button interface and hardware transport against the documented backend contract.
- [ ] Document the hardware adapter and end-to-end integration steps after the software prototype is validated.
- [ ] Revisit Pomodoro/session controls and voice recognition after the prototype scope is complete.
