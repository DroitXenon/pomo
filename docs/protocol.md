# Protocol v7

The backend serves the simulator at `/`, reports health at `/health` and accepts WebSocket connections at `/ws` on the same origin. Use `ws` for HTTP and `wss` for HTTPS.

Version 7 combines the v2 reminder branch and v6 browser-camera branch. It preserves browser JPEG ingestion and uses one shared reminder policy for camera and simulated input. Display identifiers are `ready`, `shutdown`, `distraction`, `reminding` and `unavailable`; `possible_absence` is no longer a display identifier. Update backend and simulator together; earlier clients are incompatible.

`GET /health` returns:

```json
{"status":"ok","phase":2,"protocol_version":7,"camera_processor_ready":true}
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
  "protocol_version": 7,
  "instance_id": "6fe3ecf8-69bc-468d-b690-5dc162dc9393",
  "revision": 0,
  "dev_controls": true,
  "powered_on": true,
  "monitoring_enabled": false,
  "muted": true,
  "behavior_state": "ready",
  "display": "ready",
  "preview_active": false,
  "camera_status": "unavailable",
  "observation_session": "fece9f0ba618451ea17e8ef3ab8dafde",
  "observation": {
    "presence": "unknown",
    "source": "none",
    "observed_at": null,
    "age_seconds": null
  },
  "absence_duration_seconds": 0.0,
  "cooldown_remaining_seconds": 0.0,
  "reminder": {
    "active": false,
    "id": 0,
    "message": null
  },
  "settings": {
    "absence_seconds": 5.0,
    "cooldown_seconds": 30.0,
    "observation_timeout_seconds": 3.0
  },
  "events": [],
  "input_source": "camera",
  "camera_session": null,
  "camera_processor_ready": true,
  "camera_capture_status": "paused",
  "camera_settings": {
    "width": 640, "height": 480, "fps": 10, "jpeg_quality": 0.75,
    "max_bytes": 524288, "timeout_seconds": 3, "startup_seconds": 30
  },
  "frames_received": 0,
  "last_frame": null,
  "camera_observation": null,
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
| `behavior_state` | Actual policy state: `ready`, `shutdown`, `distraction`, `reminding` or `unavailable` |
| `display` | Rendered expression; equals behaviour unless a manual preview is active |
| `preview_active` | Whether a development expression preview is overriding rendering |
| `camera_status` | `available` or `unavailable`, independently of WebSocket connection status |
| `observation.presence` | `present`, `absent` or `unknown`; unavailable input is represented as unknown presence |
| `observation.source` | `none`, `simulated` or `camera` |
| `observation.observed_at` | Last accepted source timestamp, in Unix seconds, or `null` |
| `observation.age_seconds` | Source age on receipt plus subsequent monotonic elapsed time, or `null` |
| `observation_session` | Opaque token producers must copy from the latest snapshot |
| `absence_duration_seconds` | Current continuous absence window; resets on recovery, uncertain/unavailable input, pause or input gaps |
| `cooldown_remaining_seconds` | Remaining quiet period, clamped to zero |
| `reminder.id` | Counter increased only when a real reminder is triggered; use with `instance_id` to identify a cue |
| `reminder.active` / `message` | Whether a real visual reminder is active and its supportive text; message is `null` when inactive |
| `events` | Up to 100 recent backend events in oldest-to-newest order |

Connection status is a client-side transport condition. It must not be interpreted as user absence. A camera can be available while tracking is uncertain; in that case presence is `unknown` and behaviour is `unavailable`.

Additional camera fields are:

| Field | Meaning |
| --- | --- |
| `input_source` | `camera` by default, or explicitly selected `simulated` |
| `camera_session` | Opaque upload token only visible to its owning WebSocket |
| `camera_processor_ready` | Whether model initialization succeeded; simulation can work when false |
| `camera_capture_status` | Capture/transport: `paused`, `starting`, `available`, `unavailable` |
| `camera_observation` | Latest raw, validated camera diagnostics, or null after invalidation |
| `head_direction` | Camera-relative `forward`, `left`, `right`, `up`, `down` or `unknown` |
| `camera_armed` | Whether stable visible-face evidence permits camera absence reminders |
| `camera_tracking_status` | Baseline/grace/quality diagnostic, separate from actual `behavior_state` |
| `camera_absence_duration_seconds` | Raw continuous non-detection interval, including before arming |
| `frames_received`, `last_frame` | Accepted frame count and dimensions/sequence, never pixels |

`camera_status` retains the policy input availability meaning from v2;
`camera_capture_status` holds the browser capture meaning formerly named
`camera_status` in v6. `observation` is the normalized policy input;
`camera_observation` holds the richer v6 diagnostic schema. They are deliberately
separate so clock domains and unknown input are not confused with absence.

## Strict Commands

Booleans must be JSON booleans, not strings or numbers. Commands accept only the fields shown.

### Input source

```json
{"type":"set_input_source","source":"camera"}
{"type":"set_input_source","source":"simulated"}
```

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
- Pausing monitoring returns behaviour to `ready` and preserves any remaining cooldown.
- `set_power` is a soft power control. Power off enters `shutdown`, disables monitoring and clears input, preview, active reminder and cooldown. It does not terminate HTTP or WebSocket serving.
- Power on returns to `ready` with monitoring paused. Repeating an unchanged power or monitoring setting is idempotent at policy level, although an accepted command still receives a new revision.

### Sound and dismissal

```json
{"type":"set_muted","muted":false}
{"type":"set_muted","muted":true}
{"type":"dismiss_reminder","reminder_id":1}
```

Mute is a shared preference. It does not change reminder IDs or trigger a new reminder. The browser needs a user gesture to unlock its local audio context; visual reminders work when audio is unavailable.

Dismissal requires a strict positive integer matching the currently active reminder. A stale or inactive ID is rejected. Dismissal clears the visual cue, returns ongoing absence to `distraction` and ensures a full new cooldown using `max(existing_deadline, dismissal_time + cooldown)`.

### Development expression previews

```json
{"type":"preview_display","display":"distraction"}
{"type":"clear_preview"}
```

Preview accepts any of the five display identifiers. It requires power on, monitoring paused and development controls enabled. It changes rendering only: previewing `reminding` does not activate a real reminder, increment its ID or play a sound; previewing `shutdown` does not power off the backend policy.

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

- `presence`: `present`, `absent`, `unknown` or `unavailable`.
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
| Monitoring enabled without valid input | `unavailable`; no reminder |
| Fresh `present` | `ready`; clear pending duration and active reminder; retain cooldown |
| Fresh `absent` | `distraction`; start/continue a sustained absence window |
| Absence threshold reached with fresh input and no cooldown | `reminding`; increment reminder ID, show message and start cooldown |
| Reminder remains active | Keep the same reminder; do not repeatedly trigger cues when its original cooldown ends |
| Dismissal | Clear the active reminder and begin a full quiet period; continuing absence may retrigger only after cooldown |
| Fresh `unknown` | Camera available but tracking uncertain; clear pending duration/reminder and enter `unavailable` |
| Fresh `unavailable` | Camera unavailable; clear pending duration/reminder and enter `unavailable` |
| Observation timeout or producer disconnect | Clear input and active reminder, rotate the session token and enter `unavailable` while monitoring |
| Monitoring pause | Clear input and active reminder, rotate session and show `ready`; retain cooldown |
| Power off | Show `shutdown`; reset monitoring, input, reminder and cooldown |

A reminder needs continuing fresh observations, not one old absence event. Producers should send observations more frequently than the configured timeout. The simulator sends selected simulated observations as a heartbeat until monitoring pauses, power turns off, the tab disconnects or the producer selects unavailable input.

An expired observation window cannot be extended by late input. If the window expires before the next timer tick, submissions using that generation are rejected without changing policy state. The timer then invalidates the input, rotates the token and publishes a refreshed snapshot. The producer must use the new token with fresh observations; a new absence window starts from zero.

Session tokens rotate on actual power/monitoring changes, observation timeout and producer disconnect. Frames buffered from an old session must be discarded. A replacement/reconnecting producer must read current state and generate fresh timestamps, rather than replaying queued frames.

Cooldown is shared and remains in effect after presence returns, input becomes unavailable or monitoring pauses. A zero cooldown is supported and deliberately permits immediate retriggering after dismissal when fresh sustained absence still applies.

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
resulting unavailable state. A decoded
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
Camera unavailability clears pending and active reminders and shows `unavailable`
while monitoring remains enabled. Intentional pause returns `ready`.

Raw observations use server receipt/completion monotonic timestamps and presence
`present`, `not_detected` or `unknown`. They retain reason, brightness, blur variance,
head pose, normalized face box, raw blendshapes and per-eye diagnostics. Images are
not part of observations. For policy input, receipt time is converted to Unix time
with processing age retained; model `not_detected` maps to `absent` only after the
stable-face baseline and tracking-loss grace have qualified it. Poor lighting,
blur, unavailable input, excessive processing age and stale gaps map to unknown,
clear reminders and require a fresh baseline.

Any fresh present observation clears an active cue immediately; stable presence
arms subsequent absence reminders. Stable presence defaults to 0.5 seconds; tracking-loss grace defaults to 1 second.
The normalized engine's absence threshold is 5 seconds after qualifying absence
begins. `camera_absence_duration_seconds` exposes the raw interval before that
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
This optional observation field is additive within protocol v7.

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

## Debug Events and Errors

Events include an increasing integer `id`, UTC ISO-8601 `at`, `level` (`info`, `warning` or `error`), `kind` and bounded `message`. They record transitions, reminder activity, source changes, lifecycle changes, connections and command rejections. Unchanged observation heartbeats do not add log entries.

The backend keeps only the latest 100 events in memory and writes event summaries through Python logging. The simulator displays the bounded backend log separately from its local connection journal. Clearing the browser log hides existing entries in that tab; it does not delete shared backend history.

Rejected commands return:

```json
{"type":"error","code":"invalid_command","message":"Explanation"}
```

Rejected commands do not apply the requested policy operation or directly increment revision. Rejection itself is recorded as a debug event. The timer may subsequently publish logs or independently advance elapsed-time policy state.

No frame/image/video fields are accepted in JSON commands. JPEG bodies belong only to `/camera/frame`; never persist or log them.

## Reconnection and Sound Delivery

The simulator retries after 1, 2, 4 and 8 seconds, then at most every 10 seconds. Controls remain disabled until a valid snapshot arrives. While disconnected, the previous display is marked stale, simulated-input heartbeats and any local tone stop, and commands are not queued.

On reconnect, restore the current snapshot and require a new simulated-input selection. The first snapshot never plays an old reminder sound. Subsequent newly observed active reminders may play one short cue per audio-enabled tab, identified by `instance_id:reminder.id`. Manual previews, mute/unmute and later snapshots of the same reminder do not replay sound.

A backend restart creates a new instance ID, resets reminder/event counters and revision, powers the simulated robot on with monitoring paused, and clears observations/cooldowns. Sound preference resets to the configured startup default.

## Configuration and Deterministic Checks

| Environment setting | Default | Constraint |
| --- | --- | --- |
| `POMO_ABSENCE_SECONDS` | `5` | At startup: finite, greater than zero, at most 3600, and at least camera tracking-loss grace |
| `POMO_REMINDER_COOLDOWN_SECONDS` | `30` | Finite, non-negative |
| `POMO_OBSERVATION_TIMEOUT_SECONDS` | `3` | Finite, greater than zero |
| `POMO_SOUND_ENABLED` | `false` | Startup preference; browser audio still requires a user gesture |
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
