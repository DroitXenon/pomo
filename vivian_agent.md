- [x] Web cam implementation
- [x] Define the observations to detect, such as face presence and head direction.
- [x] Now we detect whether user leave the sight
- [ ] Define how observations indicate *possible* distraction
- [ ] Require observations to persist for a configurable duration before triggering a reminder.
- [ ] Handle uncertain results, poor lighting and temporary tracking loss.

# Vivian agent implementation record

Recorded on **2026-11-01**. This records the camera and detection work completed
in this conversation in `/home/vivian/pomo`, using Python 3.13 in the activated
`pomo` Conda environment and the existing `feature/camera` branch.

The checklist above preserves Vivian's requested wording and checkbox statuses.
It is a review checklist, rather than an exact statement of implementation status:
configurable persistence, uncertainty handling, lighting checks and temporary-loss
handling are already implemented and covered by automated tests, but physical
webcam evaluation remains pending. The relevant unchecked items are left unchanged
for Vivian to review. “Leave the sight” currently means sustained face non-detection;
it does not prove the user physically left. A broader distraction interpretation
has not been implemented: head direction and expression scores are diagnostics.

## Working conventions

- Describe delivered work as implemented.
- Document the current implementation without obsolete feature descriptions.
- Keep agent-authored code free of unused state and superseded logic.
- Limit maintenance to agent-authored code and documentation; preserve other work.

## Implemented application and setup code — 8 files

| File | What it does |
| --- | --- |
| [simulator/camera.js](simulator/camera.js) | Accesses the webcam through the Windows browser, attaches the stream to the live preview, samples JPEG frames and uploads them sequentially. Handles permission errors, cancelled requests, late permission grants and media-track cleanup. |
| [backend/camera.py](backend/camera.py) | Owns the dedicated processing thread. Checks JPEG format and dimensions before OpenCV decoding, converts BGR to RGB, passes frames to perception, and opens/closes the perception model on the worker. |
| [backend/perception.py](backend/perception.py) | Runs MediaPipe Face Landmarker on usable frames. Checks brightness and blur/detail, extracts face presence, a normalized face box, head angles and eye and mouth movement scores and iris observations. Implements automatic head-direction classification with hysteresis and exports model up/down eye signals. Does not decide reminders. |
| [backend/eyes.py](backend/eyes.py) | Implements per-eye iris position and coarse direction relative to eye corners/lids. Uses eye-local pixel axes and blink/head-pose checks; independent of reminders. |
| [backend/observations.py](backend/observations.py) | Defines validated `Observation`, `HeadPose`, `EyeMovement` and `IrisObservation` structures carrying timestamps, presence, quality metrics, head pose, face box and blendshapes. Images are not included. |
| [backend/behaviour.py](backend/behaviour.py) | Makes reminder decisions from observations: initial visible-face baseline, tracking-loss grace, sustained absence, stable return and dismissal. Does not access the camera or read a clock itself. |
| [backend/config.py](backend/config.py) | Defines and validates camera, perception and behaviour settings. Reads environment-variable overrides and rejects invalid combinations, such as a grace period longer than the absence threshold. |
| [scripts/setup_model.py](scripts/setup_model.py) | Downloads a specific Face Landmarker model revision and verifies its SHA-256 checksum. Reuses a valid existing download and checks new content before replacing a file. |

## Implemented tests and test support — 9 files

