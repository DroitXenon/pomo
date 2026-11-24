# Protocol v10

The backend serves the simulator at `/`, reports health at `/health` and accepts WebSocket connections at `/ws` on the same origin. Use `ws` for HTTP and `wss` for HTTPS.

Version 10 adds the `robot` input source (the CoreS3 camera over USB serial) and adopts the team proposal's reminder sequence: `surprised` while the user has just left, `sad` (crying) with a spoken first reminder, a second reminder, then `bored` standby. It adds `standby`, `next_step_seconds`, `reminder.stage` and the `repeat_seconds`/`standby_seconds` settings, and new debug event kinds for study timing. Display identifiers and commands are unchanged, but the meaning of `sad` and `surprised` changed, so firmware and simulator must be updated together; v9 and earlier clients are incompatible.

Version 9 unified presence values as `present`, `absent`, `uncertain` and `unavailable`. `camera_observation.presence` and `observation.presence` are the same shared value in every snapshot.

`GET /health` returns:

```json
{"status":"ok","phase":2,"protocol_version":10,"camera_processor_ready":true}
```

## Transport and State Ownership

Messages are JSON text. The startup configuration limits incoming WebSocket messages to 4,096 bytes; the application also rejects binary messages, oversized command text, malformed JSON, unknown types, extra fields and incorrect field types.

Every connected client controls the same in-memory robot. Backend operations and broadcasts are serialised. Use one backend worker while state remains process-local; state, cooldowns, reminder IDs and events are not persisted across backend restarts.

Camera capture has one owner: the WebSocket that enabled monitoring in camera mode.
Only that peer receives `camera_session`; viewers receive null. Any client can pause
shared monitoring, power off or dismiss a current reminder. In simulated mode the
last accepted observation producer owns that input; its loss invalidates it. Viewer
loss does not clear another source. A failed send is treated as disconnection.

This development server has no authentication. Use localhost or private workspace
access controls. Browser capture is intended for a browser and backend on the same
laptop; a remote backend receives the uploaded frames. Frames stay in memory and
are never put in WebSocket snapshots, logs or persistent storage.

## Complete State Snapshot

A client receives the current complete snapshot on connection. Every accepted command broadcasts a new snapshot to all clients. The 250 ms backend timer also publishes changes to policy state, elapsed-time diagnostics and debug events.

The following example shows the complete shape; instance/session IDs, revision and event contents vary:

```json
{
  "type": "state",
  "protocol_version": 10,
  "instance_id": "6fe3ecf8-69bc-468d-b690-5dc162dc9393",
  "revision": 0,
  "dev_controls": true,
  "powered_on": true,
  "monitoring_enabled": false,
  "muted": true,
  "behavior_state": "bored",
  "display": "bored",
  "preview_active": false,
  "camera_status": "unavailable",
  "observation_session": "fece9f0ba618451ea17e8ef3ab8dafde",
  "observation": {
    "presence": "unavailable",
    "source": "none",
    "observed_at": null,
    "age_seconds": null
  },
  "absence_duration_seconds": 0.0,
  "cooldown_remaining_seconds": 0.0,
  "standby": false,
  "next_step_seconds": null,
  "reminder": {
    "active": false,
    "id": 0,
    "stage": 0,
    "message": null
  },
  "settings": {
    "absence_seconds": 10.0,
    "cooldown_seconds": 0.0,
    "observation_timeout_seconds": 3.0,
    "uncertainty_seconds": 1.0,
    "repeat_seconds": 300.0,
    "standby_seconds": 600.0
  },
  "events": [],
  "input_source": "camera",
  "robot_display": "disabled",
  "camera_session": null,
  "camera_processor_ready": true,
  "camera_capture_status": "paused",
  "camera_settings": {
    "width": 640, "height": 480, "fps": 10, "jpeg_quality": 0.75,
    "max_bytes": 524288, "timeout_seconds": 3, "startup_seconds": 30
  },
  "frames_received": 0,
  "last_frame": null,
  "camera_observation": {"presence": "unavailable", "reason": "no_camera_data"},
  "head_direction": "unknown",
  "camera_armed": false,
  "camera_tracking_status": "paused",
  "camera_absence_duration_seconds": 0.0
}
```

