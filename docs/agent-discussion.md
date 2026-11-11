# Agent Discussion

Shared discussion space for Pomo teammates and their coding agents. Use it to exchange proposals, questions, replies, decisions and handoffs across separate chats and branches.

Project instructions live in [AGENTS.md](../AGENTS.md), implementation progress in [README.md](../README.md), and the current transport contract in [protocol.md](protocol.md). This discussion log complements those documents; proposals here do not automatically change the project contract or task scope.

## How to Participate

1. Read the relevant existing entries before starting a task or proposing a shared change. Check the branch and commits you are working from so you know which version of the discussion you have.
2. Append an entry using the template below. Identify the teammate you are working with and the agent/tool writing the entry. Use a descriptive ID such as `2026-10-31-alex-camera-observations`; author/topic-based IDs reduce collisions across branches.
3. Explain the idea or question, its reasoning and the affected files or interfaces. Separate observed behaviour from assumptions and proposed changes.
4. Reply by appending another entry and referencing the original ID. Preserve other contributors' words and the discussion history. Correct an earlier claim with a follow-up entry.
5. Record decisions with the actual decision maker or merged pull request as evidence. An agent proposal is not a team decision. Continue implementation within the task owner's requested scope.
6. When an agreed change is implemented, update the relevant code, tests and canonical documentation through the normal task workflow. Add a short follow-up linking the result and any remaining work.

Keep entries concise and relevant to Pomo. Include repository paths, commit IDs, test results or pull-request links when they support the discussion. Keep credentials, private `.env` values and camera images/video out of this file.

## Sharing Through Git

This is an asynchronous Git discussion log. A local edit becomes available to teammates after it is committed, pushed and brought into their checkout. It does not send notifications or messages to another agent automatically.

- Add discussion entries on the branch used for the task and share them through the team's normal commit/pull-request workflow.
- Merge discussion updates into the shared branch promptly when they affect other work. Teammates then update their checkout before relying on those entries.
- Respect existing local changes when updating a branch. Do not discard work or rewrite shared history to synchronise this file.
- When branches add entries concurrently, keep both entries during conflict resolution. Avoid editing the same existing entry from multiple branches.
- Follow the task owner's authorised scope for committing, pushing or merging. Writing an entry does not itself authorise publishing changes.

## Entry Template

Copy this template to the end of the discussion log and replace the placeholders. Leave the template itself available for the next contributor.

```markdown
### YYYY-MM-DD-author-short-topic

- Date: YYYY-MM-DD HH:MM UTC-offset
- Author: <teammate name> / <agent or tool>
- Type: Proposal | Question | Reply | Decision | Handoff
- Related entries: <entry IDs, or none>
- Context: <task, branch/commit and relevant repository files>

**Idea or response:**
<What you propose, need to know, or want to tell another contributor.>

**Reasoning and evidence:**
<Observed behaviour, alternatives, tradeoffs and any checks performed.>

**Next step:**
<A concrete action or question; identify an agreed owner or leave it unassigned.>

**Decision evidence, if applicable:**
<Who made the decision or which merged PR records it; omit for open proposals.>
```

## Starting Topics

These are open questions from the current Phase 2 roadmap, not agreed implementation decisions:

- What camera-to-backend observation format should carry presence, timestamp and camera availability?
- Which configurable absence durations and reminder cooldowns should be evaluated, and how will simulated observations test them?
- How should camera, backend behaviour and simulator work be divided while keeping state transitions in the backend?

## Discussion Log

Append new entries below this line; replies should reference the entry they address.

### 2026-10-31-pomo-agent-states-reminders-handoff

- Date: 2026-10-31 16:09 UTC+00:00
- Author: Pomo task owner's agent / Codex
- Type: Handoff
- Related entries: none
- Context: `agent/feature/states`; `backend/policy.py`, `backend/app.py`,
  `backend/config.py`, `simulator/`, `docs/protocol.md` and the three linked
  Notion task specifications in that protocol document.

**Idea or response:**
The states/reminder/debug-log implementation is ready for review. The backend
owns all five states and reminder decisions. The simulator sends synthetic
observation metadata and offers shared monitoring, soft power, mute and dismissal.
Camera capture/perception remains a separate teammate task.

**Reasoning and evidence:**
Protocol v2 documents the complete ingestion contract. Camera producers should
connect to `/ws`, read the current observation-session token, send fresh strictly
increasing Unix timestamps and receive updated tokens after lifecycle changes.
Prefer one active producer. `source: "camera"` is a metadata label, not a camera
implementation or authenticated identity. Do not upload images/video.

Default timings are 5 s absence, 30 s cooldown and 3 s observation timeout, all
configurable. Dismissal guarantees a full quiet period; pause, return and lost
input preserve cooldown. Soft power-off resets it. These are implementation
defaults for validation, not a claim that the team has approved optimal timings.

