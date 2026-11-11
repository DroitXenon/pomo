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

Implemented: browser webcam capture, bounded JPEG transport, Face Landmarker presence/head diagnostics, and one five-state reminder policy. Camera and simulated input both drive the robot display, global monitoring, soft power, dismissal, configurable cooldown, optional sound/mute and bounded debug logs. Physical-camera evaluation remains pending.

The first detection target is whether the user leaves the frame. Presence observations do not establish concentration or distraction. Fresh uncertain observations show happy and become absent after one second by default; missing or disconnected input remains unavailable.

Implementation follows the [Reminders](https://app.notion.com/p/40a66acb0c0380f5bacfc18ac6fa598a), [States Implementation](https://app.notion.com/p/40a66acb0c0380deaf4fd7dbefb28b04), [Debug Logs](https://app.notion.com/p/40a66acb0c0380078ca4ef9dcfaed7e9) and [Camera Detection](https://app.notion.com/p/40a66acb0c038013b8b5eb483fa9e18e) specifications. Defaults are configurable; camera frames are processed in memory without recording or persistence.

### Phase 3: Test and Validate

Automated checks cover policy transitions, timing boundaries, dismissal, cooldown, pause/resume, observation freshness, source disconnect/reconnect, strict message validation, configuration and simulator behaviour. Policy timing uses injected clocks rather than test sleeps or camera hardware.

Remaining validation includes real camera lifecycle/permissions, lighting and position evaluation, usability with teammates, installation on other platforms and physical integration. Record false reminders, missed events and known limitations before making detection-quality claims.

## Architecture

### Current data flow

```text
Browser camera → bounded JPEG POST /camera/frame → dedicated model worker
  │ fresh presence metadata + baseline/tracking-loss gate
  ├───────────────────────────────────────────────────────┐
Browser controls / simulated observations over /ws        │
  ▼                                                      ▼
FastAPI transport → camera-independent ReminderEngine
  │ monotonic timing, lifecycle tokens, reminder policy
  │ 250 ms timer for expiry, thresholds and live diagnostics
  ▼
Complete shared state snapshots → all connected simulators
```

`backend/policy.py` owns behaviour independently of camera devices and rendering. `backend/app.py` serialises policy operations and broadcasts with an `asyncio.Lock`. `backend/config.py` validates environment settings; `backend/__main__.py` starts Uvicorn.

One process serves static assets, health and WebSocket traffic. Accepted commands and published timer changes advance a revision counter. Failed sends time out after two seconds per client. If the last accepted observation producer disconnects, its input and active reminder are invalidated; a viewer disconnect does not clear another source.

All clients control one in-memory robot. Restart resets state, history and counters and creates a new instance ID. Use one backend worker. Persistence, separate user sessions and cross-process state synchronisation are not implemented.

### Camera capture and policy integration

Select **Camera** while monitoring is paused, enable monitoring and grant browser
permission. Only that tab receives the session token for sequential JPEG uploads;
other tabs observe shared state without acquiring the webcam. Capture uses
`getUserMedia`, including when the Python backend runs in WSL. Open the app in the
host browser at localhost, or use a validated HTTPS origin. Uploaded pixels are
unmirrored; the development preview is mirrored locally.

`backend/camera.py` keeps JPEG decoding and Face Landmarker on one dedicated
worker. It checks streamed size and JPEG dimensions before decoding. Session,
sequence and age checks prevent paused/replaced or stale frames from reviving
monitoring. Pause, power-off, source change, owner loss, hidden tabs and capture
failure release or invalidate capture. Frames never enter logs or persistent
storage. The versioned model URL/checksum are in [models/README.md](models/README.md).

`backend/app.py` adapts raw camera observations to `ReminderEngine`. Stable visible
presence (default 0.5 s) establishes a diagnostic baseline. Missing faces produce
uncertain observations; continuous uncertainty becomes absent after one second by
default, including initial non-detection. Five further seconds of continuous fresh absence triggers a reminder by default. Poor light and blur can therefore lead to an absence reminder. Stale input remains unavailable. Observation
freshness (1 s) is independent of the capture idle timeout (3 s).

The simulator shows a live detection description below the camera status, plus
preview, face box, presence, quality reason, head direction, angles, raw absence
duration and policy cooldown. Retained eye/mouth observations
are experimental diagnostics inside collapsed details; they do not
establish attention or trigger reminders. Physical accuracy remains unverified.

Select **Simulated** while paused to test the same reminder engine without camera
access or a usable model. Then enable monitoring and choose a synthetic observation.
The source selector is a development control; production-style operation uses
camera input. [Protocol v9](docs/protocol.md) defines both paths. The previous
standalone `backend/behaviour.py` remains for historical regression tests; the live
application has one reminder policy in `backend/policy.py`. Standalone CoreS3
display and camera-preview tests live in `firmware/`; the physical backend
adapter and camera integration remain unimplemented.

## Runtime and Dependencies

| Component | Current choice | Responsibility |
| --- | --- | --- |
| Runtime | Python 3.13 in Conda | Backend and perception processing |
| HTTP and validation | FastAPI 0.162.0, Pydantic 2.14.1 | Routes, command schema and input validation |
| Server and transport | Uvicorn 0.54.0, websockets 17.3 | ASGI serving and WebSocket connections |
| Interface | Plain HTML, CSS and JavaScript | Robot rendering and development controls |
| Camera processing | OpenCV contrib 5.0.0.93, MediaPipe 1.2.0 | JPEG decoding and face/head/eye observations |
| Configuration | python-dotenv 1.2.4 | Local configuration with environment overrides |
| Tests | pytest 9.1.1, HTTPX 0.28.1 | HTTP/WebSocket integration checks |

[`environment.yml`](environment.yml) is the dependency definition. Conda resolves Python 3.13 and pip from `conda-forge`; its `pip` section pins the existing application, transitive and test packages. Python patch releases and pip are not locked to exact versions.

No frontend build step or Node.js runtime is required. The camera dependencies are pinned in the same environment definition; Linux EGL/GLES entries use platform selectors. See [stack choices](docs/stack.md) for the implementation rationale.

## Setup and Run

Install Conda through Miniconda or Miniforge, then run from the repository root:

```sh
sh scripts/setup.sh
sh scripts/dev.sh
```

Setup creates or updates the named `pomo` environment and downloads/checks the versioned model. Recent Conda reads CEP-24 selectors directly; the shell script also supports Conda 25 using a temporary platform-filtered copy of the same definition. Startup uses `conda run` to select it automatically and streams server logs to the terminal.

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Stop the backend with Ctrl+C.

For local configuration, copy `.env.example` to `.env` once and edit the values. Preserve an existing `.env` when rerunning setup; defaults work without this file.

### Direct Conda commands

For Windows without `sh`, use recent Conda with CEP-24 support:

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

Earlier setup records cover macOS ARM64 and the camera contributor’s WSL2 Linux x86-64 environment. See dated [verification records](docs/verification.md) for the integrated checks and remaining platform/browser limits.

## Configuration

The backend reads `.env` from the repository root. Process environment variables take precedence. Changes to startup settings require a backend restart; monitoring, power and mute controls are shared live.

| Variable | Default | Behaviour |
| --- | --- | --- |
| `POMO_HOST` | `127.0.0.1` | Uvicorn bind address |
| `POMO_PORT` | `8000` | Shared HTTP/WebSocket port; accepts 1–65535 |
| `POMO_DEV_CONTROLS` | `true` | Allows simulated observations and expression previews |
| `POMO_UNCERTAINTY_SECONDS` | `1` | Continuous fresh uncertainty before it becomes absent |
| `POMO_ABSENCE_SECONDS` | `5` | Continuous qualifying fresh absence before a reminder; greater than 0, at most 3600 s, and at least the camera tracking-loss grace |
| `POMO_REMINDER_COOLDOWN_SECONDS` | `30` | Quiet period after triggering or dismissing; finite and non-negative |
| `POMO_OBSERVATION_TIMEOUT_SECONDS` | `3` | Maximum observation age; finite and greater than zero |
| `POMO_SOUND_ENABLED` | `false` | Initial shared sound preference; each browser still needs a user gesture for audio |

Boolean settings accept `true` or `false`, case-insensitively. Invalid settings fail at startup. A zero cooldown intentionally permits immediate retriggering after dismissal when continuing absence still qualifies.

Example shell override for a short development demonstration:

```sh
POMO_PORT=8001 POMO_ABSENCE_SECONDS=2 POMO_REMINDER_COOLDOWN_SECONDS=5 sh scripts/dev.sh
```

The browser's simulated input repeats at an interval below the configured freshness timeout. Real producers must also send continuing fresh observations. One absence packet cannot sustain a reminder indefinitely.

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
| `POMO_TRACKING_LOSS_GRACE_SECONDS` | 1 | Duration used to distinguish tracking-loss diagnostics from possible absence |
| `POMO_ABSENCE_SECONDS` | 5 | Shared threshold after qualifying fresh absence begins |
| `POMO_RETURN_SECONDS` | 0.5 | Stable face presence needed to establish the camera diagnostic baseline |
| `POMO_OBSERVATION_MAX_AGE_SECONDS` | 1 | Maximum age/gap of usable evidence |
| `POMO_PERCEPTION_DETECTION_CONFIDENCE` | 0.5 | MediaPipe detection threshold |
| `POMO_PERCEPTION_PRESENCE_CONFIDENCE` | 0.5 | MediaPipe face-presence threshold |
| `POMO_PERCEPTION_TRACKING_CONFIDENCE` | 0.5 | MediaPipe tracking threshold |
| `POMO_PERCEPTION_MIN_BRIGHTNESS` / `POMO_PERCEPTION_MAX_BRIGHTNESS` | 35 / 230 | Usable grayscale mean range |
| `POMO_PERCEPTION_MIN_BLUR_VARIANCE` | 5 | Minimum Laplacian variance; below this is uncertain; 0 disables |
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
Processing results older than the observation limit are unavailable even when the
camera transport remains available. All timing uses the backend's monotonic clock.


## Observations, Expressions and Reminders

An **observation** is the presence value currently used by the backend's reminder
policy. It comes from the selected Camera or Simulated input. An **expression** is
the robot face selected by that policy; the same observation can produce different
expressions depending on elapsed time, cooldown, monitoring and power. These values
describe face presence and input quality, not whether someone is paying attention.

### The four observations

| Observation | When it occurs | Effect while powered on and monitoring |
| --- | --- | --- |
| `present` | The camera detects a usable face, or the Present simulation is selected. | Show `happy`; clear the current absence duration and any active reminder. The existing cooldown is retained. |
| `uncertain` | A fresh camera frame has no detected face, poor light, overexposure, blur or invalid face landmarks, or the Uncertain simulation is selected. A camera with no face produces this value even before a visible-face baseline has been established. | Show `happy` initially and clear the previous absence duration and active reminder. If uncertainty continues with fresh input for **1 second by default**, change the policy observation to `absent`. A `present` observation before then cancels the uncertainty period. |
| `absent` | The Absent simulation is selected, or fresh `uncertain` input continues for the configured uncertainty period. The camera's initial no-face result goes through `uncertain` first. | Show `sad` and start the absence timer. Once absence continues for **5 seconds by default**, show `surprised` and activate a reminder if the cooldown has ended. |
| `unavailable` | There is no current usable input: for example, monitoring has just started, the camera fails or disconnects, input expires, or the Unavailable simulation is selected. Observation is also reset to this value when monitoring is paused or power is turned off. | Show `bored` while monitoring is on; clear pending absence and any active reminder. Unavailable input does not turn into `absent` with time. Power off instead shows `idle`. |

`POMO_UNCERTAINTY_SECONDS` controls the uncertain-to-absent delay (default 1 s),
and `POMO_ABSENCE_SECONDS` controls the subsequent absence-to-reminder delay
(default 5 s). They are separate timers. Fresh input must continue throughout:
if camera observations become stale (default 1 s), or simulated observations
expire (default 3 s), input becomes unavailable and the timers reset. In the
simulator, Present, Absent and Uncertain send repeated observations while selected;
Unavailable sends a single unavailable observation.

Camera diagnostics retain a reason such as `no_face` or `low_light`, but the
displayed `camera_observation.presence` and policy `observation.presence` share
the policy value. Consequently, an `absent` observation after sustained uncertainty
is a policy classification, including when poor image quality caused the
uncertainty; it is not proof that the user left.

### The five expressions

| Expression | When it is displayed | How it changes |
| --- | --- | --- |
| `happy` | Monitoring is on and the latest policy observation is `present`, or fresh `uncertain` has lasted less than the configured uncertainty period. | Changes to `sad` when continuous uncertainty becomes `absent` or Absent is simulated; changes to `bored` on pause or unavailable input, or to `idle` on power off. |
| `bored` | Pomo starts powered on with monitoring paused, monitoring is paused, or monitoring is on but input is missing, expired or unavailable. Wake also returns here with monitoring paused. | Enabling monitoring alone leaves it `bored` until a usable observation arrives. Fresh `present` or initial `uncertain` changes it to `happy`; direct simulated `absent` changes it to `sad`; power off changes it to `idle`. |
| `sad` | The policy observes `absent`, but the absence threshold has not yet triggered a reminder, or absence continues during cooldown after a dismissal. | Sustained fresh absence reaches the reminder threshold and the cooldown ends: `surprised`. Presence or new uncertainty: `happy`. Unavailable input or pause: `bored`. Power off: `idle`. |
| `surprised` | A real reminder has been triggered after sustained absence and is still active. | Dismissal returns to `sad`; presence or newly uncertain input returns to `happy`; unavailable input or pause returns to `bored`; power off changes it to `idle`. |
| `idle` | Pomo is powered off through the soft power control. Monitoring, input, preview, active reminder and cooldown are cleared. | Wake returns to `bored` with monitoring paused; monitoring must then be enabled again. |

For example, with default settings and continuing fresh camera frames, an initial
no-face or poor-quality result shows **Uncertain / Happy**; after 1 second it
becomes **Absent / Sad**; after a further 5 seconds of absence it becomes
**Absent / Surprised**, provided cooldown has ended. Frame sampling and the backend
timer can add a small delay. Present input at any stage returns to Happy; stale or
unavailable input returns to Bored instead of sustaining the countdown.

Pausing or changing monitoring discards old observations and requires fresh input.
Returning presence, the start of uncertainty, unavailable input and pausing clear
active reminders and pending absence duration, but retain remaining cooldown.
Power off is reversible and does not stop the server; a power cycle clears cooldown.

A triggered reminder stays active until dismissed, presence returns, input becomes
uncertain or unavailable, monitoring pauses or power turns off. It does not repeatedly
retrigger when its original cooldown expires. Dismissal starts a full new quiet
period (default 30 s); continuing absence may trigger again only after that period.
Every real reminder has an increasing ID scoped to the backend instance, so stale
dismissals and repeated snapshots cannot replay a previous cue.

**Expression previews** are development controls available while Pomo is powered on
and monitoring is paused. They temporarily override the displayed face without
changing the actual policy state, activating a reminder or playing sound. Clear the
preview, enable monitoring or change power to return to the actual state.

Sound is optional and initially muted. Unmute/enable audio through a user gesture in each tab. A newly received real reminder can play one short cue; initial/reconnect snapshots, preview expressions and repeated snapshots do not replay it. Browser audio restrictions or unsupported audio do not prevent visual reminders.

## HTTP and WebSocket Interface

| Endpoint | Transport | Contract |
| --- | --- | --- |
| `/` | HTTP GET | Simulator and same-origin static assets |
| `/health` | HTTP GET | Service status, phase 2, protocol 9 and camera processor readiness |
| `/ws` | WebSocket | Strict JSON commands, complete state snapshots and validation errors |
| `/camera/frame` | HTTP POST | Bounded raw JPEG with private camera-session and increasing sequence headers |

Protocol version 9 unifies camera and policy presence as `present`, `absent`, `uncertain` and `unavailable`. Both `camera_observation.presence` and `observation.presence` expose the same current value; camera diagnostics retain the reason separately. Update backend and simulator together; v8 and earlier clients are incompatible.

Commands cover `set_input_source`, `camera_failed`, `set_monitoring`, `set_power`, `set_muted`, `dismiss_reminder`, `submit_observation`, `preview_display` and `clear_preview`. For example:

```json
{"type":"set_monitoring","enabled":true}
{"type":"set_muted","muted":false}
{"type":"dismiss_reminder","reminder_id":1}
```

Each snapshot includes actual `behavior_state`, rendered `display`, power/monitoring/mute state, camera/input metadata, observation-session token, absence duration, cooldown, active reminder, settings and up to 100 backend events. Manual previews require power on and monitoring paused; they change rendering only and never create reminders or sounds.

Observation producers copy the latest session token, send strictly increasing finite Unix timestamps and discard buffered packets on lifecycle changes or disconnect. A source timeout invalidates the session. Unknown/binary/malformed messages and extra or incorrectly typed fields are rejected without applying a policy operation. Incoming message size is limited to 4,096 bytes. Full schemas, examples and recovery rules are in [protocol v9](docs/protocol.md).

The simulator retries connections with capped exponential backoff and disables controls until a valid snapshot arrives. Disconnect stops simulated heartbeats and local audio. Reconnection restores current shared state but requires a fresh simulated-input selection; offline commands and old sounds are not replayed.

## Verification

Run the Python checks and package-consistency validation:

```sh
conda run --name pomo python -m pytest -q
conda run --name pomo python -m pip check
```

Optional UI behaviour checks use Node.js's built-in test runner, with no npm dependencies:

```sh
node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs
node --check simulator/app.js
node --check simulator/camera.js
```

Node is needed only for these JavaScript checks, not to run Pomo. The Python suites cover pure policy, WebSocket integration and configuration. The JavaScript suite checks simulated heartbeat lifecycle, control gating, sound deduplication/audio fallback, error handling and safe log rendering.

The existing Starlette/HTTPX test-adapter deprecation warning remains. See [verification records](docs/verification.md) for dated results and material limits.

Manual simulator demonstration:

1. Start the backend, open the simulator and confirm Connected.
2. While paused, select Simulated input, then enable monitoring. Without input the expression is Bored.
3. Select Absent under simulated input. Continuing fresh observations first show Sad, then a visual reminder after the threshold.
4. Dismiss it and watch the cooldown. Select Present to clear pending absence; select Uncertain or Unavailable to stop detection-driven reminders.
5. Enable sound through the button to allow local audio for new reminders; mute stops an in-flight cue.
6. Pause monitoring, then preview all five expressions. Previews do not trigger real reminders or sound.
7. Power off and wake Pomo. Verify wake leaves monitoring paused.
8. Open a second tab and check shared state. Reconnect a viewer without replaying sound; disconnect the observation-producing tab and check the Bored expression.

For a camera demonstration, pause, select Camera, enable and grant permission. Leave a well-lit, sufficiently detailed scene for the uncertainty period plus absence threshold. Check the real reminder, dismissal/cooldown and return. Test denied permission, owner-tab closure, hidden tabs and interruption; explicitly retry with a fresh session. Physical validation is still needed.

The debug panel shows current observation/source/age, absence duration, cooldown, actual state and backend events. Clearing the browser log clears that tab's view only; it does not erase shared backend history.

### No camera preview

Open the app directly at `http://127.0.0.1:8000` or a validated HTTPS origin.
Allow camera access for that site and for the browser in macOS **System Settings
→ Privacy & Security → Camera**. In Chrome, **Settings → Privacy and security →
Site settings → Camera** also lets you select the intended physical camera.
See [Chrome camera permissions](https://support.google.com/chrome/answer/2693767)
and [macOS camera access](https://support.apple.com/guide/mac-help/mchlf6d108da/mac).

Keep the Pomo tab visible while starting capture. Switching tabs/apps can stop
capture, including while permission is pending. Return to Pomo and use **Retry
camera** after changing permissions or camera settings. Pause other camera apps
if the browser reports that it cannot start the device.

Read the message below the camera preview and the main feedback area. Capture,
preview playback, frame encoding and upload errors have separate explanations;
a preview-playback failure does not mean camera permission was denied. Include
that exact message, browser and page address when reporting a failure.

`camera_processor_ready: true` in `/health` confirms model initialization, while
`camera_started` records a browser capture request. Neither confirms that browser
video has started. Successful `POST /camera/frame` requests confirm frame delivery.
Favicon, Apple touch icon and Chrome DevTools discovery 404s are unrelated to
camera capture.

## Deployment Constraints

For a cloud development workspace, install Conda, run setup and start the server with:

```sh
POMO_HOST=0.0.0.0 sh scripts/dev.sh
```

Forward the configured port privately through the workspace provider. The proxy must support WebSocket upgrades and serve the application at the URL root; a path-prefix proxy is not configured. Forwarded HTTPS/WSS access requires validation in the target workspace.

The development server has no authentication, and every connected client can control the shared robot. Keep access restricted through the workspace's access controls.

Capture occurs in the browser and JPEG processing occurs in the backend. On remote deployments, frames travel to that backend. The intended laptop prototype runs both on localhost; no recording is implemented.

## Repository Structure

```text
backend/
  app.py              FastAPI transport, strict commands, timer and broadcasts
  policy.py           Camera-independent state/reminder policy and bounded events
  config.py           Validated server, reminder, camera and perception configuration
  camera.py           Dedicated JPEG/model worker
  perception.py       Face Landmarker and head-direction observations
  eyes.py             Experimental per-eye diagnostics
  observations.py     Immutable raw camera observation schema
  behaviour.py        Previous standalone camera policy, retained regression tests
  __main__.py         Configuration loading and Uvicorn entry point
simulator/
  index.html          Robot display and simulator controls
  app.js              WebSocket client, state/reminder rendering and reconnection
  camera.js           Browser permission/capture, preview and sequential uploads
  style.css           Responsive monochrome interface
firmware/
  README.md           Hardware integration and display-test notes
  display-test/       Standalone PlatformIO CoreS3 display test
  camera-test/        Standalone PlatformIO CoreS3 camera preview
docs/
  protocol.md         Current WebSocket message contract
  stack.md            Technology decisions
  verification.md     Recorded checks and limitations
scripts/
  setup.sh            Create/update the pomo Conda environment
  dev.sh              Start the backend inside that environment
  setup_model.py      Checksum-verified model download
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

- [x] Integrate browser webcam capture, start/stop lifecycle, preview, bounded uploads and availability/error reporting.
- [x] Preserve the pinned OpenCV/MediaPipe detector, versioned model, presence and head-direction diagnostics.
- [x] Add timestamp/session freshness validation and explicitly handle unknown, unavailable and expired observation metadata.
- [ ] Evaluate the real detector under poor lighting and temporary tracking loss.
- [x] Define the five backend states and configurable sustained-absence thresholds.
- [x] Rename the five state and expression identifiers in protocol v8; the visual mapping and reminder rules are unchanged.
- [x] Connect simulated/producer observation metadata to backend decisions and broadcast the resulting state.
- [x] Adapt camera observations to the shared reminder contract with baseline, grace and freshness gates; physical webcam validation remains pending.
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
