# Protocol v6

The browser connects to `/ws` on the page origin (WSS on HTTPS). JSON text commands
remain limited to 4,096 bytes. Images use a separate bounded HTTP endpoint.
Monitoring uses browser camera ownership and shared state snapshots. Update
browser and backend together.

## Snapshots and commands

New/reconnecting clients receive a complete snapshot. Every accepted command and
successful frame increments revision and broadcasts state. Lifecycle changes also
increment revision. All clients share one process-local robot; use one server worker.

```json
{
  "type": "state", "protocol_version": 6,
  "monitoring_enabled": false, "display": "ready",
  "camera_status": "paused", "revision": 0,
  "dev_controls": true, "camera_session": null,
  "frames_received": 0, "last_frame": null,
  "camera_settings": {
    "width": 640, "height": 480, "fps": 10, "jpeg_quality": 0.75,
    "max_bytes": 524288, "timeout_seconds": 3, "startup_seconds": 30
  }
}
```

`camera_status`: `paused`, `starting`, `available`, `unavailable`. These describe
capture/transport, not face presence, reminders or WebSocket health.
`last_frame`, when present, contains `width`, `height` and `sequence`; never pixels.

```json
{"type":"set_monitoring","enabled":true}
{"type":"set_monitoring","enabled":false}
{"type":"camera_failed"}
{"type":"preview_display","display":"possible_absence"}
```

Enabling reserves the camera for the sending WebSocket and resets display to ready.
A new opaque `camera_session` is included only in that owner's snapshots. Other
clients see null. A second enable while owned is rejected, including from the owner;
pause first to restart. Any client may pause shared monitoring. Only the owner may
report `camera_failed` (no other fields). Pausing, owner disconnection, failure or
timeout invalidates the session and clears frame metadata; failure sets unavailable.

Display values remain `ready`, `possible_absence`, `reminding`, `unavailable`.
Previews require development controls, work while paused and do not represent
inference or reminders. Invalid commands return `invalid_command` errors without
mutating state. Unknown fields, non-boolean enabled, invalid JSON and binary
WebSocket messages are rejected.

## Frame ingestion

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
415 wrong media type, 429 busy. Rejected frames do not increment revision. A decoded
frame marks camera available and increments `frames_received` (per session).

The browser uses one upload at a time, sampling a new frame after the previous
response plus the configured frame interval. FPS is an upper sampling target,
not a guaranteed throughput. Failed uploads are not retried/replayed.

## Lifecycle and recovery

Backend initialization opens the model once on a dedicated thread. A failed
initialization keeps the server reachable, reports unavailable, sets
`camera_processor_ready=false` in `/health` and rejects enable commands. Fix setup
and restart. `/health` otherwise reports `{"status":"ok","phase":2,
"camera_processor_ready":true}`.

A watchdog expires sessions after the startup allowance (default 30 seconds) or,
after the first accepted frame, the idle allowance (default 3 seconds). Deadlines
use backend monotonic time; browser timestamps are not compared with that clock.
This transport timeout is independent of the shorter observation-freshness limit.

The browser releases media tracks on pause, capture/upload failure, owner-session
loss, WebSocket disconnection, pagehide and tab hiding. Hidden tabs pause shared
monitoring rather than silently relying on throttled timers. A late permission
grant after cancellation immediately stops its tracks. Reconnection restores state,
but capture needs a fresh explicit enable. Commands and images are never queued
offline. Backend restart resets monitoring and sessions.

The preview comes directly from the browser's video stream and is mirrored only
for display; uploaded pixels are unmirrored. Permissions require localhost or HTTPS.
WSL does not need a `/dev/video*` device. Face presence drives the sustained-absence policy described below. Identity
recognition is not implemented.


## Observation and behaviour fields

An accepted frame provides `observation`, `head_direction` and a `behaviour`
diagnostic object in snapshots.

```json
{
  "observation": {
    "observed_at": 100.0, "processed_at": 100.04,
    "presence": "present", "reason": "usable",
    "brightness": 115.2, "blur_variance": 210.4,
    "head_pose": {"yaw": 2.0, "pitch": -3.0, "roll": 0.0},
    "face_box": [0.2, 0.1, 0.8, 0.9],
    "blendshapes": {"eyeBlinkLeft": 0.1, "eyeBlinkRight": 0.1, "jawOpen": 0.1},
    "eye_movement": {
      "eyeLeft": {"direction": "center", "blink_score": 0.1667, "horizontal": 0.5, "vertical": 0.5, "vertical_offset": 0.0, "reason": "usable"},
      "eyeRight": {"direction": "left", "blink_score": 0.1667, "horizontal": 0.8, "vertical": 0.5, "vertical_offset": 0.0, "reason": "usable"}
    }
  },
  "head_direction": "forward",
  "behaviour": {
    "status": "present", "armed": true, "absence_seconds": 0,
    "reminder_active": false
  }
}
```

`observation` is null before input, on pause/session loss and when the watchdog
marks input stale. `presence` is `present`, `not_detected` or `unknown`.
Reasons include `usable`, `no_face`, `low_light`, `overexposed`,
`low_detail_or_blur`, `invalid_landmarks`, `stale`. Optional diagnostics default to
null/empty. `observed_at` is backend request-receipt monotonic time, not a browser
capture timestamp. `processed_at` is backend completion time. Sequence/session
validation remains part of ingestion. Neither timestamps nor image quality metrics
are model confidence scores. A late inference becomes unknown and cannot remind.

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
This optional observation field is additive within protocol v6.

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

```json
{"type":"dismiss_reminder"}
```

`dismiss_reminder` takes no additional fields. Any connected client may dismiss the
shared reminder. Dismissal requires an actual policy reminder; a manual display
preview is not dismissible. Invalid requests return `invalid_command` and leave
revision/state unchanged.

Policy status values: `paused`, `unavailable`, `awaiting_face`, `confirming_face`,
`present`, `tracking_loss`, `possible_absence`, `reminding`, `uncertain`,
`stale`. Every fresh `not_detected` observation contributes to a continuous absence
interval, even before stable face presence arms reminders. `behaviour.absence_seconds`
starts at zero on the first non-detection and advances with fresh observation times.
This same interval selects `tracking_loss` before the configured grace period and
`possible_absence` at/after that boundary. Stable visible presence is required only
for reminder arming: `reminding` activates at the absence threshold when armed.
Unarmed non-detection continues counting and remains `possible_absence` past that
threshold, with `reminder_active=false`. Grace counts within the total duration.
Any reliable present observation cancels pending absence; stable presence clears
an active reminder.

Dismissal clears the active reminder and resets the absence countdown. A later
reminder requires a new continuous non-detection interval. Pause/session loss
clears the face baseline,
pending duration and active reminder.
Unknown, stale and unavailable input clear evidence and reminders; a fresh stable
face baseline is required before absence can remind again. A watchdog marks
observations stale independently of the camera's longer transport timeout. Waiting
without new observations never triggers an absence reminder.

`display` belongs to manual expression previews. Observations, policy transitions,
reminder dismissal, stale input and camera failures preserve the selected expression.
Explicit monitoring enable/pause commands retain the ready reset. Camera ownership,
observations and `behaviour.status` are separate from display. Detection data never
selects Expression buttons or renders the robot face.

Clients render detection/reminder information within the camera diagnostics, using
`behaviour.reminder_active` for prompts and dismissal. Repeated snapshots do not
repaint unchanged expression/title content or reset idle video sources. The app
contains no full-page reload command.
Absence duration reflects the latest snapshot, not a client-side timer.
See README and `.env.example` for defaults and tuning limitations.
