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