| Field | Meaning |
| --- | --- |
| `instance_id` | Identifies this backend application instance; changes on restart |
| `revision` | Increments for accepted commands and subsequent published state/diagnostic changes; it is not a command-only counter |
| `behavior_state` | Actual policy state: `happy`, `idle`, `sad`, `surprised` or `bored` |
| `display` | Rendered expression; equals behaviour unless a manual preview is active |
| `preview_active` | Whether a development expression preview is overriding rendering |
| `camera_status` | `available` or `unavailable`, independently of WebSocket connection status |
| `observation.presence` | `present`, `absent`, `uncertain` or `unavailable` |
| `observation.source` | `none`, `simulated` or `camera` |
| `observation.observed_at` | Last accepted source timestamp, in Unix seconds, or `null` |
| `observation.age_seconds` | Source age on receipt plus subsequent monotonic elapsed time, or `null` |
| `observation_session` | Opaque token producers must copy from the latest snapshot |
| `absence_duration_seconds` | Time since the user left, including the initial uncertainty; resets on recovery, unavailable input, pause or input gaps |
| `cooldown_remaining_seconds` | Remaining quiet period, clamped to zero |
| `robot_display` | `disabled` (no `POMO_SERIAL_PORT`), `connected` (serial port open) or `unavailable`. While `connected`, the robot speaks reminders and the browser stays silent |
| `standby` | True after `standby_seconds` without return; display `bored`, no further reminders until the user returns |
| `next_step_seconds` | Seconds until the next first/second reminder or standby, or `null` |
| `reminder.stage` | `0` none, `1` first reminder, `2` second reminder; resets when the departure ends |
| `reminder.id` | Counter increased only when a real reminder is triggered; use with `instance_id` to identify a cue |
| `reminder.active` / `message` | Whether a real visual reminder is active and its supportive text; message is `null` when inactive |
| `events` | Up to 100 recent backend events in oldest-to-newest order |

Connection status is a client-side transport condition. It must not be interpreted as user absence. A camera can be available while tracking is uncertain; fresh `uncertain` observations show `happy` and become `absent` after the configured uncertainty period (default 1 second).

Additional camera fields are:

| Field | Meaning |
| --- | --- |
| `input_source` | `camera` by default, or explicitly selected `simulated` |
| `camera_session` | Opaque upload token only visible to its owning WebSocket |
| `camera_processor_ready` | Whether model initialization succeeded; simulation can work when false |
| `camera_capture_status` | Capture/transport: `paused`, `starting`, `available`, `unavailable` |
| `camera_observation` | Shared current `presence` with camera diagnostics when available; its presence equals `observation.presence` in every snapshot |
| `head_direction` | Camera-relative `forward`, `left`, `right`, `up`, `down` or `unknown` |
| `camera_armed` | Whether stable visible-face evidence permits camera absence reminders |
| `camera_tracking_status` | Baseline/grace/quality diagnostic, separate from actual `behavior_state` |
| `camera_absence_duration_seconds` | Raw continuous non-detection interval, including before arming |
| `frames_received`, `last_frame` | Accepted frame count and dimensions/sequence, never pixels |

`camera_status` retains the policy input availability meaning from v2;
`camera_capture_status` holds the browser capture meaning formerly named
`camera_status` in v6. `observation` is the policy input; `camera_observation.presence` is the same
normalized value and camera diagnostic fields provide the reason and measurements.
When no camera diagnostics are retained, a placeholder with the shared presence
and `no_camera_data` reason is exposed. Presence values remain distinct from camera availability and
connection health.

## Strict Commands

Booleans must be JSON booleans, not strings or numbers. Commands accept only the fields shown.

### Input source

```json
{"type":"set_input_source","source":"camera"}
{"type":"set_input_source","source":"simulated"}
{"type":"set_input_source","source":"robot"}
```

