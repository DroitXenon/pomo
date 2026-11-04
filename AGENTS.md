# Instructions

These instructions apply to the whole repository. Apply any more specific repository instructions for the files being changed.

## Start Here

1. Read [README.md](README.md) for setup, scope and current behaviour. Read its phases and TODO section when present.
2. Run `git status --short --branch` and inspect existing changes. Preserve work made by the user or other contributors.
3. Read the relevant implementation and tests. For communication changes, also read [docs/protocol.md](docs/protocol.md); for dependency decisions, read [docs/stack.md](docs/stack.md).
4. Implement the requested task. A roadmap or TODO list is not an instruction to implement every remaining feature.

Use checked-in documentation and current code as shared context. Linked planning tools can provide additional context, but access to the original author's chat or private workspace is not required for ordinary development.

## Project Scope

Pomo is a desktop robot study companion. The software prototype uses a browser simulator and a Python backend; a physical robot will provide the interface later.

- **Phase 1: Set Up the Env.** Environment, repository structure, configurable connections, simulator and initial verification.
- **Phase 2: Add Basic Functions.** Camera input, presence observations, backend behaviour, robot expressions and reminders.
- **Phase 3: Test and Validate.** Detection evaluation, deterministic behaviour tests, recovery, usability and installation checks.
- Pomodoro/session controls and voice recognition are deferred. Implement them when requested as a separate task.

The current baseline provides manual display previews, browser webcam capture, bounded JPEG ingestion, camera ownership and a long-lived processing worker. Timestamped face observations and a sustained-absence reminder policy are implemented. Head direction and blendshapes are diagnostics only. Detection data does not select manual expressions or drive the robot face. Physical-camera validation and firmware remain pending. Verify this baseline against the code before making status claims, and update the documentation as implementation progresses.

The initial detection target is whether the user leaves the frame. Presence and head direction do not prove attention or distraction. Camera or connection failure must be represented as unavailable/unknown input rather than user absence.

## Environment and Commands

Use **Python 3.13 and the `pomo` Conda environment**. [environment.yml](environment.yml) is the dependency definition, including its pinned pip packages. Keep dependency changes there; do not recreate `requirements.txt` or introduce a second environment workflow.

Run from the repository root:

```sh
# Create/update the environment when needed.
sh scripts/setup.sh

# Start the simulator/backend with live logs.
sh scripts/dev.sh

# Run backend integration checks.
conda run --name pomo python -m pytest -q

# Check package consistency after dependency changes.
conda run --name pomo python -m pip check
```

For Windows or a terminal without `sh`, use the direct Conda commands in the README. Reuse an existing working environment; setup is needed when the environment is missing or dependencies change.

Defaults are `POMO_HOST=127.0.0.1`, `POMO_PORT=8000` and `POMO_DEV_CONTROLS=true`. Process environment variables override `.env`. Preserve existing local configuration. If a server is already running, use a free port for a temporary verification server and stop processes you started when finished.

## Code Boundaries

| Location | Responsibility |
| --- | --- |
| `backend/app.py` | FastAPI factory, command schema, shared state and WebSocket transport |
| `backend/__main__.py` | Configuration loading and server startup |
| `simulator/` | HTML/CSS/JavaScript display, controls and connection handling |
| `firmware/` | Physical integration notes; future hardware adapter |
| `tests/` | HTTP/WebSocket checks and future behaviour tests |
| `docs/` | Protocol, stack decisions and verification evidence |

Keep perception, behaviour policy, transport and rendering separate as Phase 2 develops. The backend owns state transitions and reminder decisions; the simulator renders backend state. Hardware support should reuse the same behaviour logic through an adapter.

Keep blocking camera capture or inference off the asynchronous request/WebSocket loop. Provide explicit lifecycle and cleanup for camera resources and background processing.

Use the existing Python/FastAPI and plain JavaScript patterns. The interface has no frontend build step. Add dependencies and architectural components only when needed for the requested task, and document the reason and validation.

## Protocol and State Rules

Preserve these contracts unless the requested task changes them. Update the backend, simulator, tests and protocol documentation together when changing a shared contract; version breaking protocol changes.