137 Python cases and seven mocked-browser JavaScript cases pass. A real
HTTP/WebSocket smoke check passed the observation → reminder → dismissal →
cooldown → recovery flow. [Verification records](verification.md) distinguish
these checks from the browser/audible and real-camera checks still needed.

**Next step:**
Camera/perception contributor: integrate fresh metadata using the producer
contract and test unavailable-input recovery. Team reviewers: review protocol v2,
run the manual simulator/audio check, evaluate timings and record any proposed
contract changes here before coordinating implementation.

### 2026-11-04-pomo-camera-reminders-integration

- Date: 2026-11-04 16:22 UTC+00:00
- Author: Pomo task owner's agent / Codex
- Type: Handoff
- Related entries: 2026-10-31-pomo-agent-states-reminders-handoff
- Context: `feature/states`; merge of reminder commit `d3ebfef` and camera merge
  `4f069c4` from `main`; `backend/app.py`, `backend/config.py`, `simulator/` and
  [protocol v7](protocol.md).

**Idea or response:**
The task owner requested resolution of the in-progress merge while preserving
camera detection, reminders, states and debug logs. Both inputs now use one
`ReminderEngine`. Browser camera capture, JPEG processing, quality gates and
head/eye diagnostics are retained; explicit Camera/Simulated input modes share
monitoring, soft power, visual cues, mute, dismissal, cooldown and bounded logs.

**Reasoning and evidence:**
Protocol 7 supersedes the incompatible v2 and v6 branch contracts. Camera upload
tokens stay owner-only. `camera_capture_status` describes capture, `camera_status`
normalized input availability, `camera_observation` raw diagnostics and
`observation` normalized policy input. Camera mode requires a stable visible-face
baseline and tracking-loss grace before qualifying absence. The raw no-face
counter remains available before arming. Head/eye/mouth values do not remind.
A fresh present result immediately clears the cue; stable presence arms subsequent
camera absence. Manual previews require powered-on, paused monitoring.

The shared absence threshold remains 5 seconds, after the camera's default 1-second
grace; stable baseline is 0.5 seconds, cooldown 30 seconds, camera evidence freshness
1 second and capture idle timeout 3 seconds. Existing local settings still override
these defaults. Startup also requires grace <= absence <= 3600 seconds.

266 Python tests and 32 mocked-browser JavaScript tests pass. The real model and
live HTTP/WebSocket pipeline passed portrait baseline, synthetic no-face reminder,
viewer recovery, dismissal, low-light uncertainty, power cleanup, simulation and
pause. Setup/model checksum and package consistency passed on this Mac. See
[verification records](verification.md) for exact commands and physical/browser
limits. The previous standalone `backend/behaviour.py` remains for regression
history; it is not a second policy running in the app.

**Next step:**
Review and integrate the tested merge through the normal Git workflow. All
teammates must update backend and simulator together for protocol 7 and update the
`pomo` environment using `sh scripts/setup.sh`. Manually check real webcam
permissions/lifecycle, narrow layout, audible sound and false reminders before
claiming physical-camera accuracy. Experimental eye/mouth diagnostics are not
completed calibrated detection features.

### 2026-11-04-pomo-camera-startup-diagnostics

- Date: 2026-11-04 17:09 UTC+00:00
- Author: Pomo task owner's agent / Codex
- Type: Reply
- Related entries: 2026-11-04-pomo-camera-reminders-integration
- Context: No-video report on protocol 7; `simulator/camera.js`, `simulator/app.js`,
  camera/browser tests and README troubleshooting.

**Idea or response:**
The running backend reports ready camera processing, while the reported browser
attempts fail before a JPEG request reaches the server. That alone does not prove
permission denial: capture, playback, frame preparation and tab hiding can fail
before upload. The user's browser/address/exact on-page reason were requested.

**Reasoning and evidence:**
A mock reproduction confirmed that playback rejection was mislabelled camera
permission denial. Capture/playback/encoding/upload now have distinct bounded
messages; hidden-tab interruptions keep their reason after unavailable snapshots.
Camera failure text is copied to feedback and the connection journal without
images, tokens or arbitrary native-error details. All 39 Node checks and both
production JavaScript syntax checks pass; backend/protocol are unchanged.

**Next step:**
Reload the updated camera v4/app v16 client, keep the owner tab visible, check
browser and OS camera settings and retry. Obtain the exact on-page failure before
claiming the physical-camera issue is fixed. Preserve the other contributor's
concurrent `a705dba` commit; remaining test/diagnostic edits are separate local work.

### 2026-11-11-pomo-cores3-display-test

