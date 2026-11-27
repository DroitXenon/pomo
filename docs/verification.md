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

## CoreS3 static display build — 11 November 2026

The standalone `firmware/pomostack` PlatformIO sketch initializes M5Unified and
renders a static black-and-white face. `pio run -d firmware/pomostack` succeeded
on macOS with PlatformIO Core 6.2.0, Espressif32 6.9.0, M5Unified 0.3.0 and
M5GFX 0.3.0. No upload was performed. Physical display rendering and USB
communication remain unverified; camera capture and the backend adapter are not
implemented by this sketch.

## CoreS3 standalone camera preview — 11 November 2026

The user subsequently confirmed the static face appeared on the CoreS3. A
separate `firmware/camera-test` project now builds a local camera preview.

- `/Users/droitxenon/.platformio/penv/bin/pio run -d firmware/camera-test`:
  passed on macOS with Espressif32 6.9.0, M5Unified 0.3.0 and M5GFX 0.3.0.
- This camera sketch was not uploaded or tested on physical hardware. Camera
  capture, frame colors, orientation and stability remain to be verified on the
  device. It does not record frames or connect to the Pomo backend.

The user later reported that the camera preview works on the CoreS3. Colors,
orientation and stability were not separately assessed in this merge.

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

### 2026-11-11: Sustained uncertainty policy

Synthetic clock tests verify that fresh uncertain input displays happy, becomes absent after five seconds, can trigger the normal absence reminder, and clears on present input. `tests/test_policy.py`, `tests/test_perception.py`, `tests/test_eyes.py`, `tests/test_config.py`, and `tests/test_behaviour.py`: 179 passed in the `pomo` environment. The HTTP/WebSocket suite stalled while entering Starlette TestClient before a test ran; browser, Node.js (not installed), and physical camera validation were not completed.

### 2026-11-11: Expression while monitoring is paused

Synthetic policy and ASGI/WebSocket expression checks cover startup, pause, wake and manual previews. The policy, expression protocol, perception, eyes, configuration and historical behaviour suites passed: 181 tests. Browser and physical-camera checks were not run.

### 2026-11-11: One-second uncertainty threshold

Fake-clock policy checks cover the 0.999/1.000-second boundary, subsequent reminder timing, recovery and configuration overrides. The policy, expression protocol, perception, eyes, configuration and historical behaviour suites passed: 188 tests. Camera integration, browser and physical-camera checks were not run; the earlier TestClient startup stall remains unresolved.

## Merge main into feature/stack — 11 November 2026

- `PYTHONDONTWRITEBYTECODE=1 conda run --no-capture-output --name pomo python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=20`: 279 passed, with the existing Starlette/HTTPX deprecation warning.
- `node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs`: 42 passed. `node --check simulator/app.js` and `node --check simulator/camera.js` also passed.
- Browser rendering and physical hardware were not tested during this merge. The user previously reported the CoreS3 camera preview works.

## Proposal reminder sequence (protocol 10) — 24 November 2026

- Fake-clock policy tests cover surprised before the first reminder; the first reminder at 10 s measured from the first lost face; the second at +300 s with a new ID; standby at +600 s with no further reminders; return from each stage, including after standby; return-latency log messages; dismissal keeping the schedule; cooldown spacing between departures; and the new configuration validation.
- `conda run --name pomo python -m pytest -q -p no:cacheprovider`: 281 passed, with the existing Starlette/HTTPX deprecation warning.
- `node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs`: 43 passed, including a stubbed `speechSynthesis` check that each new reminder ID is spoken once and that clearing or muting cancels speech. `node --check simulator/app.js` passed.
- A live server on port 8011 (`POMO_ABSENCE_SECONDS=3`, `POMO_REMINDER_REPEAT_SECONDS=4`, `POMO_STANDBY_SECONDS=8`) was driven with simulated observations over WebSocket. Displays went happy → surprised (0.6 s) → sad, stage 1 (3.6 s) → sad, stage 2 (7.7 s) → bored standby (11.7 s) → happy on return. The server log showed `departure_detected`, `reminder_triggered` (first, second), `standby_entered` and `user_returned ... after standby`. The server was stopped afterwards.
- Browser speech output, rendering of the crying face, a physical camera and the CoreS3 were not tested.