| File | What it checks or provides |
| --- | --- |
| [tests/test_camera.py](tests/test_camera.py) | Camera ownership, uploads, invalid/oversized images, stale sequences and sessions, timeouts, backpressure, pause/disconnect cleanup and initialization/processing failures. |
| [tests/test_perception.py](tests/test_perception.py) | Head-angle calculations, invalid poses, direction hysteresis, image-quality gates, model-result conversion and observation validation. |
| [tests/test_eyes.py](tests/test_eyes.py) | Tests per-eye directions, eye-local roll/scale normalization, blink/closed-eye handling, head-angle limits, invalid geometry and inference integration using synthetic landmarks. |
| [tests/test_behaviour.py](tests/test_behaviour.py) | Reminder timing, initial face baseline, temporary loss, continuous absence, stable return, uncertain/stale input, dismissal and pause/resume using synthetic observations and explicit times. |
| [tests/test_detection_integration.py](tests/test_detection_integration.py) | Sends synthetic detection results through the real HTTP/WebSocket application and verifies automatic head direction, reminders, dismissal, stale-input handling and shared snapshots. |
| [tests/test_camera_client.cjs](tests/test_camera_client.cjs) | Checks late permission grants after cancellation, sequential uploads, upload aborts, track cleanup and permission-denial messaging with mocked browser APIs. |
| [tests/test_simulator.cjs](tests/test_simulator.cjs) | Checks observation rendering, actual reminders versus manual previews, dismissal commands and uncertain-input messages. |
| [tests/camera_helpers.py](tests/camera_helpers.py) | Provides a processor that uses real JPEG decoding while bypassing model initialization and inference, so transport tests do not need a physical camera or model download. |
| [tests/__init__.py](tests/__init__.py) | Empty package marker allowing test modules to import shared helpers. |

The 17 code files above implement the camera, perception and test modules.
The following table records implementation within existing project files.

## Implementation within existing files

| Existing file | Implementation |
| --- | --- |
| [backend/app.py](backend/app.py) | Implemented application lifespan management for the worker/model, bounded `POST /camera/frame` ingestion, session tokens tied to the owning WebSocket, sequence validation, single-job backpressure, processing deadlines and a watchdog. Connected observations to behaviour and reminder dismissal. Extended snapshots with camera, frame, observation and behaviour diagnostics. |
| [backend/__main__.py](backend/__main__.py) | Loads validated camera, perception and behaviour settings from the environment and passes them into the application factory. Existing server startup remains the entry point. |
| [simulator/index.html](simulator/index.html) | Implemented the video preview, face-box canvas, camera/detection statuses, detection diagnostics, supportive reminder message and dismissal control. Preserved the robot simulator and manual expression controls. |
| [simulator/app.js](simulator/app.js) | Connected backend snapshots to browser capture and detection rendering. Implemented the dismissal command, observation and head-direction displays, quality reasons, absence duration, detection state, face-box drawing and separate eye/mouth movement rows. Stops capture on disconnect/pagehide/tab hiding, disables unavailable controls, and limits journal noise from repeated frame snapshots. |
| [simulator/style.css](simulator/style.css) | Implemented camera panel, video preview, mirrored face overlay, expression-score wrapping and reminder styling while preserving the dark grayscale interface. |
| [environment.yml](environment.yml) | Pinned OpenCV contrib 5.0.0.93, MediaPipe 1.2.0 and camera-processing Python dependencies. Implemented Linux-only EGL/GLES libraries required by MediaPipe in WSL, using CEP-24 selectors. Kept the existing Conda environment workflow. |
| [.env.example](.env.example) | Documented camera constraints, frame limits/timeouts, model path override, perception confidence/quality/head/iris-direction settings and absence/reminder timing defaults. Existing local `.env` values were preserved. |
| [scripts/setup.sh](scripts/setup.sh) | Uses CEP-24 parsing for platform-specific environment dependencies and runs the model download/checksum helper after environment setup. |
| [.gitignore](.gitignore) | Excludes downloaded model binaries, partial model downloads, temporary Conda requirement files and local `.tools/` verification utilities. Existing camera frames are not persisted by the app. |
| [tests/test_backend.py](tests/test_backend.py) | Implemented phase-2 health/readiness assertions and owner-only token assertions using the camera-independent test processor. |
| [README.md](README.md) | Implemented browser/WSL capture, processing, observations, reminder behaviour, configuration, setup instructions and manual checks. Preserves the simulator → command validation → shared state → clients diagram and its Uvicorn, locking, revision, broadcast-timeout and single-worker explanation. |
| [docs/protocol.md](docs/protocol.md) | Documented camera ownership, JPEG upload headers, validation, backpressure, timeouts and lifecycle. Implemented observation/behaviour fields, `dismiss_reminder`, along with freshness and reminder semantics. |
| [docs/stack.md](docs/stack.md) | Recorded OpenCV/MediaPipe choices, browser capture for WSL, the dedicated worker, Linux native dependencies, quality gates and separation of perception from behaviour. |
| [docs/verification.md](docs/verification.md) | Records camera, observation and reminder validation, with physical-camera and browser limitations. |
| [AGENTS.md](AGENTS.md) | Documents implemented capture, observations and reminder policy within the existing scope and workflow instructions. |