`robot` uses the CoreS3 camera through the serial adapter (see "Robot Display Serial") and is rejected when `POMO_SERIAL_PORT` is not configured. Enabling monitoring in robot mode requires `robot_display` to be `connected`. The robot session has no browser owner: every peer receives `camera_session: null`, and frames go through the same checks, size limit, processor and presence normalisation as `/camera/frame`. Timeouts work as for the browser camera, and losing the serial link marks the camera unavailable; pause and enable monitoring (or Retry camera) to start again.

Source changes require power on and monitoring paused. Simulated mode requires
development controls. Source changes discard input and rotate observation tokens.
Camera mode is the default. Enable monitoring to reserve a capture session; the
owner starts browser capture after receiving its token. An unavailable processor
rejects camera enable without preventing simulated operation. Camera input cannot
be replaced by a synthetic packet while camera mode is selected.

### Monitoring and power

```json
{"type":"set_monitoring","enabled":true}
{"type":"set_monitoring","enabled":false}
{"type":"set_power","enabled":false}
{"type":"set_power","enabled":true}
```

- Enabling monitoring requires power on. An actual monitoring change clears the preview, input and active reminder, rotates the observation-session token and requires fresh observations.
- Pausing monitoring returns behaviour to `bored`, ends any departure and preserves any remaining cooldown.
- `set_power` is a soft power control. Power off enters `idle`, disables monitoring and clears input, preview, active reminder and cooldown. It does not terminate HTTP or WebSocket serving.
- Power on returns to `bored` with monitoring paused. Repeating an unchanged power or monitoring setting is idempotent at policy level, although an accepted command still receives a new revision.

### Sound and dismissal

```json
{"type":"set_muted","muted":false}
{"type":"set_muted","muted":true}
{"type":"dismiss_reminder","reminder_id":1}
```

Mute is a shared preference. It does not change reminder IDs or trigger a new reminder. The browser needs a user gesture to unlock its local audio context; visual reminders work when audio is unavailable.

Dismissal requires a strict positive integer matching the currently active reminder. A stale or inactive ID is rejected. Dismissal silences the current cue and hides its message; the face stays `sad`, and the second reminder and standby schedule continue. It also extends any configured cooldown to `max(existing_deadline, dismissal_time + cooldown)`.

### Development expression previews

```json
{"type":"preview_display","display":"sad"}
{"type":"clear_preview"}
```

Preview accepts any of the five display identifiers. It requires power on, monitoring paused and development controls enabled. It changes rendering only: previewing `surprised` does not activate a real reminder, increment its ID or play a sound; previewing `idle` does not power off the backend policy.

### Simulated observation ingestion

```json
{
  "type": "submit_observation",
  "presence": "absent",
  "source": "simulated",
  "observed_at": 1793458800.25,
  "session_id": "fece9f0ba618451ea17e8ef3ab8dafde"
}
```

Replace the illustrative timestamp with the actual observation time and the token with the latest `observation_session`.

- `presence`: `present`, `absent`, `uncertain` or `unavailable`.
- `source`: `simulated`; camera observations arrive through the frame adapter.
- `observed_at`: a finite JSON number in Unix seconds.
- `session_id`: a non-empty string of at most 100 characters, matching the current session.
- Observations require power on, monitoring enabled and simulated input selected.
- Source timestamps must be strictly newer than the previous accepted timestamp in the session, including when changing source.
- At receipt, an observation must be younger than `observation_timeout_seconds` and no more than one second in the future. Age equal to the timeout is already expired.
- Freshness after receipt uses a monotonic clock and includes the age the observation already had at receipt.

With `POMO_DEV_CONTROLS=false`, simulated input selection/observations and both preview commands are rejected. Browser camera monitoring, power, mute and dismissal remain available. Camera input is accepted only through the session-scoped HTTP adapter.

## Reminder and Recovery Semantics

