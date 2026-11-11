# Phase 1 verification — 26 October 2026

Verified locally on macOS with Python 3.13:

- Four pytest integration tests passed: health/static routes, multi-client state
  broadcast and reconnect/restart semantics, malformed commands and disabled previews.
- JavaScript syntax check passed (`node --check simulator/app.js`).
- Real Uvicorn server bound to 127.0.0.1:8000.
- Live HTTP requests returned 200 for /, /health, /app.js and /style.css.
- Two real WebSocket clients received matching updates for all four expression
  previews. A new connection received current state after clients disconnected.

Limitations:

- No browser was available through the UI automation tools. Rendered appearance,
  responsive layout and browser-side automatic reconnection need a manual check
  using the README demo. Backend reconnection was verified separately.
- No cloud workspace/provider was available; forwarded HTTPS/WSS preview remains
  unverified. Cloud startup instructions are included in the README.
- The test stack emits a Starlette deprecation warning for its HTTPX test adapter;
  the tests currently pass. Revisit the adapter when upgrading test dependencies.
- A teammate's independent fresh installation has not been performed.

Camera detection, reminder policy and physical hardware are intentionally outside
Phase 1. No camera or microphone permissions were requested.

## Conda setup verification — 31 October 2026

Verified on macOS ARM64 with Conda 25.1.1 and Python 3.13.18:

- `sh scripts/setup.sh` created the `pomo` environment from `environment.yml`.
  A second run completed successfully with the same 24 pinned Python packages.
- `conda run --name pomo python -m pytest -q` passed all four integration tests.
  The existing Starlette/HTTPX deprecation warning remains.
- `conda run --name pomo python -m pip check` found no broken requirements.
- `scripts/dev.sh` started the backend through Conda on a temporary localhost
  port. `/` and `/health` returned 200, a WebSocket expression command was
  acknowledged, and Ctrl+C shut down the backend.

Conda setup on Windows and Linux has not been verified.

## States, reminders and debug logs — 31 October 2026

