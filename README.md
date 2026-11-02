# Pomo

Pomo is a small desktop robot designed to be a friendly study companion. It aims to support consistent study habits through simple facial expressions and gentle reminders.

## Phase

### Phase 1: Set Up the Env

Establish the prototype scope, select and document libraries, organise the repository, configure ports and connect the simulator to the backend.

The foundation includes:

- A `pomo` Conda environment, repeatable setup and configurable startup.
- FastAPI HTTP routes and a WebSocket transport with strict command validation.
- A monochrome simulator with a placeholder robot face, monitoring control and four manual expression previews.
- Shared state broadcasts, connection status, automatic reconnection and a bounded connection journal.
- Integration tests covering routes, commands, broadcasts and state recovery.

Camera foundation (steps 1–4) is implemented: browser capture/preview, bounded
JPEG uploads, one-tab ownership and a long-lived Python processing worker. Face
observations and sustained-absence reminders are now connected, with head-direction
and expression diagnostics. Real Windows webcam testing is still required.

The prototype scope is camera detection, robot display and reminders. Pomodoro timing, session controls and voice recognition are deferred.

### Phase 2: Add Basic Functions

Introduce a configurable webcam source and camera availability reporting. The first detection target is whether the user leaves the frame. Presence observations indicate possible absence; they do not establish concentration or distraction.

Connect observations to a backend state machine with configurable duration thresholds, reminder dismissal and monitoring pause/resume. Keep connection health independent of detection state. Provide distinct display states, simulated observation inputs, diagnostic logs and an optional sound cue with mute control.

Completion requires the camera or simulated observations to drive backend decisions and simulator expressions, including recovery from unavailable or stale input. Raw camera images and video should not be stored by default.

### Phase 3: Test and Validate

Validate camera lifecycle and permissions, detection under different lighting and user positions, state transitions, reminder timing and interruption recovery. Add deterministic tests for thresholds, dismissal and pause/resume using simulated observations.

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

### Camera capture and frame ingestion

The camera pipeline adds frame ingestion alongside the command and state flow above. Successful frame processing and camera lifecycle changes also increment the revision counter and broadcast complete snapshots.

```text
Windows browser: getUserMedia → video preview + sampled JPEG uploads
  → POST /camera/frame → dedicated Python worker: OpenCV decode/BGR-to-RGB
  → camera availability + frame metadata → /ws snapshots → simulator
```

Browser capture works around WSL's lack of direct Windows webcam access. Run the
backend in WSL and open `http://localhost:8000` in a Windows browser. Camera access
needs browser permission and localhost or HTTPS. The preview stays in the browser;
uploaded frames stay in memory and are never recorded or logged.

Only the tab enabling monitoring owns the camera session. Other tabs can view
state or pause monitoring. Pause, tab hiding/closing, connection loss, failed
uploads and server timeouts release/invalidate capture. Re-enable explicitly to
resume. Permission requests completing after cancellation release their tracks.

The processing worker loads Face Landmarker once at startup and closes it on
shutdown. Each usable frame runs Face Landmarker on that worker. Small timestamped
observations drive a separate backend policy; raw frames remain outside shared state.

### Detection and behaviour flow

```text
Browser camera frames (synthetic observations in automated tests)
  → presence detection and timestamped observations
  → backend behaviour policy: duration and dismissal
  → detection status and reminder diagnostics
  → browser detection details / future physical robot adapter
```

Expression previews are manual controls, independent of detection data. Camera
observations, absence, uncertain/stale input and camera failures do not select an
expression or alter the robot face. Detection status and reminder controls belong
to the camera diagnostics. Explicit monitoring commands retain their ready reset.
Repeated snapshots render only text or expression content that differs from the
current display; they do not reload the page.

The observation pipeline and sustained-absence policy are implemented; physical-camera evaluation remains pending. The `firmware/` directory currently contains integration notes; it does not contain a working hardware adapter.

### Presence observations and reminders

While monitoring, the absence counter starts with the first fresh `not_detected`
observation and increases with continuous non-detection, including before a face
baseline exists. The same interval drives `possible_absence` after the configured
1-second tracking-loss grace period. Initial non-detection starts at 0 seconds.