## Documentation and model assets

| Item | Purpose |
| --- | --- |
| [models/README.md](models/README.md) | Records the official model URL, revision, checksum, setup instructions and model lifecycle. |
| `models/face_landmarker.task` | Downloaded official Face Landmarker float16 revision 1 model. It is a local binary asset, ignored by Git, not source code or a camera recording. |
| `.tools/` | Ignored local Node 22.14.0 executable and download archive used for JavaScript verification. Node is not an application runtime requirement. |
| [vivian_agent.md](vivian_agent.md) | This implementation and handoff record. |

## Implemented architecture and behaviour

```text
Windows browser camera
  → getUserMedia → local video preview
  → sampled JPEG uploads to POST /camera/frame
  → dedicated worker: JPEG validation → OpenCV decode → RGB conversion
  → quality gate → MediaPipe Face Landmarker
  → timestamped observations → backend absence/reminder policy
  → shared state + revision → /ws snapshots → detection diagnostics
```

The original command path still exists alongside frame ingestion:

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

- Capture happens in the Windows browser because this WSL environment initially
  exposed no `/dev/video*` device. The implementation does not use `VideoCapture(0)`.
  OpenCV handles image decoding/conversion and quality checks in Python.
- Only the tab enabling monitoring owns the capture session; other clients receive
  shared robot state without its upload token. Any client can pause monitoring.
- Uploads are bounded, ordered and sequential. Invalid sessions, repeated sequences,
  invalid JPEGs, excessive dimensions, oversized bodies and busy processing are
  rejected. Late results cannot revive an expired or paused session.
- Camera capture/transport status, connection status, face observations and robot
  display remain separate. Model initialization failure leaves the server reachable
  but reports an unavailable processor and rejects capture enable commands.
- Pause, owner loss, tab hiding, capture/upload failure and timeouts stop or
  invalidate capture. Late permission grants after cancellation release tracks.
  Model processing stays on the dedicated worker; the model loads once per app
  lifecycle and closes on shutdown. Frames remain in memory.
- Stable face presence establishes the baseline. Brief loss uses the grace period.
  Continuous non-detection then shows possible absence and eventually a reminder.
- Poor-quality, stale or unavailable input cancels pending evidence and active
  reminders. Fresh stable face presence is required before absence can remind again.
- A stable return clears a reminder. Dismissal clears the active reminder and resets
  the absence countdown.
- Head direction and yaw/pitch/roll are estimated automatically relative to the
  camera.
  A turned first frame is not treated as forward; missing pose yields unknown.
  Selected blendshapes
  describe facial movements; neither head direction nor expressions trigger reminders.
- Manual expression previews control the robot face independently of detections.
  Observations, stale input, camera failures and reminder dismissal preserve the
  selected expression. Explicit monitoring commands retain the ready reset.
- Detection status, reminder messages and dismissal controls belong to Detection
  details. Repeated snapshots do not repaint unchanged expression/title content or
  reset idle video sources. There is no full-page reload command in the app.

Eye movement, Iris vertical offsets, Vertical eye signals and Mouth movement
rows are hidden in the frontend; observation generation and snapshots remain active.
The hidden eye movement diagnostics retain subject-left/right iris direction (`center`, `left`,
`right`, `up`, `down`, `closed`, `unknown`) followed by blink scores. Mouth movement diagnostics
show jaw opening and left/right smile scores. Eye-local axes account for head roll;
strong head yaw/pitch and invalid measurements yield unknown. A detected blink or
valid closed-lid geometry reports closed for that eye. Coarse iris
observations never trigger reminders or establish screen gaze.