| Input or action | Result |
| --- | --- |
| Monitoring enabled without valid input | `bored`; no reminder |
| Fresh `present` | `happy`; end the departure, clear the reminder sequence and log `user_returned` with latency; retain cooldown |
| Fresh `absent` | `surprised`; start/continue the departure window and log `departure_detected` |
| `absence_seconds` after leaving, fresh input, cooldown ended | First reminder (`stage` 1): `sad`, new reminder ID, message and spoken cue |
| `repeat_seconds` after the first reminder, still away | Second reminder (`stage` 2): `sad`, new reminder ID, spoken again |
| `standby_seconds` after the first reminder, still away | `standby` true: `bored`, reminder cleared, no further reminders; monitoring stays on and a return shows `happy` |
| Dismissal | Silence the current cue; the face stays `sad` and the schedule continues |
| Fresh `uncertain` | Show `happy`; after 1 second of continuous fresh uncertainty report `absent`. The departure time is backdated to the start of that uncertainty |
| Fresh `unavailable` | Camera unavailable; clear pending duration/reminder and enter `bored` |
| Observation timeout or producer disconnect | Clear input and active reminder, rotate the session token and enter `bored` while monitoring |
| Monitoring pause | Clear input and active reminder, rotate session and show `bored`; retain cooldown |
| Power off | Show `idle`; reset monitoring, input, reminder and cooldown |

A reminder needs continuing fresh observations, not one old absence event. Producers should send observations more frequently than the configured timeout. The simulator sends selected simulated observations as a heartbeat until monitoring pauses, power turns off, the tab disconnects or the producer selects unavailable input.

An expired observation window cannot be extended by late input. If the window expires before the next timer tick, submissions using that generation are rejected without changing policy state. The timer then invalidates the input, rotates the token and publishes a refreshed snapshot. The producer must use the new token with fresh observations; a new absence window starts from zero.

Session tokens rotate on actual power/monitoring changes, observation timeout and producer disconnect. Frames buffered from an old session must be discarded. A replacement/reconnecting producer must read current state and generate fresh timestamps, rather than replaying queued frames.

Cooldown is shared and defaults to zero. When set, it only delays the first reminder of a later departure; it remains in effect after presence returns, input becomes unavailable or monitoring pauses. `next_step_seconds` reports the time until the next scheduled reminder or standby, or null when none is pending.

## Camera Frame Adapter

### Frame ingestion

`POST /camera/frame` with raw JPEG bytes, `Content-Type: image/jpeg`,
`X-Camera-Session: <owner token>` and `X-Frame-Sequence: <increasing integer>`.
Sequence is a nonnegative ASCII decimal of at most 16 digits, scoped to the session.
Never log or persist frame bytes or session tokens.

The server bounds streamed request bytes (default 512 KiB), validates JPEG header
dimensions before decoding, and runs decode/BGR-to-RGB conversion and Face Landmarker on its dedicated
worker. Frames must fit the configured width and height. There is one in-flight
body/decode operation across clients, with no processing queue. A timed-out native
job retains that slot until it completes. Session and age are checked again before
publishing a result; late results cannot revive paused or replaced sessions.

Success: `{"accepted":true,"sequence":0}`. Errors: 400 invalid JPEG/sequence,
408 body/processing deadline, 409 stale sequence/session, 413 oversized body,
415 wrong media type, 429 busy, 503 worker failure. Pure validation rejections do
not increment revision. An expired session, processing timeout or worker failure
can invalidate camera input, clear reminders, increment revision and broadcast the
resulting bored state. A decoded
frame marks camera available and increments `frames_received` (per session).

The browser uses one upload at a time, sampling a new frame after the previous
response plus the configured frame interval. FPS is an upper sampling target,
not a guaranteed throughput. Failed uploads are not retried/replayed.


### Lifecycle and observation normalization

The model loads once on a dedicated worker and closes on application shutdown.
Capture starts only after an explicit monitor enable and permission grant. Pause,
power off, source change, owner loss and upload failure invalidate the token.
Late permission grants release their tracks; late inference cannot revive a token.
The browser also stops on pagehide or tab hiding. Re-enable explicitly after loss.
`camera_failed` is an owner-only, zero-field command:

```json
{"type":"camera_failed"}
```

The startup allowance is 30 seconds; subsequent capture idle timeout is 3 seconds.
Observation evidence expires sooner (default 1 second), independently of capture.
Camera unavailability clears pending and active reminders and shows `bored`
while monitoring remains enabled. Intentional pause returns `bored`.