## CoreS3 serial adapter (code only) — 24 November 2026

- `tests/test_hardware.py` uses a fake serial port and clock. It checks the compact message, latest-value queueing, duplicate suppression, the unavailable device and retry, write failure and reconnect, the 2-second heartbeat, thread start and close releasing the port, app broadcasts reaching the adapter (an adapter exception does not break broadcasts) and `POMO_SERIAL_PORT`/`POMO_SERIAL_BAUDRATE` validation.
- `pyserial==3.5` added to `environment.yml`; it was already present in the `pomo` environment. `conda run --name pomo python -m pip check`: no broken requirements.
- Full suite: 290 passed, with the existing Starlette/HTTPX deprecation warning.
- `pio run` in `firmware/robot-adapter` built for `m5stack-cores3` without warnings in the sketch (RAM 7.2%, flash 8.3%).
- The firmware was not uploaded. Rendering, the chime, USB serial with a real device, reconnection after unplugging and the study viewing distance remain untested.

## CoreS3 speaker — 24 November 2026

- The two reminder sentences were recorded with macOS `say` (voice "Flo (English (UK))") into 16 kHz mono WAV clips in `firmware/robot-adapter/include/clips.h`, generated from `REMINDER_MESSAGES`. A pytest check fails if the clips no longer match the text.
- `pio run` built the firmware without warnings in the sketch (flash 11.9%).
- New checks: the snapshot reports `robot_display` (`disabled`, `unavailable`, `connected`); while connected the simulator neither speaks nor plays its tone, but still shows the visual reminder and dismissal. Python: 292 passed. Node: 44 passed.

## CoreS3 robot camera — 24 November 2026

- Tests use a fake serial port and synthetic JPEGs; no camera images are stored. They cover frame parsing with noise, partial reads and oversized lengths; the boot line being logged; robot frames driving the engine through the `/camera/frame` checks; the robot token never reaching browsers; serial loss marking the camera unavailable; rejection without a configured or connected robot; and the simulator and camera client never starting browser capture in robot mode. Python: 297 passed. Node: 46 passed.
- On the connected CoreS3, the first firmware (default USB-Serial-JTAG driver) delivered about 1.5 frames per second and most frames were corrupted. The cause is that driver in Arduino-ESP32 2.0.17 discarding bytes. After switching the sketch to TinyUSB CDC, a 90-second stream gave 450 intact 320x240 frames (5.0 per second) with no disconnects.
- Both reminder clips were played while streaming; frames continued at about 5 per second, with no restart.
- A 45-second run through the backend (Robot camera input, monitoring on) processed 225 frames. The display moved through happy, surprised and sad as the face detector reported presence and absence. During one earlier 10-second run the robot restarted once; the cause was not identified, and it did not happen again in later runs.
- Uploads with the 1200-baud touch left the board in its ROM bootloader. `tools/after_upload.py` now clears the force-download flag and resets the board; one upload was confirmed.
- Detection accuracy with the robot camera at the study distance, lighting variation and long sessions have not been evaluated.

## Page layout and session log — 24 November 2026