- `/` serves the simulator, `/health` reports service status and `/ws` transports JSON commands and snapshots on the same origin.
- Commands are strictly validated. Invalid input must not mutate state or crash the server.
- All clients currently share one in-memory robot state. Use one backend worker while state remains process-local.
- Each accepted command increments the revision and broadcasts a complete snapshot. New/reconnecting clients receive current state.
- Current display identifiers are `ready`, `possible_absence`, `reminding` and `unavailable`. Keep identifiers consistent across Python, JavaScript, tests and docs.
- Monitoring changes reset the display to `ready`; enabling reserves a browser camera session for the sending WebSocket. Manual expression previews can run while monitoring is paused when development controls are enabled.
- Manual previews are rendering controls, not detection observations or evidence of a triggered reminder.
- Controls remain disabled until a valid snapshot arrives. Disconnection marks displayed state stale; offline commands are not queued for replay.
- Keep connection health, camera availability, monitoring state and display state distinct.

## Simulator Design

Preserve the simple **black-and-white/grayscale interface with a dark background**. Prioritise the robot face, state label, monitoring control, connection status and expression controls. Keep connection diagnostics collapsed by default.

Avoid marketing copy, introductory hero sections, slogans and phase banners. Keep labels concise. Preserve keyboard focus indicators, semantic controls, accessible state announcements and responsive layout. When removing or renaming an HTML element, update its JavaScript hooks and CSS selectors together.

## Detection and Reminder Work

For Phase 2 changes:

- Make camera sources, duration thresholds configurable; document new settings in `.env.example` and the README.
- Keep frame previews and observation diagnostics in the development interface.
- Timestamp observations, reject stale input and handle uncertain results, temporary tracking loss and unavailable cameras explicitly.
- Pause/unavailable input must stop new detection-driven reminders. Resume with fresh observations and release camera resources on shutdown.
- Keep reminders supportive. Implement dismissal as backend behaviour; make optional sound independently muteable.
- Keep capture/processing local for the laptop prototype unless the task explicitly introduces browser capture or a remote transport.
- Keep camera images/video out of persistent storage, logs, commits and test fixtures by default. Prefer synthetic observations for automated tests.

## Validation

Match checks to the change:

- **Backend or protocol:** run the integration suite; add meaningful tests for new behaviour and regressions.
- **Detection/reminder policy:** use synthetic observations and a controllable clock for thresholds, dismissal, pause/resume and unavailable-input cases. Core logic tests must run without a physical camera or fixed timing sleeps.
- **Simulator:** check the changed controls, expressions, connection states and narrow layouts in a browser when available. If Node.js is available, `node --check simulator/app.js` checks JavaScript syntax; Node is not an application runtime requirement.
- **Scripts:** run `sh -n scripts/setup.sh scripts/dev.sh`; verify setup/startup when those paths change.
- **Dependencies:** verify environment setup/update, run `pip check` through Conda and run relevant tests.
- **Documentation only:** check accuracy, local links, commands and `git diff --check`; application tests are not required for prose-only edits.

Report the exact checks and outcomes. State when a camera, browser, operating system or deployment was not tested. The existing Starlette/HTTPX deprecation warning is documented; do not upgrade unrelated dependencies just to hide it.

## Team Workflow and Handoff

- Respect the task owner's branch choice. For new team work, prefer a focused short-lived branch such as `feature/camera-input` or `fix/reconnect-state`, with reviewed working changes integrated into `main`.
- Keep each change focused. Do not discard unrelated changes, rewrite shared history or force-push shared branches. Follow the task's authorised scope for commits, pushes, pull requests and merges.
- Update README progress/TODO items when work is implemented and verified. Keep planned features and completed work clearly labelled.
- Update `docs/protocol.md` for message changes, `.env.example` for configuration and `docs/verification.md` for new verification evidence. Retain the dates and context of older records.
- Keep `.env`, credentials, local environment directories and camera recordings out of version control.
- Finish with a concise summary of what changed, why, the checks performed and remaining limitations. Call out shared protocol/configuration changes that teammates need to adopt.