Camera detections retain reason, brightness, blur variance, head pose, normalized
face box, raw blendshapes and per-eye diagnostics. Images are not part of
observations. `camera_observation.presence` and `observation.presence` expose the
same final policy value, including during simulated input or when no frame is
available. Camera diagnostics have a separate reason such as `no_face` so that
raw non-detection is distinguishable without exposing a different presence.

An armed camera with a briefly missing face reports `uncertain` and displays
`happy` during the tracking-loss grace, without starting an absence timer. Continuous fresh no-face results become `absent` after the uncertainty period. Without a baseline,
no face remains `uncertain` until the uncertainty period elapses, then becomes `absent`. Poor lighting, blur and invalid
face landmarks are `uncertain`; unavailable camera input, stale processing and
stale gaps are `unavailable`. Initially both clear pending and active reminders. Fresh uncertainty lasting one second becomes absent; unavailable input stays unavailable.

Any fresh present observation clears an active cue immediately; stable presence
establishes the diagnostic baseline. Stable presence defaults to 0.5 seconds; tracking-loss grace defaults to 1 second and affects diagnostics.
The engine's first reminder follows 10 seconds after the face was first lost
(the start of the qualifying uncertainty). `camera_absence_duration_seconds` exposes the raw interval before that
gate, so an empty scene can be diagnosed without arming a reminder. Head direction,
eye closure and mouth movements never independently trigger reminders.
`backend/behaviour.py` is the retained standalone previous policy; live decisions
come from `backend/policy.py` and the camera gate in `backend/app.py`.

### Camera diagnostics

Head pose uses XYZ Euler rotation from the scale-normalized canonical-to-face
matrix: yaw around Y, pitch around X, roll around Z, in degrees. Direction is
relative to the camera-facing canonical pose by default, with configurable exit
hysteresis. Direction and raw angles are camera-relative.
Positive yaw is labelled subject-left and positive pitch down; physical-camera
validation of these conventions remains pending. Missing pose gives `unknown`.
`face_box` is normalized left/top/right/bottom; only the owner draws it over their
mirrored preview. Blendshapes contain selected movement scores, never emotion,
attention or identity labels. Head pose and blendshapes cannot trigger reminders.

`eye_movement` contains `eyeLeft` and `eyeRight` observations. Each direction is
`center`, `left`, `right`, `up`, `down`, `closed` or `unknown`. Eye names and directions use
the subject's perspective on unmirrored input, independently of the mirrored preview.
Horizontal position increases toward image-right (subject-left); vertical position
increases downward. Both values are normalized to the eye opening in [0, 1].
Horizontal classification uses the iris-to-corner ratio. Vertical classification
uses `vertical_offset`: signed iris displacement from the eye-corner line divided
by eye width, negative for up and positive for down. The default vertical threshold
is 0.08. The lid-relative `vertical` ratio is diagnostic and is not the vertical
direction reference. Near-zero corner-relative displacement remains center. Eye opening uses median upper/lower projections from three lid pairs. A neutral eye has `center` direction.

Eye-local axes account for roll and image aspect ratio. Large head yaw/pitch is
excluded beyond 60° yaw / 45° pitch because this heuristic does not fully
compensate for perspective. Blink scores of at least 0.55 make the affected iris
direction `closed`; raw blink values are still transmitted without rescaling.
Qualifying blink scores are evaluated independently of head-angle availability.
Valid narrow-lid geometry also reports closed without requiring iris landmarks. Reasons
include `usable`, `blink`, `missing_landmarks`, `invalid_landmarks`, `eye_too_small`,
`eye_closed`, `invalid_eye_geometry`, `iris_outside_eye`, `head_pose_unavailable`, `head_turned`
and default `unavailable`. Unknown and closed directions have null positions. An absent or
unknown face defaults to unknown eye observations, so no previous direction persists.
This optional observation field is additive within protocol v9.

`blendshapes` also includes `eyeLookUpLeft`, `eyeLookDownLeft`, `eyeLookUpRight`
and `eyeLookDownRight`. A vertical coefficient must meet the configured threshold
(default 0.30) and exceed the opposing coefficient by the configured margin
(default 0.10). Qualified coefficients allow a half-sized displacement in the same direction;
they cannot impose a vertical label on centered geometry or override measured
motion in the opposite direction. This avoids treating asymmetric/moving lids as
a fixed direction reference. The simulator exposes signed offsets and raw model
signals separately for physical validation.