Vertical direction uses signed iris displacement from the eye-corner line divided
by eye width (up negative, down positive), with a default threshold of 0.08. It does
not assume that neutral iris position is the midpoint of the eyelid opening.
Qualified MediaPipe up/down coefficients (at least 0.30 and 0.10 above the opposite)
permit a half-sized displacement in the same direction. Coefficients cannot force
up/down when geometry is centered or points the opposite way. Hidden diagnostic rows
retain Iris vertical offsets and Vertical eye signals for webcam evaluation.

### Iris availability and blink interpretation

| Condition | Implemented result |
| --- | --- |
| Absolute head yaw exceeds 60° or pitch exceeds 45° | Open-eye directions are `unknown`, reason `head_turned`. A qualifying raw blink score can still report closed. |
| An eye's blink score is at least 0.55 | That eye's direction is `closed`, reason `blink`; its blink score follows continuous normalization. |
| Eye-opening height divided by eye width is below 0.12 | With valid geometry, ratios below 0.06 report closed; ratios below 0.12 report closed when no qualified vertical eye signal is present. Blink score follows continuous normalization. |

These are prototype application thresholds chosen for the coarse estimator, not
limits imposed by MediaPipe. Head-angle limits restrict extreme perspective with the current 2D geometry.
Eye-opening measurements use the median of three lid pairs to reduce sensitivity
to a single misplaced landmark. A wider allowed angle does not itself establish
better measurement accuracy. Their accuracy
and the blink threshold require physical-webcam evaluation.

Blink scores are MediaPipe facial blendshape coefficients, not calibrated eyelid
closure percentages. A closed eye is not guaranteed to produce 1.00; readings of
0.60–0.70 can occur. The default raw label threshold is 0.55. Raw coefficients remain in `blendshapes`.
Each eye's displayed blink score is `clamp(raw / 0.60, 0, 1)`, using a configurable
full-closure reference. For example, raw values 0.30, 0.45, 0.54, 0.57 and 0.60
produce scores 0.50, 0.75, 0.90, 0.95 and 1.00. Direction classification and score
normalization are separate: the closed label does not force a binary numeric value.
No coefficient means an unavailable score even if lid geometry gives a closed
label. These are approximate normalized signals, not measured physical percentages
or model confidence. Reference: [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker).

The availability checks are in [backend/eyes.py](backend/eyes.py), with configurable
head-angle/blink thresholds in [backend/config.py](backend/config.py).

## Important settings and interface values

| Setting or value | Current default or meaning |
| --- | --- |
| Python / OpenCV / MediaPipe | Python 3.13 / `opencv-contrib-python==5.0.0.93` / `mediapipe==1.2.0` |
| Camera target | 640 × 480, up to 10 sampled uploads/second, JPEG quality 0.75 |
| Upload limit | 524,288 bytes; one body/decode operation at a time |
| Active camera timeout / startup allowance | 3 seconds / 30 seconds |
| `POMO_TRACKING_LOSS_GRACE_SECONDS` | 1 second, included within total absence duration |
| `POMO_ABSENCE_SECONDS` | 10 seconds of continuous non-detection |
| `POMO_RETURN_SECONDS` | 0.5 seconds of stable presence for baseline/return |
| `POMO_OBSERVATION_MAX_AGE_SECONDS` | 1 second for evidence age and gaps |
| Brightness / blur gate | Mean grayscale range 35–230; minimum Laplacian variance 15 |
| Head-direction thresholds | Yaw 30°, pitch 25°, exit hysteresis 5° |
| Iris thresholds | Horizontal midpoint margin 0.15; vertical corner-relative threshold 0.08 eye widths; blink threshold 0.55; maximum head yaw 60° / pitch 45° |
| Blink full-closure reference | `POMO_PERCEPTION_EYE_BLINK_FULL_CLOSURE=0.60`; continuous normalization to 1.00 |