A visible face for at least 0.5 seconds establishes the baseline required for
reminders. Once armed, 10 continuous seconds of non-detection activates a supportive
reminder. Without that baseline, the counter and possible-absence status still run,
but no reminder activates. These durations are configurable. Visible presence
resets the counter; a stable return clears an active reminder. Dismissal clears the
reminder and starts a new absence interval with the next non-detection observation.

Low light, overexposure, low detail/blur, stale results and camera failures are
unknown/unavailable input, not absence. They cancel pending absence and require
a fresh visible-face baseline before further absence reminders. No reminder is
triggered solely by waiting without fresh observations. Pausing releases capture
and clears evidence.

The camera panel shows face presence, quality reasons and absence duration. Head direction and yaw/pitch/roll angles are estimated automatically relative to
the camera. Head direction and blendshape scores do not trigger reminders or establish
attention, emotion or identity. The face box is a development overlay.

Eye movement, Iris vertical offsets, Vertical eye signals and Mouth movement
rows are hidden in the frontend. Detection and snapshot data remain available.
The hidden eye/mouth rows retain this format:

```text
Eye movement: eyeLeft: closed · eyeRight: right · eyeBlinkLeft: 1.00 · eyeBlinkRight: 0.48
Mouth movement: jawOpen: 0.00 · mouthSmileLeft: 0.00 · mouthSmileRight: 0.00
```

Each iris is located relative to its eye corners and lids using the existing
478-landmark mesh. Eye-local pixel axes account for head roll and image aspect
ratio. Median measurements across three eyelid pairs reduce single-landmark jitter. Directions are `center`, `left`, `right`, `up`, `down`, `closed` or `unknown`, from
the subject's perspective. The mirrored preview does not swap eye names or labels.
Detected closure reports `closed` for the affected eye. Tiny eyes, missing
landmarks and strong head yaw/pitch yield unknown direction. A qualifying blink
score can still report closed when head orientation prevents iris tracking. Missing movement scores display a dash rather than zero.
Vertical direction uses signed iris displacement from the eye-corner line,
normalized by eye width. Negative offset means up; positive means down. The default
threshold is 0.08 eye widths. A near-zero offset remains center even if the iris
appears off-center between asymmetric eyelids.

MediaPipe's per-eye up/down coefficients provide corroboration: at least 0.30,
and 0.10 above the opposite signal, allows a half-sized measured excursion in the
same direction. A model coefficient alone cannot turn centered geometry into up.
**Iris vertical offsets** and **Vertical eye signals** retain both measurements
in hidden diagnostic rows for webcam evaluation. These are not gaze probabilities.

These are coarse iris-position estimates, not screen-gaze coordinates, and do not
trigger reminders or distraction decisions. The supported head-angle range is
60° yaw / 45° pitch, subject to usable eye geometry. Raw MediaPipe coefficients remain in the observation. The frontend displays
`eyeBlinkLeft`/`eyeBlinkRight` as continuous normalized scores:
`min(raw blink coefficient / 0.60, 1.00)`. Partial closure retains intermediate
values, including while the direction label is `closed`. The label does not force
the number to 1.00. The full-closure reference is configurable. These scores are
not calibrated physical percentages or model confidence. A raw blink score of at least 0.55 classifies the eye closed. Valid eye-opening
ratios below 0.06 also classify closed; ratios below 0.12 do so when no qualified
vertical eye signal supports an open-eye movement. These are prototype defaults,
not calibrated probabilities or verified accuracy guarantees. Physical accuracy
requires evaluation.

Quality thresholds are heuristics and have not been tuned on a physical webcam.
A plain background can look like a low-detail/blurred image and suppress absence
reminders. Set `POMO_PERCEPTION_MIN_BLUR_VARIANCE=0` to disable that particular
check when evaluating such a scene. Face turned away or occluded can appear absent;
the system measures face visibility rather than proving the user left.

## Runtime and Dependencies

| Component | Current choice | Responsibility |
| --- | --- | --- |
| Runtime | Python 3.13 in Conda | Backend execution and future perception processing |
| HTTP and validation | FastAPI 0.162.0, Pydantic 2.14.1 | Routes, command schema and input validation |
| Server and transport | Uvicorn 0.54.0, websockets 17.3 | ASGI serving and WebSocket connections |
| Interface | Plain HTML, CSS and JavaScript | Robot rendering and development controls |
| Camera processing | OpenCV contrib 5.0.0.93, MediaPipe 1.2.0 | JPEG decoding, face landmarks, head pose and expression diagnostics |
| Configuration | python-dotenv 1.2.4 | Local configuration with environment overrides |
| Tests | pytest 9.1.1, HTTPX 0.28.1 | HTTP/WebSocket integration checks |