Blink-threshold closure takes precedence. Eye-opening ratio below 0.06 also reports
closed; ratios from 0.06 to below 0.12 report closed only without qualified vertical
model evidence. Missing/invalid eye geometry and head-angle limits remain gates.
The simulator exposes all four model coefficients in Vertical eye signals. They
are diagnostic movement values, not probabilities or screen-gaze coordinates.

Blink values remain in `blendshapes` as `eyeBlinkLeft`/`eyeBlinkRight`. Mouth values
remain `jawOpen`, `mouthSmileLeft` and `mouthSmileRight`. The simulator renders two
separate Eye movement/Mouth movement rows. Each eye observation includes an optional
`blink_score` in [0, 1], calculated as `clamp(raw / full_closure_reference, 0, 1)`.
The default raw full-closure reference is 0.60. This continuous score is independent
of the closed/center/directional label; a closed label does not override it.
Missing coefficients give null scores and display a dash, including when geometry
alone establishes the closed label. Raw coefficients remain in `blendshapes`.
Normalized scores are approximate closure signals rather than physical percentages
or model confidence. Iris
observations do not affect the absence policy or represent screen gaze/attention.

## Robot Display Serial

When `POMO_SERIAL_PORT` names a device (for example `/dev/cu.usbmodem1101` on macOS or `COM5` on Windows), `backend/hardware.py` mirrors the rendered state to the CoreS3 over USB serial at `POMO_SERIAL_BAUDRATE` (default 115200). An empty port disables it. Backend to device: one ASCII JSON object per line:

```json
{"v":1,"display":"sad","reminder":3,"stage":1,"sound":true,"standby":false,"camera":false}
```

- `v`: serial message version, currently 1. The device ignores other versions.
- `display`: one of the five display identifiers, including manual previews.
- `reminder`: active reminder ID, or 0 when no reminder is active. A new non-zero ID is a new cue.
- `stage`: 0, 1 or 2, as in `reminder.stage`.
- `sound`: false when the shared preference is muted.
- `standby`: as in the snapshot.
- `camera`: true while power is on, monitoring is enabled and `input_source` is `robot`; the device streams frames only while it is true.

Device to backend: binary camera frames, each `PJPG` + uint32 length + uint32 sequence (both little-endian) + a JPEG. The firmware sends 320x240 JPEGs at up to 5 frames per second. The backend resynchronises on `PJPG`, discards frames over `POMO_CAMERA_MAX_BYTES`, and drops frames that arrive while the previous one is still being processed. After each boot the device also sends one text line, `pomo-robot boot reset_reason=<n> camera=<0|1>`, which the backend logs. Frames are never stored or shown on the robot.

A message is queued whenever a published snapshot changes these fields; only the newest pending message is kept. A dedicated thread writes it, so the event loop never blocks on the port, and repeats the last message every 2 seconds as a heartbeat. A missing or unplugged device is logged once as unavailable and reopened every 2 seconds; it never stops the server. The firmware in `firmware/robot-adapter` shows the bored face with "No link" when no line arrives for 6 seconds. The device sends no commands; dismissal and controls remain in the simulator.

The firmware speaks each new non-zero `reminder` once through the CoreS3 speaker, using recorded clips of the stage 1 and stage 2 messages. The first message after the link starts is silent, so an old reminder is never replayed. Speech stops when `reminder` becomes 0 (return, dismissal or standby), when `sound` becomes false, or when the link times out. While `robot_display` is `connected`, the simulator does not speak or play its tone.

## Debug Events and Errors

Events include an increasing integer `id`, UTC ISO-8601 `at`, `level` (`info`, `warning` or `error`), `kind` and bounded `message`. They record transitions, reminder activity, source changes, lifecycle changes, connections and command rejections. Unchanged observation heartbeats do not add log entries.

