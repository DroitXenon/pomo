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