- Date: 2026-11-11 16:19 UTC+00:00
- Author: Pomo task owner's agent / Codex
- Type: Handoff
- Related entries: 2026-11-04-pomo-camera-reminders-integration
- Context: `feature/stack`; `firmware/pomostack/platformio.ini` and `src/main.cpp`.

**Idea or response:**
The existing PlatformIO project now initializes M5Unified and draws a static
black-and-white face. It preserves the CoreS3 board selection and adds the
M5Unified dependency. It does not control Pomo's backend or camera.

**Reasoning and evidence:**
The CoreS3 PlatformIO build succeeded with M5Unified and M5GFX 0.3.0. The
firmware was not uploaded and the physical screen has not been verified.

**Next step:**
Upload the display test, confirm its appearance on the device, then separately
plan camera capture and the USB/backend adapter. Follow the existing protocol's
camera ownership rules; do not send camera frames in WebSocket commands.

### 2026-11-11-pomo-cores3-camera-test

- Date: 2026-11-11 16:39 UTC+00:00
- Author: Pomo task owner's agent / Codex
- Type: Handoff
- Related entries: 2026-11-11-pomo-cores3-display-test
- Context: `feature/stack`; standalone `firmware/camera-test` project.

**Idea or response:**
The task owner confirmed the face appeared on the device and requested a camera
test. The new sketch previews CoreS3 camera frames on the device screen without
saving them or connecting to the backend. The existing face project remains
separate; uploading either project replaces the program on the device.

**Reasoning and evidence:**
The PlatformIO camera build passed. The sketch releases the internal I2C driver
before camera initialization and avoids polling shared-bus peripherals during
preview. Physical camera capture, colors, orientation and stability have not
yet been tested. See [verification records](verification.md).

**Next step:**
Upload the camera test and check the preview and serial diagnostics on the
CoreS3. Upload `firmware/pomostack` again to restore the face. Plan backend
integration separately after the camera test works.

### 2026-11-11-pomo-expression-identifiers

- Date: 2026-11-11 16:21 UTC+00:00
- Author: Pomo task owner / Codex
- Type: Handoff
- Related entries: 2026-11-04-pomo-camera-reminders-integration
- Context: `fix/camera` working tree; backend, simulator, tests and protocol v8.

**Idea or response:**
The task owner requested five renamed expressions. Both `behavior_state` and
`display` now use `happy`, `sad`, `surprised`, `bored` and `idle`; camera and
observation availability identifiers are unchanged. Protocol v8 requires matching
backend and simulator versions.

**Reasoning and evidence:**
Existing expressions and reminder thresholds keep their previous mapping. The
full Python suite passed outside the sandbox (268 tests). TestClient hung inside
the sandbox even for an empty FastAPI app. See `docs/verification.md` for exact
checks and limits.

**Next step:**
Teammates should update both clients and backend together, then run the Node
suites and check browser rendering and camera behavior.

### 2026-11-11-pomo-happy-tracking-grace

- Date: 2026-11-11 UTC+00:00
- Author: Pomo task owner / Codex
- Type: Handoff
- Related entries: 2026-11-04-pomo-camera-reminders-integration, 2026-11-11-pomo-expression-identifiers
- Context: `fix/camera` working tree; camera adapter, policy and protocol v8.

**Idea or response:**
At the task owner's request, an armed camera that briefly loses face tracking
shows `happy` during the configured grace. The raw observation remains
`not_detected` and normalized presence remains `unknown`; after grace, the
existing absence threshold and reminder rules apply. Unarmed and uncertain or
unavailable input still show `bored`.

**Reasoning and evidence:**
The Python suite passed outside the sandbox with 270 tests, including synthetic
clock-controlled checks at the grace boundary and observation expiry. Physical
camera and browser testing remain pending; see `docs/verification.md`.

**Next step:**
Teammates should use the updated protocol guidance when interpreting `unknown`
observations and verify the display with a real camera.

### 2026-11-11-pomo-visible-camera-description

- Date: 2026-11-11 UTC+00:00
- Author: Pomo task owner / Codex
- Type: Handoff
- Related entries: 2026-11-04-pomo-camera-startup-diagnostics, 2026-11-11-pomo-happy-tracking-grace
- Context: `fix/camera` working tree; simulator camera status and diagnostics.

**Idea or response:**
The task owner requested an explanation beneath the camera status. The existing
detection-status element is now visible there and describes tracking, image
quality and reminders; detailed diagnostics remain collapsible.

**Reasoning and evidence:**
A V8 mocked frontend check covered ten camera conditions and disconnect; see
`docs/verification.md`. Backend messages and camera capture are unchanged.

**Next step:**
Check the layout and status changes in a browser with a real camera; run the
repository's Node tests where Node.js is available.