Configuration definitions are in [backend/config.py](backend/config.py); all
available variables are recorded in [.env.example](.env.example).
`Behaviour.observe()` evaluates sustained absence. `Behaviour.dismiss()` clears
the active reminder and resets pending absence. `Behaviour.snapshot()` exports
current detection status and absence duration through `/ws`.

The versioned model's SHA-256 is
`64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff`.
Only one OpenCV distribution is installed. No OpenCV 4 dependency was retained.

## Validation

Verification records and platform limitations are in
[docs/verification.md](docs/verification.md).

| Check | Recorded result |
| --- | --- |
| Full backend suite: `python -m pytest -q` | 115 passed; the existing Starlette/HTTPX deprecation warning remains. |
| Client capture lifecycle tests | 4 passed with mocked browser APIs. |
| Simulator rendering tests | 10 passed with mocked browser APIs. |
| JavaScript syntax checks | Passed for `simulator/app.js` and `simulator/camera.js`. |
| Package consistency: `python -m pip check` | No broken requirements. |
| Environment/model setup | Conda environment setup and model checksum verification passed; CEP-24 setup verified with Conda 26.9.4. |
| Real-model smoke | Detailed synthetic noise ran inference and produced no face/awaiting-face; a black image produced unknown/low-light without a reminder. Model initialization, HTTP ingestion, WebSocket state and shutdown passed. An official public portrait produced usable center iris observations for both eyes, processed only in memory. |
| Shell syntax and whitespace checks | Setup/dev shell syntax and `git diff --check` passed in the recorded implementation work. |

Core policy tests use synthetic observations and a controllable clock, without a
physical webcam or timing sleeps. Images for smoke checks stayed in memory.
Sandboxed HTTP/WebSocket tests stalled in the test client's event-loop portal;
they passed when run outside that tool sandbox. No application workaround was added.

## Remaining validation and deferred work

- Test a real Windows-browser webcam end to end: permissions, preview, frame box,
  actual absence reminders, dismissal, return, interruption and resource release.
- Evaluate detection accuracy, false reminders and missed absences across lighting,
  distance, head positions, occlusion and reading notes.
- Validate physical head/iris-direction signs and coarse eye-position thresholds. It is approximate head
  orientation, not eye gaze or identity recognition.
- Tune brightness and blur/detail thresholds. A plain background may be treated as
  low detail and suppress reminders. `POMO_PERCEPTION_MIN_BLUR_VARIANCE=0` disables
  that gate for evaluation.
- Validate browser layout, accessibility, responsive behaviour and actual tab/
  permission lifecycle. Current client tests mock browser APIs.
- Validate Windows/macOS installation and private HTTPS/WSS forwarding.
- Define any broader *possible distraction* interpretation before adding it to the
  reminder policy. Presence, head direction and facial movements do not prove attention.
- Optional sound with independent mute, interactive simulated-observation controls,
  physical robot integration, Pomodoro/session controls and voice recognition remain
  outside the completed implementation.

No camera recording, image persistence, personal identity recognition or emotion
classification was added. No commit, push, merge or deployment was performed by
the agent during this work.

## Run the app

From WSL:

```sh
cd /home/vivian/pomo
conda activate pomo
python -m backend
```

Open `http://localhost:8000` in the Windows browser, enable monitoring and grant
camera permission. Remain visible briefly to establish the baseline; face forward
to see automatic direction and angle diagnostics. If setup is needed, run
`sh scripts/setup.sh` first. Stop the backend with Ctrl+C.


## Absence counter and possible-absence detection

`backend/behaviour.py` starts the absence interval on the first fresh non-detection,
even before the visible-face baseline exists. `behaviour.absence_seconds` and the
`possible_absence` transition use that same interval. Default grace is 1 second;
reminders still require stable face presence first and 10 seconds of absence.
Unknown/stale/unavailable input and visible presence reset the interval. The counter
advances with observations rather than wall-clock waiting. Manual expressions remain
independent of the detection status.

Policy, HTTP/WebSocket and simulator checks cover initial non-detection, the exact
grace boundary, counter reset/restart after uncertainty, shared snapshot rendering
and expression isolation. Physical-camera evaluation remains pending.