[`environment.yml`](environment.yml) is the dependency definition. Conda resolves Python 3.13 and pip from `conda-forge`; its `pip` section pins the existing application, transitive and test packages. Python patch releases and pip are not locked to exact versions.

No frontend build step or Node.js runtime is required. Linux-only EGL/GLES dependencies are selected from the same environment file. See [stack choices](docs/stack.md) for the implementation rationale.

## Setup and Run

Install a recent Conda with CEP-24 support (`--format cep-24`; verified with Conda 26.9.4), then run from the repository root:

```sh
sh scripts/setup.sh
sh scripts/dev.sh
```

Setup creates or updates the named `pomo` environment and downloads/verifies the
versioned Face Landmarker model (see [model manifest](models/README.md)). Startup uses `conda run` to select it automatically and streams server logs to the terminal.

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Stop the backend with Ctrl+C.

For local configuration, copy `.env.example` to `.env` once and edit the values. Preserve an existing `.env` when rerunning setup; defaults work without this file.

### Direct Conda commands

These commands also provide the setup path for Windows:

```sh
conda env create --file environment.yml --format cep-24
conda activate pomo
python scripts/setup_model.py
python -m backend
```

For an existing environment, update it instead of creating it again:

```sh
conda env update --name pomo --file environment.yml --format cep-24 --prune
```

The original setup was verified on macOS ARM64. Camera environment setup and
model initialization are verified on WSL2 Linux x86-64. The environment
uses CEP-24 platform selectors for Linux EGL/GLES; Windows/macOS setup with the
camera dependencies still requires validation.

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

Disabling development controls rejects expression-preview commands. Enabling monitoring starts browser capture in the owning tab. Sustained-absence reminders run only with fresh, usable observations.

## HTTP and WebSocket Interface

| Endpoint | Transport | Contract |
| --- | --- | --- |
| `/` | HTTP GET | Simulator HTML; static assets are served from the same origin |
| `/health` | HTTP GET | Service and camera-processor readiness |
| `/ws` | WebSocket | JSON text commands, state snapshots and validation errors |
| `/camera/frame` | HTTP POST | Bounded, session-scoped JPEG ingestion |

### Camera configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `POMO_CAMERA_WIDTH` / `POMO_CAMERA_HEIGHT` | 640 / 480 | Capture target and maximum decoded dimensions |
| `POMO_CAMERA_FPS` | 10 | Upper sampling target; uploads are sequential |
| `POMO_CAMERA_JPEG_QUALITY` | 0.75 | Browser JPEG encoding quality |
| `POMO_CAMERA_MAX_BYTES` | 524288 | Maximum streamed request body |
| `POMO_CAMERA_TIMEOUT_SECONDS` | 3 | Body/processing deadline and active-source idle timeout |
| `POMO_CAMERA_STARTUP_SECONDS` | 30 | Initial permission/first-frame allowance |
| `POMO_CAMERA_MODEL_PATH` | repository `models/face_landmarker.task` | Optional model override |

Values are validated at startup. Invalid or oversized images are rejected before
state changes; JPEG dimensions are checked before OpenCV decoding. Only one upload
is processed at a time; old frames are not queued or replayed.

### Detection configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `POMO_TRACKING_LOSS_GRACE_SECONDS` | 1 | Tolerate brief non-detection; included in absence duration |
| `POMO_ABSENCE_SECONDS` | 10 | Continuous non-detection before reminding |
| `POMO_RETURN_SECONDS` | 0.5 | Stable face presence for arming and return |
| `POMO_OBSERVATION_MAX_AGE_SECONDS` | 1 | Maximum age/gap of usable evidence |
| `POMO_PERCEPTION_DETECTION_CONFIDENCE` | 0.5 | MediaPipe detection threshold |
| `POMO_PERCEPTION_PRESENCE_CONFIDENCE` | 0.5 | MediaPipe face-presence threshold |
| `POMO_PERCEPTION_TRACKING_CONFIDENCE` | 0.5 | MediaPipe tracking threshold |
| `POMO_PERCEPTION_MIN_BRIGHTNESS` / `POMO_PERCEPTION_MAX_BRIGHTNESS` | 35 / 230 | Usable grayscale mean range |
| `POMO_PERCEPTION_MIN_BLUR_VARIANCE` | 15 | Minimum Laplacian variance; 0 disables |
| `POMO_PERCEPTION_YAW_DEGREES` / `POMO_PERCEPTION_PITCH_DEGREES` | 30 / 25 | Direction thresholds relative to the camera |
| `POMO_PERCEPTION_HYSTERESIS_DEGREES` | 5 | Direction exit margin to reduce flicker |