- Removed "Simulator" from the page title and header. The robot and controls panels are unchanged; debug logs moved into a full-width Session log at the bottom of the page. It has a session summary, filters, search, a Connection tab and TSV export, and keeps up to 2,000 events per backend run in the tab.
- `node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs`: 47 passed, including a new test for history beyond the backend window, filters, search, summary, tabs, clearing and backend restart. `node --check` passed for both scripts.
- The page content is up to 1,600 pixels wide, and the top panels match the log's width. On desktop windows (at least 701 x 600 pixels) the page fits the window without page scrolling. The top row is 280–360 pixels tall (36% of the window height); the robot panel shows the face beside its controls; the controls panel has two columns at 1,101 pixels and wider; the log fills the remaining height. Panels scroll inside when needed (the controls panel at shorter heights, the robot panel while a reminder or error is shown). Measured in headless Chrome at 1600x1000, 1440x800, 1280x720 and 1024x768: no page scrolling. On phones the panels stack and the page scrolls normally. A drag handle between the top row and the log sets the split (remembered in browser storage, reset by double-click or Enter). In headless Chrome at 1280x720, 1440x800 and 1600x1000, keyboard resizing to both limits and resetting never caused page scrolling; the top row keeps at least 160 pixels and the log at least 300. Mouse dragging was not tested in a real browser.
- Headless Chrome (local server with simulated input) rendered the layout at 1400 and 1600 pixels wide. Measured inside an iframe, the page had no horizontal overflow at 390 or 1024 pixels wide. Export was not clicked in a real browser.

## Robot weather and clock pages — 27 November 2026

- Added swipeable face, weather and clock pages to `firmware/robot-adapter`. `backend/weather.py` fetches Open-Meteo weather (London by default, configurable with `POMO_WEATHER_*`). `SerialDisplay` adds `time` and the weather fields to every serial line. The WebSocket protocol is unchanged (v10), and the serial message is still `v:1` because the new fields are additive.
- `conda run --name pomo python -m pytest -q`: 313 passed. New tests cover weather parsing, WMO code mapping, failure handling in the refresh loop, settings validation, and serial lines carrying time and weather without defeating de-duplication. No network is used in tests.
- One live Open-Meteo request for London returned `{'wt': 4, 'wh': 4, 'wl': 2, 'wc': 'cloudy'}`.
- `pio run` in `firmware/robot-adapter` succeeded (RAM 14.6%, flash 13.5%).
- Not yet tested on the device: swipe detection, reading the FT6336 touch controller through the camera's I2C driver while frames stream, page rendering, and auto-return to the face. If touch reads conflict with the camera, the fallback is to allow swiping only while the camera is not streaming.
- Added a music page (the fourth page): tap to play or stop. It plays the original "Pomo Theme" tune, or audio converted by `tools/make_music.py` into the gitignored `include/music_user.h`. A reminder stops the music and mute prevents it. `pio run` succeeded both with the tune (flash 13.5%) and with a generated 15 s test tone converted from MP3 (flash 20.8%). The test header was removed afterwards. Playback, tapping and the speaker channel split were not tested on the device.
- Added a video page (the fifth page): tap to play or stop. It loops the original "Pomo Dance" animation drawn in code, or JPEG frames converted by `tools/make_video.py` into the gitignored `include/video_user.h`. `--audio` also converts the soundtrack into `music_user.h`. `pio run` succeeded in three cases: the built-in animation; a generated 6 s test GIF (60 frames at 10 fps, 320x180, 0.32 MB); and a 5 s generated test video with a sine soundtrack. The test headers were removed afterwards. Playback speed, touch and audio sync were not tested on the device.

## Robot Pomodoro timer page — 27 November 2026

- Added a timer page (second page, before weather) to `firmware/robot-adapter`. Tap to start or pause, hold to reset. Focus is followed automatically by a short or long break, and the next focus waits for a tap. A chime marks each change, respecting mute and never playing over a reminder. The face page shows a countdown while the timer runs. Durations come from the new `POMO_TIMER_*` settings, sent as `pf`/`ps`/`pl`/`pn` on each serial line. The WebSocket protocol and the reminder policy are unchanged.
- `conda run --name pomo python -m pytest -q`: 320 passed, including tests for the timer fields on serial lines and for settings validation. `pio run` succeeded. Not yet tested on the device.