Implemented on `agent/feature/states` against the Reminders, States Implementation
and Debug Logs task specifications linked in [protocol v2](protocol.md#task-sources).
Verified on macOS ARM64 with the existing Python 3.13.18 Conda environment and
Node.js 26.11.1. No dependency additions were required.

- `conda run --name pomo python -m pytest -q`: 137 passed (41 pure-policy,
  50 HTTP/WebSocket integration and 46 configuration cases). Timing tests use
  injected monotonic/epoch clocks without camera hardware or timing sleeps.
- `conda run --name pomo python -m pip check`: no broken requirements.
- `node --test tests/test_simulator.js`: seven passed. These execute the actual
  simulator JavaScript using mocked DOM, WebSocket, timers and audio objects;
  they do not verify rendered layout or audible output in a browser.
- `node --check simulator/app.js`, shell-script syntax checks and
  `git diff --check` passed.
- A real server started through `scripts/dev.sh` on a temporary localhost port.
  `/`, `/health` and both static assets returned 200. A live observation producer
  and viewer exercised threshold-driven reminders, restoration of an active
  reminder on reconnect, no repeated active cue, dismissal with a full quiet
  period, subsequent reminders, producer-disconnect invalidation, presence and
  uncertain/unavailable input, global pause, soft shutdown/wake and mute.
  Shortened smoke-check settings were 0.5 s absence, 1 s cooldown and 0.8 s input
  timeout; committed defaults remain 5 s, 30 s and 3 s respectively.
- Ctrl+C completed backend shutdown. Both temporary verification servers were
  stopped afterwards.

Remaining limits:

- Browser access reported an unavailable host; native Arc/Chrome access failed
  with `cgWindowNotFound`. Desktop/narrow rendered layout, browser interaction
  and the physical audibility of the sound cue remain unverified for this change.
- Real camera capture/perception and physical firmware are not implemented.
  Metadata ingestion is ready for a separate camera adapter; no images/video
  were captured or stored during these checks.
- Windows, Linux, cloud proxy forwarding and teammate usability remain untested.
- The existing Starlette/HTTPX test-adapter deprecation warning remains.

## Camera, observations and behaviour — 31 October–1 November 2026

Implemented in `/home/vivian/pomo` on `feature/camera`, using the activated `pomo`
environment with Python 3.13.18, OpenCV contrib 5.0.0.93 and MediaPipe 1.2.0.

### Environment and model

- Conda setup with CEP-24 selectors passed using Conda 26.9.4. Linux-only EGL/GLES
  dependencies support MediaPipe in WSL. Model float16 revision 1 checksum passed;
  source and SHA-256 are recorded in `models/README.md`.
- Real-model smoke checks passed for initialization, JPEG decoding, RGB conversion,
  inference, HTTP ingestion, WebSocket snapshots, pause and shutdown. A detailed
  synthetic noise scene produced no face/awaiting-face; a black scene produced
  unknown/low-light without a reminder. Images stayed in memory.
- Real-model iris inference on the official public MediaPipe `portrait.jpg` asset
  passed: a present face and usable center direction for both eyes. The source was
  `https://storage.googleapis.com/mediapipe-assets/portrait.jpg`; the image was held
  in memory only. Actual up/down coefficients were exported for both eyes, with
  neutral portrait directions remaining center. This checks the model-to-observation
  path, not physical gaze accuracy.
- `python -m pip check`: no broken requirements.

### Automated checks

- Backend suite: **112 passed**, with the existing Starlette/HTTPX deprecation
  warning. Tests cover frame validation, ownership, ordering, backpressure,
  expiration, worker lifecycle, observations, head angles/direction, continuous
  absence, stable return, dismissal and uncertain/stale/unavailable input.
- Policy tests use synthetic observations and explicit monotonic times without a
  physical camera or timing sleeps. HTTP/WebSocket integration covers automatic
  head/iris direction, per-eye blink handling, eye/mouth score transport and stale
  inference. Synthetic geometry covers both eyes, all directions, scale/roll, closed
  eyes, missing/invalid landmarks, head-angle boundaries (including 60° yaw /
  45° pitch), and single-lid outliers. Blink scores in 0.55–0.70 suppress iris
  direction with a closed classification while remaining unscaled in observations. Eye opening uses median
  projections from three eyelid pairs. Blink UI tests verify intermediate values through the closed-label boundary,
  continuous reopening, per-eye independence and raw-score preservation. Normalized
  values use a configurable full-closure reference rather than a binary label override. Closed lids
  without iris points and invalid lid ordering are covered by geometry tests. Sustained eye observations
  with a visible face do not trigger absence reminders.
- Thirteen mocked Node tests passed: four capture-lifecycle tests and nine simulator
  rendering tests. JavaScript syntax checks passed for both modules. Node 22.14.0
  is an ignored local verification utility, not an application runtime dependency.
- Corner-anchored vertical regressions cover asymmetric lids with centered iris,
  upward iris/lid translation with centered lid-relative ratios, and model signals
  that disagree with geometry. The official portrait retains center for both eyes.
  This does not validate the reported live camera setup; center/up readings are
  required to assess physical accuracy. Signed offsets are exposed in diagnostics.
- Vertical-direction regressions cover both eyes with lids and iris moving together,
  weak/ambiguous model signals, narrow open lids, blink precedence, raw coefficient
  export and diagnostic rendering. Synthetic regressions establish algorithm paths;
  live up/down detection is not verified by those tests.
- All four manual expressions persist through detections, absence/reminding,
  uncertainty, stale observations, dismissal and camera failure. Explicit monitoring
  commands retain the ready reset. Rendering tests confirm stable selected buttons,
  no repeated robot/title writes for identical expressions, and no idle-video resets.
  Detection/reminder controls are in camera diagnostics. No full-page reload command
  exists in the app; real-browser refresh behaviour remains unverified.
- `sh -n scripts/setup.sh scripts/dev.sh` and `git diff --check` passed.
- HTTP/WebSocket checks require execution outside this tool sandbox: sandboxed
  Starlette TestClient stalls in its event-loop portal before application startup.

### Physical validation pending

- Windows-browser webcam access, permission/tab lifecycle, resource release,
  responsive layout, accessibility, Windows/macOS installation and HTTPS forwarding.
- Face detection accuracy, head/iris-direction signs, per-eye thresholds and
  lighting/blur thresholds on a physical webcam. Plain backgrounds can be classified
  as low detail; the blur gate is configurable for evaluation.
- Head direction and yaw/pitch/roll are automatic camera-relative diagnostics.
  Eye movement and mouth movement have separate frontend diagnostics. Iris positions
  are approximate and do not establish screen gaze. Facial movement scores do not establish
  attention, emotion or identity and do not trigger reminders.


## Diagnostic row visibility — 2 November 2026

Implemented a hidden container for Eye movement, Iris vertical offsets, Vertical
eye signals and Mouth movement. Observation generation, transport and existing
rendering hooks remain active. An HTML parser check confirmed all four rows have
a hidden ancestor while face presence, head direction, head angles and absence
remain visible. `git diff --check` passed. Real-browser appearance was not tested.


## Absence duration and possible absence — 2 November 2026

Implemented absence timing from the first fresh non-detection observation,
independent of reminder arming. The same observation interval drives the displayed
counter and possible-absence grace threshold. Stable visible-face baseline remains
required for reminders. Unknown/stale/unavailable input resets evidence; subsequent
fresh non-detection starts a new counter interval. Manual Expression stays independent.

- Activated `pomo`: `python -m pytest -q -o faulthandler_timeout=20` passed
  **115 tests** in 4.77 seconds, with the existing Starlette/HTTPX warning.
- Tests cover initial non-detection, exact grace boundary, uncertainty reset/restart,
  counter snapshots, reminder gating and HTTP/WebSocket transport.
- Ten mocked simulator rendering tests passed, including counter/status alignment
  and preservation of the selected expression.
- `git diff --check` passed. No configuration or dependencies were introduced.

Physical webcam validation remains pending. Non-detection is distinct from poor
lighting, blur, stale input and camera failures; those remain unknown/unavailable
and do not contribute to the absence counter.


## Shared blur threshold — 2 November 2026

Implemented a shared minimum blur variance of 5 in application configuration and
`.env.example`. The gate remains active; below-threshold frames are unknown.
Existing local environment values override defaults. Brightness checks remain active.

Synthetic checks cover moderately detailed frames with variance between 5 and 15
reaching inference, flat frames being rejected and explicit blur thresholds.
Physical head-turning accuracy remains unverified; 5 is a tunable prototype value.

Activated `pomo`: the full backend suite passed **116 tests** in 4.50 seconds,
with the existing Starlette/HTTPX warning. `git diff --check` passed.


## Integrated camera and reminders — 4 November 2026

The `feature/states` merge combines camera commit `4f069c4` from `main` with
reminder commit `d3ebfef`. Earlier records above describe their separate branches;
the integrated protocol is v7. Combined checks are recorded below. Physical webcam, browser permissions/layout, audible output
and cross-platform accuracy are not established by unit or mocked-browser tests.

- `sh scripts/setup.sh`: passed with Conda 25.1.1 on macOS ARM64. The fallback
  filtered Linux-only native entries from a temporary copy of `environment.yml`;
  the existing `pomo` environment was updated with the pinned OpenCV/MediaPipe
  packages and the Face Landmarker model checksum verified. Local `.env` was not
  changed. Recent-Conda CEP-24 handling remains available; see earlier WSL records.
- `conda run --name pomo python -m pytest -q -o faulthandler_timeout=20`:
  **266 passed**, one existing Starlette/HTTPX deprecation warning. Coverage includes
  both original branches plus camera-to-reminder baseline/grace, cooldown, mute,
  stale-vs-transport timeouts, recovery, power, source gating, private tokens and
  rejected-result atomicity. Core timing tests use injected clocks.
- `node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs`:
  **32 passed**. Mocked-browser checks execute the production JavaScript and cover
  shared policy rendering, source switching, owner-only capture, diagnostics,
  permission/encoder/upload cancellation, audio fallback/deduplication and stale UI.
- `conda run --name pomo python -m pip check`: no broken requirements.
- `node --check simulator/app.js`, `node --check simulator/camera.js`,
  `sh -n scripts/setup.sh scripts/dev.sh` and `git diff --check`: passed.
- A temporary real server on `127.0.0.1:8767` loaded the actual model. HTTP health
  and all simulator assets returned 200; health reported protocol 7 and ready
  camera processing. Live JPEG HTTP uploads plus WebSocket owner/viewer snapshots
  passed: official public portrait -> stable baseline -> synthetic detailed noise
  with no face -> real reminder -> viewer restoration -> ID-based dismissal and
  cooldown -> black-frame low-light uncertainty -> shutdown/token invalidation ->
  wake -> simulated absence reminder -> pause. Test settings were 0.5 s absence,
  0.1 s grace, 0.1 s baseline and 0.5 s cooldown; shared defaults remain unchanged.
  The public source was `https://storage.googleapis.com/mediapipe-assets/portrait.jpg`.
  All images remained in memory; no personal camera input was acquired or stored.

Protocol 7 replaces both prior branch protocols. Raw camera observations retain
server monotonic timestamps; normalized policy observations use Unix receipt time
with processing age preserved. The live application has one reminder policy.
Any fresh presence clears a cue immediately; stable presence is the baseline for
subsequent camera absence. Camera grace precedes the shared absence threshold.
Physical camera permissions/accuracy, rendered desktop/narrow browser appearance,
actual audible output and new Windows/Linux installs remain unverified in this
integration run. Native model warnings and the existing test adapter warning did
not fail the checks.

## Camera startup diagnostics — 4 November 2026

A user reported successful HTTP assets/WebSocket connections followed by
`camera_started` and `camera_failed`, without a frame upload. A read-only request
to the running local `/health` endpoint confirmed protocol 7 and
`camera_processor_ready: true`. This establishes model readiness, not webcam
access or the user's exact browser failure.

A Node reproduction showed successful camera permission followed by a rejected
`video.play()` incorrectly reporting permission denial. Hidden-tab interruption
also lost its specific local reason after the next unavailable snapshot.
Capture, attachment, playback, encoding and upload now have separate messages;
the preview is explicitly muted/inline, hidden-tab reasons persist, and bounded
failure text appears in feedback and the connection journal. WebSocket schema and
backend behavior are unchanged. Static asset versions are camera v4/app v16.

- `node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs`:
  **39 passed**. Added regression coverage for playback denial after successful
  capture, attachment failure, late playback cancellation, missing canvas, empty
  or failed JPEG encoding, rejected fetch and hidden-tab interruption during
  permission and active capture. Cancellation still releases resources and reports
  one failure without logging native error details, images or session tokens.
- `node --check simulator/camera.js`, `node --check simulator/app.js` and
  `git diff --check`: passed.
- Backend code and protocol were unchanged, so Python tests were not repeated for
  this browser-only correction. The preceding integrated backend run remains
  recorded separately.

The actual user's camera access, preview, browser/OS permissions and playback
remain unverified pending the exact on-page error and a manual retry. This change
improves diagnosis; it does not establish that the no-video report is resolved.

## Expression identifier rename — 11 November 2026

On the `fix/camera` working tree with the existing Python 3.13 `pomo` environment:

- `conda run --no-capture-output --name pomo python -m pytest -q tests/test_policy.py tests/test_behaviour.py tests/test_config.py tests/test_eyes.py tests/test_perception.py`: 177 passed.
- `conda run --no-capture-output --name pomo python -m pytest -q` outside the sandbox: 268 passed, with the existing Starlette/HTTPX deprecation warning. Protocol coverage includes v8 commands and snapshots, all five previews, legacy-name rejection and observation-driven transitions without a physical camera.
- Both simulator JavaScript files compiled with V8's `Function` constructor; HTML preview/observation values and CSS selectors were checked, and `git diff --check` passed. Node.js is not installed, so the Node test suites and `node --check` were not run.
- Inside the sandbox Starlette's `TestClient` hung during initialization, including for an empty FastAPI app. Running the suite outside the sandbox completed successfully.
- A real browser, camera, narrow layout and audible output were not tested.

## Happy expression during camera tracking grace — 11 November 2026

- `conda run --no-capture-output --name pomo python -m pytest -q` outside the sandbox: 270 passed, with the existing Starlette/HTTPX deprecation warning.
- Synthetic camera frames and a controllable clock cover an armed face, tracking loss before and at the grace boundary, absence, return and uncertain input. The policy test covers observation freshness expiry. Raw `not_detected` and normalized `unknown` are retained during grace.
- `git diff --check` passed. A physical webcam and browser rendering were not tested.

## Visible camera detection description — 11 November 2026

- The actual simulator JavaScript was exercised in a V8 mocked DOM/WebSocket harness with ten synthetic camera scenarios and disconnection. Checks covered face presence, armed/unarmed tracking loss, absence and active reminder, low light and blur, stale data, camera startup and unavailable input.
- V8 compiled `simulator/app.js`, `simulator/camera.js` and `tests/test_simulator.cjs`. HTML checks confirmed that the live description follows the camera status outside collapsed details and retains `role=status`; `git diff --check` passed.
- Node.js is not installed, so the repository's Node test commands and `node --check` were not run. A browser, narrow layout and physical camera were not tested.