For user-study timing, the server log also records `departure_detected` (with the backdated departure time), `reminder_triggered` (with first/second stage and time away), `standby_entered`, `user_returned` (seconds since the latest reminder and total time away) and `absence_interrupted` (input lost, paused or powered off during a departure).

The backend keeps only the latest 100 events in memory and writes event summaries through Python logging. The simulator displays the bounded backend log separately from its local connection journal. Clearing the browser log hides existing entries in that tab; it does not delete shared backend history.

Rejected commands return:

```json
{"type":"error","code":"invalid_command","message":"Explanation"}
```

Rejected commands do not apply the requested policy operation or directly increment revision. Rejection itself is recorded as a debug event. The timer may subsequently publish logs or independently advance elapsed-time policy state.

No frame/image/video fields are accepted in JSON commands. JPEG bodies belong only to `/camera/frame`; never persist or log them.

## Reconnection and Sound Delivery

The simulator retries after 1, 2, 4 and 8 seconds, then at most every 10 seconds. Controls remain disabled until a valid snapshot arrives. While disconnected, the previous display is marked stale, simulated-input heartbeats and any local tone stop, and commands are not queued.

On reconnect, restore the current snapshot and require a new simulated-input selection. The first snapshot never plays an old reminder sound. Unless the robot display is connected, subsequent newly observed active reminders speak the reminder message once per audio-enabled tab using browser speech synthesis, falling back to a short tone when speech is unavailable, identified by `instance_id:reminder.id`. Clearing the reminder, muting, pausing, powering off or disconnecting cancels speech. Manual previews, mute/unmute and later snapshots of the same reminder do not replay sound.

A backend restart creates a new instance ID, resets reminder/event counters and revision, powers the simulated robot on with monitoring paused, and clears observations/cooldowns. Sound preference resets to the configured startup default.

## Configuration and Deterministic Checks

| Environment setting | Default | Constraint |
| --- | --- | --- |
| `POMO_UNCERTAINTY_SECONDS` | `1` | Continuous fresh uncertainty before it becomes absent |
| `POMO_ABSENCE_SECONDS` | `10` | Leaving to first reminder. At startup: finite, greater than zero, at most 3600, and at least camera tracking-loss grace |
| `POMO_REMINDER_REPEAT_SECONDS` | `300` | First to second reminder; finite, greater than zero |
| `POMO_STANDBY_SECONDS` | `600` | First reminder to standby; greater than the repeat interval |
| `POMO_REMINDER_COOLDOWN_SECONDS` | `0` | Finite, non-negative; spaces first reminders between departures |
| `POMO_OBSERVATION_TIMEOUT_SECONDS` | `3` | Finite, greater than zero |
| `POMO_SOUND_ENABLED` | `true` | Startup preference; browser audio still requires a user gesture |
| `POMO_SERIAL_PORT` | empty | CoreS3 serial device; empty disables the robot display adapter |
| `POMO_SERIAL_BAUDRATE` | `115200` | Positive integer; must match the firmware |
| `POMO_DEV_CONTROLS` | `true` | Gates simulated input and manual expression previews |

Tests can construct `create_app(config=PolicyConfig(...), clock=fake_monotonic, wall_clock=fake_epoch, run_ticker=False)` and explicitly await `app.state.runtime.tick()`. Pure policy tests inject both clocks into `ReminderEngine`. No test-only command for advancing time is exposed over the WebSocket.

Camera configuration and perception thresholds are listed in `.env.example` and
README. `POMO_TRACKING_LOSS_GRACE_SECONDS`, `POMO_RETURN_SECONDS` and
`POMO_OBSERVATION_MAX_AGE_SECONDS` apply to the camera evidence adapter. The shared
`POMO_ABSENCE_SECONDS` applies to the authoritative reminder engine in both modes.

## Task Sources

- [Reminders](https://app.notion.com/p/40a66acb0c0380f5bacfc18ac6fa598a)
- [States Implementation](https://app.notion.com/p/40a66acb0c0380deaf4fd7dbefb28b04)
- [Debug Logs](https://app.notion.com/p/40a66acb0c0380078ca4ef9dcfaed7e9)
- [Camera Detection](https://app.notion.com/p/40a66acb0c038013b8b5eb483fa9e18e)