| Iris setting | Default | Purpose |
| --- | --- | --- |
| `POMO_PERCEPTION_EYE_HORIZONTAL_MARGIN` | 0.15 | Horizontal distance from eye midpoint before left/right |
| `POMO_PERCEPTION_EYE_VERTICAL_OFFSET_THRESHOLD` | 0.08 | Signed iris displacement from eye-corner line, normalized by eye width |
| `POMO_PERCEPTION_EYE_VERTICAL_SIGNAL_THRESHOLD` | 0.30 | Minimum model up/down coefficient to supplement iris geometry |
| `POMO_PERCEPTION_EYE_VERTICAL_SIGNAL_MARGIN` | 0.10 | Minimum difference between opposing model up/down coefficients |
| `POMO_PERCEPTION_EYE_BLINK_THRESHOLD` | 0.55 | Raw blink threshold for closed-eye classification |
| `POMO_PERCEPTION_EYE_BLINK_FULL_CLOSURE` | 0.60 | Raw blink coefficient mapped continuously to displayed 1.00 |
| `POMO_PERCEPTION_EYE_MAX_YAW_DEGREES` | 60 | Maximum absolute head yaw for iris interpretation |
| `POMO_PERCEPTION_EYE_MAX_PITCH_DEGREES` | 45 | Maximum absolute head pitch for iris interpretation |

Choose freshness limits above the expected upload interval plus processing latency.
Processing results older than the observation limit are unknown even when the
camera transport remains available. All timing uses the backend's monotonic clock.

### Protocol v6

`/health` reports phase 2 and `camera_processor_ready`. `/ws` broadcasts complete
state snapshots with camera status (`paused`, `starting`, `available`,
`unavailable`), frame count/dimensions and an owner-only upload session token.
`POST /camera/frame` accepts bounded raw JPEG requests with session and sequence
headers. The 4 KB JSON WebSocket channel remains separate from image transport.

Commands are `set_monitoring`, `camera_failed` (owner only), and `preview_display`
(development controls only), plus `dismiss_reminder`. Snapshots
add observation, head-direction and behaviour diagnostics. Display values remain `ready`, `possible_absence`,
`reminding`, `unavailable`; manual previews do not represent detection results.
Connection health, camera availability and robot display remain independent.

Protocol v6 defines the camera, observation and behaviour contracts. Update
frontend and backend together. See [protocol v6](docs/protocol.md) for exact contracts,
validation, ownership, timeouts and reconnection behaviour.

## Verification

Run the integration suite and check installed package consistency:

```sh
conda run --name pomo python -m pytest -q
conda run --name pomo python -m pip check
```

Tests cover HTTP/WebSocket contracts, shared state, owner-only camera sessions,
JPEG validation, backpressure, expiration and cleanup. Core camera tests use a fake
model lifecycle and synthetic images; they do not require a physical webcam.
The existing Starlette/HTTPX deprecation warning remains. See [verification
records](docs/verification.md) for dated checks and limitations.

If Node is available, optional client lifecycle checks are:

```sh
node --check simulator/app.js
node --check simulator/camera.js
node --test tests/test_camera_client.cjs tests/test_simulator.cjs
```

Manual Windows-browser check:

1. Open `http://localhost:8000` and confirm Connected.
2. Enable monitoring and grant camera permission; verify preview and frame count.
3. Open another tab; verify it observes the camera without acquiring it.
4. Pause; confirm the browser camera indicator turns off.
5. Test permission denial, tab hiding, owner tab close and backend restart.
6. Re-enable explicitly after interruptions; verify a new session and fresh frames.
7. Preview robot expressions; verify they remain independent of camera status.
8. Stay visible until Face visible; check automatic head direction and angles by
   turning left/right/up/down. With your head approximately forward, check each eye
   direction and blink score, then verify mouth scores remain in their own row.
9. Leave the frame for over 10 seconds in a usable scene; verify a reminder, dismissal
   and a fresh absence countdown. Return for at least 0.5 seconds and check recovery.
10. Test darkness/occlusion and interrupted uploads; confirm uncertain/stale input
    clears the countdown and requires a fresh face baseline.

## Deployment Constraints

For a cloud development workspace, install Conda, run setup and start the server with:

```sh
POMO_HOST=0.0.0.0 sh scripts/dev.sh
```

Forward the configured port privately through the workspace provider. The proxy must support WebSocket upgrades and serve the application at the URL root; a path-prefix proxy is not configured. Forwarded HTTPS/WSS access requires validation in the target workspace.

The development server has no authentication, and every connected client can control the shared robot. Keep access restricted through the workspace's access controls.

Capture happens in the browser, so the backend does not open the laptop webcam.
On a remote deployment frames travel to that backend; the intended prototype runs
on the same laptop through localhost. No camera recording is implemented.

## Repository Structure

```text
backend/
  app.py              FastAPI factory, command validation and shared state
  __main__.py         Configuration loading and Uvicorn entry point
  camera.py           Long-lived processing worker and JPEG validation
  config.py           Validated camera, perception and behaviour settings
  observations.py     Timestamped observation schema
  perception.py       Face Landmarker and head-direction diagnostics
  eyes.py             Eye-local iris direction observations
  behaviour.py        Camera-independent sustained-absence policy
simulator/
  index.html          Robot display and simulator controls
  app.js              WebSocket client, rendering and reconnection
  camera.js           Browser capture, preview and sequential JPEG uploads
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
  setup_model.py      Download and checksum-verify the versioned model
tests/
  test_backend.py     HTTP/WebSocket integration tests
environment.yml       Conda runtime and pinned Python packages
.env.example          Configuration defaults
```

## TODO

### Phase 2: Add Basic Functions

- [x] Implement browser webcam capture, preview, start/stop lifecycle, bounded uploads and availability/error reporting (physical Windows-camera validation pending).
- [x] Select and document OpenCV 5, MediaPipe Face Landmarker and the versioned model.
- [x] Implement presence/absence observations for the initial prototype.
- [x] Add timestamps and observation freshness checks; handle poor lighting, uncertain results and temporary tracking loss.
- [x] Define backend state transitions and configurable sustained-absence thresholds.
- [x] Connect observations to backend decisions and broadcast detection diagnostics independently of manual expressions.
- [x] Implement reminder dismissal, pause/resume and recovery when the user returns.
- [ ] Add an optional sound cue with mute control.
- [x] Add diagnostics for observation duration, detection state and errors.
- [ ] Add interactive simulated observation inputs (synthetic observations already cover automated tests).
- [x] Stop reminders on unavailable input and discard stale observations after interruptions; keep camera recording disabled by default.

### Phase 3: Test and Validate

- [ ] Test missing/busy cameras, denied permission, resource release and recovery after interruption.
- [ ] Evaluate leaving the frame, looking away and reading notes across lighting conditions, distances and head positions; record false reminders and missed events.
- [x] Add camera-independent tests for thresholds, dismissal, pause/resume and unavailable input.
- [ ] Validate backend, simulator and camera restart/disconnection sequences without replaying old reminders.
- [ ] Demonstrate enable monitoring → observations → sustained absence → reminder → dismissal → recovery, using both camera and simulated input.
- [ ] Have teammates test installation and usability; record whether controls and reminder frequency are understandable and acceptable.
- [ ] Validate Windows/Linux setup and private HTTPS/WSS forwarding where those environments are used.
- [ ] Record a short demo, configuration instructions, detection limitations and validation results; review and merge working changes into `main`.

### Physical Integration and Deferred Features

- [ ] Define and validate the physical display, button interface and hardware transport against the documented backend contract.
- [ ] Document the hardware adapter and end-to-end integration steps after the software prototype is validated.
- [ ] Revisit Pomodoro/session controls and voice recognition after the prototype scope is complete.
