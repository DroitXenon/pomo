# Pomo

Pomo is a desktop robot study companion. A camera watches whether the user is at the desk; when they leave, a backend policy drives a sequence of facial expressions and spoken reminders, rendered on an M5Stack CoreS3 and in a browser control page.

The system is a single Python process (FastAPI + MediaPipe) that owns all behaviour, a dependency-free browser client that renders state and provides development controls, and optional CoreS3 firmware that mirrors the face, speaks reminders and streams its own camera over USB.

> Presence detection answers one question: is a usable face in frame? It does not measure attention, focus or distraction, and camera or connection failure is reported as unavailable input, never as user absence.

## Contents

- [System overview](#system-overview)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Reminder policy](#reminder-policy)
- [Perception pipeline](#perception-pipeline)
- [Interfaces](#interfaces)
- [Robot hardware](#robot-hardware)
- [Control page](#control-page)
- [Configuration](#configuration)
- [Testing and verification](#testing-and-verification)
- [Deployment and security](#deployment-and-security)
- [Repository layout](#repository-layout)
- [Project status](#project-status)

## System overview

```text
                 ┌────────────────────────── one Python process (python -m backend) ──────────────────────────┐
Browser webcam ─▶│ POST /camera/frame ─┐                                                                       │
                 │                     ├─▶ FrameProcessor ─▶ presence normaliser ─▶ ReminderEngine ─▶ snapshot ─┼─▶ /ws ─▶ all browser tabs
CoreS3 camera ──▶│ serial PJPG frames ─┘    (worker thread:     (baseline, grace,     (policy,        (revisioned │
 (USB, optional) │                           JPEG decode +        max age)              timers,          complete    │
                 │ /ws commands ───────────────────────────────────────────────────────▶ events)         state)     ├─▶ SerialDisplay ─▶ CoreS3 face + speaker
                 │   (simulated input, monitoring, power, mute, dismiss, previews)                                    │     (serial thread)
                 └────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Concern | Owner | Notes |
| --- | --- | --- |
| Behaviour and timing | `backend/policy.py` `ReminderEngine` | Camera-independent; injected monotonic clock; the only live policy |
| Transport, ownership, serialisation | `backend/app.py` `Runtime` | Strict commands, one `asyncio.Lock`, 250 ms tick, camera session tokens |
| Perception | `backend/camera.py`, `perception.py`, `eyes.py` | MediaPipe Face Landmarker on a dedicated worker; eye/head data is diagnostic only |
| Hardware | `backend/hardware.py` `SerialDisplay` | Optional; all serial I/O on its own thread |
| Rendering and controls | `simulator/` | Plain HTML/CSS/JS, no build step, no client-side state machine |
| Firmware | `firmware/robot-adapter` | PlatformIO, M5Unified, TinyUSB CDC |

## Quick start

Requirements: Conda (Miniconda or Miniforge). Node.js is optional and only used for the JavaScript tests. PlatformIO is only needed to flash the robot.

```sh
sh scripts/setup.sh     # create/update the pomo env (Python 3.13), download + checksum models/face_landmarker.task
sh scripts/dev.sh       # start on http://127.0.0.1:8000/ with live logs; Ctrl+C to stop
```

Then open [http://127.0.0.1:8000/](http://127.0.0.1:8000/), pick an input source while monitoring is paused, and enable monitoring.

| Input source | Use | Requirement |
| --- | --- | --- |
| **Camera** | Browser webcam via `getUserMedia` | Camera permission; page served from `localhost` or HTTPS |
| **Robot camera** | CoreS3 camera streamed over USB | `POMO_SERIAL_PORT` set and the robot connected |
| **Simulated** | Synthetic `present` / `absent` / `uncertain` / `unavailable` heartbeats | `POMO_DEV_CONTROLS=true` (default) |

Useful variants:

```sh
POMO_PORT=8001 sh scripts/dev.sh                                    # second server on a free port
POMO_SERIAL_PORT=/dev/cu.usbmodem7C4FADAF80EC1 sh scripts/dev.sh     # with the robot (or set it in .env)
POMO_ABSENCE_SECONDS=3 POMO_REMINDER_REPEAT_SECONDS=10 POMO_STANDBY_SECONDS=20 sh scripts/dev.sh   # short demo timings
```

Without `sh` (for example on Windows), use Conda directly; recent Conda reads the CEP-24 platform selectors in `environment.yml`:

```sh
conda env create --file environment.yml --format cep-24      # or: conda env update --name pomo --file environment.yml --format cep-24 --prune
conda activate pomo
python scripts/setup_model.py
python -m backend
```

`scripts/setup.sh` also supports Conda 25 by filtering a temporary copy of the same definition. Copy `.env.example` to `.env` for local settings; existing `.env` files are preserved.

## Architecture

### Process model

One Uvicorn worker serves the static client at `/`, `/health`, the `/ws` command/snapshot channel and `POST /camera/frame`. All clients share one in-memory robot. Restarting the process resets state, counters and history and issues a new `instance_id`, which clients use to discard stale history. Multiple workers are not supported while state is process-local.

### Concurrency

- **Event loop.** Every engine operation and every broadcast runs under a single `asyncio.Lock`, so commands, camera observations and timer ticks are linearised. Each accepted change increments `revision` and broadcasts a complete snapshot; there are no partial updates.
- **Timer.** A 250 ms `tick()` expires observations and advances thresholds. A snapshot is published only when visible state or live diagnostics change.
- **Perception worker.** JPEG decoding and Face Landmarker inference run on one dedicated thread. There is exactly one in-flight frame across all clients and no queue: a second upload while busy gets `429`. A native job that exceeds its deadline keeps the slot until it returns, and its late result is discarded.
- **Serial thread.** `SerialDisplay` owns the port on its own thread. The event loop only replaces a single "latest message" slot, so a slow or missing device can never block the server.
- **Slow clients.** Each WebSocket send has a 2 s timeout; a client that cannot keep up is dropped rather than stalling the broadcast.

### Ownership and lifecycle tokens

- **Observation session.** Monitoring changes, power changes and source changes rotate `observation_session`. Producers must echo it with each observation; anything from an older session is rejected, so buffered or in-flight input cannot revive a paused robot.
- **Camera session.** Only the tab that enabled the **Camera** source receives the private upload token (`camera_session`); other tabs observe without touching the webcam. Uploads carry a strictly increasing `X-Frame-Sequence`. Session and age are re-checked after inference before a result is published.
- **Producer loss.** If the tab that was producing observations disconnects, its input and any active reminder are invalidated and the robot shows `bored`. A viewer disconnect does not affect another tab's source.
- **Reminder identity.** Each real reminder gets an increasing `reminder.id` scoped to the backend instance. Clients and firmware speak a cue only when they see a new non-zero ID after their first snapshot, so reconnects and repeated snapshots never replay sound.

## Reminder policy

`ReminderEngine` maps a stream of timestamped presence observations to one of five behaviour states. It never sees images.

### Observations

| Presence | Produced by | Policy effect while powered on and monitoring |
| --- | --- | --- |
| `present` | A usable face, or simulated Present | `happy`; ends any departure, clears the reminder and logs `user_returned` with latency |
| `uncertain` | No face, too dark/bright, blurred or invalid landmarks, or simulated Uncertain | `happy` at first; after `POMO_UNCERTAINTY_SECONDS` of continuous fresh uncertainty it becomes `absent`, backdated to when uncertainty began |
| `absent` | Sustained uncertainty, or simulated Absent | `surprised`, then the reminder sequence below |
| `unavailable` | No input yet, camera failure, owner disconnect, expired input, or simulated Unavailable | `bored`; clears pending absence and active reminders; never turns into `absent` |

### Timeline of one departure (defaults)

```text
t = 0 s     face lost            uncertain → display happy           departure_detected (backdated)
t = 1 s     uncertainty expires  absent    → display surprised
t = 10 s    POMO_ABSENCE_SECONDS           → display sad (crying), reminder stage 1 spoken    reminder_triggered (first)
t = 310 s   + POMO_REMINDER_REPEAT_SECONDS → reminder stage 2 spoken                          reminder_triggered (second)
t = 610 s   + POMO_STANDBY_SECONDS         → display bored, no further reminders              standby_entered
any time    present                        → display happy                                    user_returned (latency since latest reminder)
```

The absence clock starts when the face was first lost, not when uncertainty became `absent`, so `POMO_ABSENCE_SECONDS` is the true time from leaving to the first reminder. Repeat and standby are measured from the first reminder. Each departure produces at most two reminders. An optional `POMO_REMINDER_COOLDOWN_SECONDS` enforces a minimum gap between first reminders of separate departures; while it runs, the face stays `surprised`.

Fresh input must continue throughout. If camera evidence becomes older than `POMO_OBSERVATION_MAX_AGE_SECONDS` (1 s) or any producer's input exceeds `POMO_OBSERVATION_TIMEOUT_SECONDS` (3 s), input becomes `unavailable` and the sequence ends. A single `absent` packet cannot sustain a reminder.

### Expressions

| Display | Shown when | Exits to |
| --- | --- | --- |
| `happy` | `present`, or `uncertain` shorter than the uncertainty period | `surprised` on absence; `bored` on pause/unavailable; `idle` on power off |
| `surprised` | Away, first reminder not yet due (or cooldown running) | `sad` at the first reminder; `happy` on return |
| `sad` | First or second reminder active (crying face) | `bored` at standby; `happy` on return |
| `bored` | Monitoring paused, input unavailable, or standby | `happy` on fresh presence (including after standby) |
| `idle` | Soft power off: monitoring, input, preview, reminders and cooldown cleared | Wake returns to `bored` with monitoring paused |

### Control semantics

- **Dismissal** (`dismiss_reminder` with the current ID) silences the active cue and hides its message but keeps the `sad` face; the second reminder and standby still follow on schedule. Stale or inactive IDs are rejected. Dismissal also extends any configured cooldown.
- **Pause** and **power off** discard observations and reminders and rotate the session. Enabling monitoring without fresh input shows `bored`.
- **Mute** is a shared preference (`POMO_SOUND_ENABLED` sets the initial value). It stops speech in progress on both the browser and the robot.
- **Expression previews** (`preview_display`) override only the rendered face. They require power on, monitoring paused and development controls enabled, and never create reminders or sound.

### Speech

Reminder text lives in `REMINDER_MESSAGES` in `backend/policy.py` (stage 1: "I miss you. Please come back to your study when you're ready."; stage 2: "I'm still here. Come back to your study whenever you're ready."). When the robot is connected (`robot_display: connected`) the CoreS3 plays recorded clips of these sentences and the browser stays silent. Otherwise the browser uses the Web Speech API, falling back to a short tone. Browsers require one user gesture per tab ("Enable audio in this tab") before audio can play; visual reminders do not depend on it.

## Perception pipeline

```text
JPEG bytes ─▶ size + header-dimension checks ─▶ OpenCV decode ─▶ brightness / Laplacian-blur gates
          ─▶ MediaPipe Face Landmarker (VIDEO mode) ─▶ face box, head pose (yaw/pitch with hysteresis),
             blendshapes, per-eye iris/blink diagnostics ─▶ CameraObservation(presence, reason, ...)
```

1. **Bounded ingestion.** The request body is streamed and rejected above `POMO_CAMERA_MAX_BYTES` (512 KiB). JPEG header dimensions are checked against `POMO_CAMERA_WIDTH`/`HEIGHT` before decoding, so oversized images never reach OpenCV.
2. **Quality gates.** Grayscale mean outside `POMO_PERCEPTION_MIN/MAX_BRIGHTNESS` (35 to 230) or Laplacian variance below `POMO_PERCEPTION_MIN_BLUR_VARIANCE` (5) produces `uncertain` with reason `low_light`, `overexposed` or `low_detail_or_blur`.
3. **Face Landmarker.** The versioned model (`models/face_landmarker.task`, URL and checksum in [models/README.md](models/README.md)) is loaded once. No face gives reason `no_face` (the normaliser turns it into `uncertain` first); unusable landmarks give `uncertain` with `invalid_landmarks`.
4. **Diagnostics.** Head direction uses yaw/pitch thresholds (30 / 25 degrees) with a 5 degree exit margin to suppress flicker. Iris direction and blink scores are computed per eye and suppressed beyond 60 / 45 degrees of head rotation. These values are displayed for development only and never drive reminders.
5. **Normalisation** (`Runtime._normalized_presence`). Stable presence for `POMO_RETURN_SECONDS` (0.5 s) arms a diagnostic baseline; brief tracking loss within `POMO_TRACKING_LOSS_GRACE_SECONDS` (1 s) is labelled as such; evidence older than `POMO_OBSERVATION_MAX_AGE_SECONDS` becomes `unavailable`. The result is passed to `engine.observe` with its capture timestamp.

`camera_observation` in the snapshot carries the detailed diagnostics (reason, brightness, blur, box, pose, eyes, `frames_received`). Its `presence` always equals the policy `observation.presence`, so poor image quality that persists can legitimately lead to a reminder. That is a policy classification, not proof that the user left.

Frames are processed in memory only. They are never logged, written to disk or included in test fixtures; the browser preview is mirrored locally while uploaded pixels are not.

## Interfaces

Full schemas, examples and recovery rules: [docs/protocol.md](docs/protocol.md) (**protocol version 10**). Backend, client, firmware, tests and that document must change together; older clients are incompatible.

### HTTP and WebSocket

| Endpoint | Method | Contract |
| --- | --- | --- |
| `/` | GET | Static control page and assets |
| `/health` | GET | `{"status":"ok","phase":2,"protocol_version":10,"camera_processor_ready":bool}` |
| `/ws` | WebSocket | JSON text commands (max 4,096 bytes) in; complete `state` snapshots and `error` messages out |
| `/camera/frame` | POST | Raw JPEG, `Content-Type: image/jpeg`, `X-Camera-Session`, `X-Frame-Sequence` |

### Commands

Each command is a strict Pydantic model selected by `type`; unknown types, extra fields, wrong types, binary frames and oversized messages are rejected with an `error` message and never mutate state.

| `type` | Fields | Constraints |
| --- | --- | --- |
| `set_input_source` | `source`: `camera` \| `robot` \| `simulated` | Power on, monitoring paused; `simulated` needs dev controls, `robot` needs `POMO_SERIAL_PORT` |
| `set_monitoring` | `enabled` | Enabling needs power on (and a connected robot for `robot`) |
| `set_power` | `enabled` | Soft power; off enters `idle` |
| `set_muted` | `muted` | Shared preference |
| `dismiss_reminder` | `reminder_id` (integer at least 1) | Must match the active reminder |
| `submit_observation` | `presence`, `source`, `observed_at`, `session_id` | Simulated input, monitoring on, current session, strictly increasing timestamps, younger than the observation timeout and at most 1 s in the future |
| `camera_failed` | none | Camera owner only |
| `preview_display` / `clear_preview` | `display` / none | Dev controls, power on, monitoring paused |

Booleans must be JSON booleans. Rejections reply `{"type":"error","code":"invalid_command","message":...}` to the sender only.

```json
{"type":"set_input_source","source":"simulated"}
{"type":"set_monitoring","enabled":true}
{"type":"submit_observation","presence":"absent","source":"simulated","observed_at":1764000000.25,"session_id":"<observation_session>"}
{"type":"dismiss_reminder","reminder_id":3}
```

### Snapshot

Every snapshot is complete: `protocol_version`, `instance_id`, `revision`, `behavior_state` (actual) and `display` (rendered, including previews), power/monitoring/mute, `input_source`, `observation` and `observation_session`, `absence_duration_seconds`, `cooldown_remaining_seconds`, `reminder` (`active`, `id`, `stage`, `message`), `standby`, `next_step_seconds`, `settings`, camera fields (`camera_session` for the owner only, `camera_capture_status`, `camera_observation`, `head_direction`, `frames_received`, ...), `robot_display` and the last 100 `events`.

### Camera upload responses

| Status | Meaning |
| --- | --- |
| 200 | `{"accepted":true,"sequence":n}` |
| 400 | Invalid sequence, empty body or undecodable JPEG |
| 408 | Body or processing deadline (`POMO_CAMERA_TIMEOUT_SECONDS`) exceeded |
| 409 | Session expired, not owned, or stale sequence |
| 413 | Body larger than `POMO_CAMERA_MAX_BYTES` |
| 415 | Not `image/jpeg` |
| 429 | Worker busy with another frame |
| 503 | Perception worker unavailable |

The browser uploads sequentially: the next frame is captured only after the previous response plus the frame interval, so `POMO_CAMERA_FPS` is an upper bound, not a guaranteed rate. Failed uploads are not retried.

### Events

The engine keeps the last 100 events in memory (and the page keeps up to 2,000 per instance; see [Control page](#control-page)). Every event is also written to the server log, which is the record used for study timing.

| Group | Events |
| --- | --- |
| Study | `departure_detected`, `reminder_triggered`, `reminder_dismissed`, `reminder_cleared`, `user_returned`, `absence_interrupted`, `standby_entered` |
| State | `state_changed`, `observation_changed`, `display_preview`, `monitoring_changed`, `power_changed`, `sound_changed` |
| Input and connection | `input_source_changed`, `camera_started`, `camera_unavailable`, `observations_invalidated`, `client_connected`, `client_disconnected`, `command_rejected` |

## Robot hardware

The physical Pomo is an M5Stack CoreS3 running `firmware/robot-adapter`, connected to the laptop by USB. Set `POMO_SERIAL_PORT` (on macOS `ls /dev/cu.usbmodem*`; the TinyUSB device name contains the board serial number, so it is stable across USB sockets). Leave it empty to run without hardware.

### Serial protocol

Host to device, one JSON line whenever the relevant fields change, repeated every 2 s as a heartbeat:

```json
{"v":1,"display":"sad","reminder":3,"stage":1,"sound":true,"standby":false,"camera":false}
```

Device to host, binary camera frames while `camera` is true:

```text
"PJPG" | uint32 length (LE) | uint32 sequence (LE) | JPEG bytes      320x240, up to about 5 fps
```

Every line also carries `time` (the laptop's local time) and, once fetched, weather fields `wt`/`wh`/`wl`/`wc`/`wp` from Open-Meteo, which `backend/weather.py` refreshes every 15 minutes without blocking the event loop.

`FrameParser` resynchronises on the `PJPG` magic, discards frames above `POMO_CAMERA_MAX_BYTES`, and drops frames that arrive while the worker is busy. Accepted frames go through `Runtime.robot_frame`, which reuses the `/camera/frame` checks and processor with input source `robot`. After each boot the device prints one line, `pomo-robot boot reset_reason=<n> camera=<0|1>`, which the backend logs.

### Robustness

- A missing or unplugged device is logged once as unavailable and reopened every 2 s; it never stops the server. `robot_display` in the snapshot reports `disabled`, `connected` or `unavailable`.
- The firmware shows `bored` with "No link" after 6 s without a line, and treats the first message after a link starts as silent, so an old reminder is never replayed.
- The device sends no commands; dismissal and other controls stay in the control page.

### Robot pages

Swipe left or right on the robot screen to move between the **face**, **timer**, **weather** (temperature, condition icon, high/low, place), **clock** (time and date), **music** and **video** pages; dots at the bottom show the current page. The robot always goes back to the face when the user leaves, a reminder starts or the link drops, and after 30 s on another page unless music is playing.

The **timer** page runs a Pomodoro cycle on the robot: tap to start or pause, hold for about a second to reset. A ring empties as time runs out and dots count completed focus sessions. Each phase ends with a short chime (respecting mute, never over a reminder); breaks start automatically and the next focus waits for a tap. After the configured number of sessions the break is long. While it runs, the face page shows a small countdown. Durations come from `POMO_TIMER_*`. The timer is local to the robot and does not change the reminder policy.

The **video** page loops an original animation by default, or a GIF/video converted with `tools/make_video.py clip.gif` (optionally `--audio` for its soundtrack) into the gitignored `include/video_user.h`. Tap to play or stop; it stops when you swipe away, leave the desk or a reminder starts.

Tap the music page to play or stop. It plays an original tune by default, or your own audio after `tools/make_music.py song.mp3 --title "..."` and a firmware upload. The generated `include/music_user.h` is gitignored, so audio never enters the repository. Music respects mute and stops when a reminder is spoken. Because the camera owns the internal I2C bus, the firmware reads the FT6336 touch controller through the camera's I2C driver instead of `M5.Touch`; without a working camera it falls back to M5Unified touch.

### Firmware build notes

- TinyUSB CDC (`ARDUINO_USB_MODE=0`) is used because the USB-Serial-JTAG driver in Arduino-ESP32 2.0.x loses bytes at camera data rates.
- Uploads reset the board with a 1200-baud touch; `tools/after_upload.py` then restarts it into the new firmware. If the board is not found, hold reset for about 3 s (green LED) and upload again.
- The camera takes over the internal I2C bus, so the speaker is started first and `M5.update()` (touch and power button polling) is not used while it runs; swipes are read directly from the touch controller (see Robot pages).
- Speech clips in `include/clips.h` (16 kHz mono) are generated from `REMINDER_MESSAGES` by `tools/make_clips.py`; a test fails if they are out of date.

```sh
cd firmware/robot-adapter && pio run -t upload           # build and flash
conda run --name pomo python firmware/robot-adapter/tools/make_clips.py   # regenerate clips after changing reminder text
```

See [firmware/README.md](firmware/README.md) for details and the standalone `display-test/` and `camera-test/` sketches.

## Control page

The page at `/` renders backend state; it has no state machine of its own. Controls stay disabled until a valid snapshot arrives, the connection retries with capped exponential backoff, and a disconnect marks the display stale without queueing commands for replay. On desktop windows the page fits the window and each panel scrolls on its own.

- **Robot panel.** The face, actual state, monitoring, power and mute controls, audio unlock and the active reminder with Dismiss.
- **Controls panel.** Input source; camera preview with face box, capture/detection status and collapsed camera diagnostics (head pose, eyes, quality); simulated input buttons; expression previews; live observation, source, age, absence duration, cooldown, robot link, reminder stage and time to next step; current timing settings.
- **Session log.** Backend events newest first in a Time / Level / Event / Message table. It shows summary counts (departures, first and second reminders, standby, returns) and the median return latency after a reminder; filters (Reminders, State, Input, Warnings) and text search; a Connection tab with this tab's connection journal; Export to a tab-separated file; and Clear view. History is merged by event ID across snapshots, up to 2,000 events per backend instance, beyond the backend's 100. Reloading the page or restarting the backend starts a new history, and Clear view affects only this tab.
- **Layout splitter.** Drag the handle between the top panels and the log, or focus it and use Arrow, Page Up/Down, Home and End, to set the split. It is remembered in browser storage; double-click or Enter resets it.

### Camera troubleshooting

- Open the page at `http://127.0.0.1:8000` (or a validated HTTPS origin) and allow camera access for the site and, on macOS, in **System Settings > Privacy & Security > Camera**. In Chrome, **Settings > Privacy and security > Site settings > Camera** selects the physical camera.
- Keep the tab visible while starting capture; hiding the tab stops capture. Use **Retry camera** after changing permissions, and close other apps using the camera.
- `camera_processor_ready: true` in `/health` confirms the model loaded; `camera_started` confirms a capture request; only successful `/camera/frame` responses confirm frames are flowing. The message under the preview distinguishes capture, playback, encoding and upload errors.
- When the backend runs in WSL, open the page in the host browser at `localhost`; capture always happens in the browser.

## Configuration

Settings come from `.env` in the repository root, overridden by process environment variables. Every value is validated at startup and an invalid value stops the server with a message. Booleans accept `true`/`false` in any case. Changes need a restart; monitoring, power and mute are live controls. `.env.example` lists every setting.

### Server and reminders

| Variable | Default | Meaning |
| --- | --- | --- |
| `POMO_HOST` | `127.0.0.1` | Bind address |
| `POMO_PORT` | `8000` | HTTP/WebSocket port (1 to 65535) |
| `POMO_DEV_CONTROLS` | `true` | Enables simulated input and expression previews |
| `POMO_UNCERTAINTY_SECONDS` | `1` | Continuous fresh uncertainty before it counts as absent |
| `POMO_ABSENCE_SECONDS` | `10` | Leaving to first reminder; greater than 0, at most 3600, at least the tracking-loss grace |
| `POMO_REMINDER_REPEAT_SECONDS` | `300` | First to second reminder |
| `POMO_STANDBY_SECONDS` | `600` | First reminder to standby; must exceed the repeat interval |
| `POMO_REMINDER_COOLDOWN_SECONDS` | `0` | Minimum gap between first reminders of separate departures |
| `POMO_OBSERVATION_TIMEOUT_SECONDS` | `3` | Maximum age of any observation accepted by the policy |
| `POMO_SOUND_ENABLED` | `true` | Initial shared sound preference |
| `POMO_SERIAL_PORT` | empty | CoreS3 serial device; empty disables the robot |
| `POMO_SERIAL_BAUDRATE` | `115200` | Must match the firmware |
| `POMO_WEATHER_ENABLED` | `true` | Fetch weather for the robot's weather page (only with a robot) |
| `POMO_WEATHER_LATITUDE` / `LONGITUDE` | `51.4988` / `-0.1749` | Location (London); the only data sent to Open-Meteo |
| `POMO_WEATHER_PLACE` | `London` | Label on the robot, 1 to 15 plain ASCII characters |
| `POMO_WEATHER_REFRESH_SECONDS` | `900` | Weather refresh interval, at least 300 |
| `POMO_TIMER_FOCUS_MINUTES` | `25` | Robot Pomodoro focus length (0.1 to 180; decimals allowed) |
| `POMO_TIMER_SHORT_BREAK_MINUTES` / `LONG_BREAK_MINUTES` | `5` / `15` | Break lengths |
| `POMO_TIMER_SESSIONS` | `4` | Focus sessions before a long break (1 to 12) |

### Camera transport

| Variable | Default | Meaning |
| --- | --- | --- |
| `POMO_CAMERA_WIDTH` / `POMO_CAMERA_HEIGHT` | `640` / `480` | Capture target and maximum decoded size |
| `POMO_CAMERA_FPS` | `10` | Upper sampling rate |
| `POMO_CAMERA_JPEG_QUALITY` | `0.75` | Browser JPEG quality |
| `POMO_CAMERA_MAX_BYTES` | `524288` | Maximum frame body (also applies to robot frames) |
| `POMO_CAMERA_TIMEOUT_SECONDS` | `3` | Body/processing deadline and capture idle timeout |
| `POMO_CAMERA_STARTUP_SECONDS` | `30` | Allowance for permission and first frame |
| `POMO_CAMERA_MODEL_PATH` | `models/face_landmarker.task` | Model override |

### Detection

| Variable | Default | Meaning |
| --- | --- | --- |
| `POMO_TRACKING_LOSS_GRACE_SECONDS` | `1` | Brief face loss labelled as tracking loss (diagnostic) |
| `POMO_RETURN_SECONDS` | `0.5` | Stable presence that arms the diagnostic baseline |
| `POMO_OBSERVATION_MAX_AGE_SECONDS` | `1` | Maximum age or gap of usable camera evidence |
| `POMO_PERCEPTION_DETECTION_CONFIDENCE` | `0.5` | MediaPipe detection threshold |
| `POMO_PERCEPTION_PRESENCE_CONFIDENCE` | `0.5` | MediaPipe face-presence threshold |
| `POMO_PERCEPTION_TRACKING_CONFIDENCE` | `0.5` | MediaPipe tracking threshold |
| `POMO_PERCEPTION_MIN_BRIGHTNESS` / `MAX_BRIGHTNESS` | `35` / `230` | Usable grayscale mean range |
| `POMO_PERCEPTION_MIN_BLUR_VARIANCE` | `5` | Minimum Laplacian variance; 0 disables |
| `POMO_PERCEPTION_YAW_DEGREES` / `PITCH_DEGREES` | `30` / `25` | Head direction thresholds |
| `POMO_PERCEPTION_HYSTERESIS_DEGREES` | `5` | Direction exit margin |

Eye diagnostics (`POMO_PERCEPTION_EYE_*`): horizontal margin `0.15`, vertical offset threshold `0.08`, vertical signal threshold `0.30` and margin `0.10`, blink threshold `0.55`, full-closure coefficient `0.60`, maximum head yaw `60` and pitch `45` degrees. They affect displayed diagnostics only.

Choose freshness limits above the expected frame interval plus inference latency; results older than the limit are `unavailable` even if frames are still arriving.

## Testing and verification

```sh
conda run --name pomo python -m pytest -q                                  # 297 tests
conda run --name pomo python -m pytest -q tests/test_policy.py             # one file
conda run --name pomo python -m pip check                                  # after dependency changes
node --test tests/test_simulator.js tests/test_simulator.cjs tests/test_camera_client.cjs   # 47 tests
node --check simulator/app.js && node --check simulator/camera.js
sh -n scripts/setup.sh scripts/dev.sh
```

| Suite | Covers |
| --- | --- |
| `test_policy.py` | Thresholds, backdated absence, repeat, standby, dismissal, cooldown, pause/power, freshness; fake clock, no sleeps |
| `test_backend.py`, `test_expression_protocol.py` | Routes, strict commands, revisions, broadcasts, ownership, reconnection |
| `test_camera.py`, `test_detection_integration.py`, `test_perception.py`, `test_eyes.py` | Frame validation, worker lifecycle, normalisation, perception gates (synthetic inputs via `camera_helpers.py`) |
| `test_hardware.py` | Serial messages, frame parsing and resync, reconnect, robot frames, clip freshness (fake port) |
| `test_config.py` | Environment parsing and validation |
| `test_behaviour.py` | Legacy `backend/behaviour.py` regression only; not wired into the app |
| Node suites | Control gating, reconnection, sound deduplication and fallback, camera client lifecycle, session log (history, filters, stats, export) via the fake DOM in `simulator_helpers.cjs` |

A known Starlette/HTTPX deprecation warning appears in the Python run and is documented; do not upgrade unrelated dependencies to hide it. Dated results and limits are recorded in [docs/verification.md](docs/verification.md).

### Manual check

1. Start the backend and confirm **Connected**.
2. Paused: select **Simulated**, enable monitoring (face is `bored` without input), then select **Absent**. Expect `surprised`, `sad` with speech at the absence threshold, a second reminder, then `bored` standby (use the short demo timings above).
3. **Dismiss** stops the cue but keeps `sad`; **Present** returns to `happy` at any stage, even after standby.
4. Pause and try each expression preview; none should speak or create reminders.
5. Power off and wake; monitoring must remain paused.
6. Open a second tab: state is shared and no sound is replayed. Close the producing tab: the robot shows `bored`.
7. Repeat with **Camera** and **Robot camera**, leaving the frame for the absence threshold. With the robot, a dot in its top-right corner shows the camera is streaming.

## Deployment and security

- The server has **no authentication**; any client that can reach it controls the shared robot. Bind to `127.0.0.1` (default) for laptop use.
- For a cloud workspace, start with `POMO_HOST=0.0.0.0 sh scripts/dev.sh` and forward the port privately. The proxy must support WebSocket upgrades and serve at the URL root (no path prefix). Browser camera capture needs HTTPS outside `localhost`.
- With a remote backend, camera frames travel over the network to it; the intended setup runs browser and backend on the same machine. Nothing is recorded.
- Keep `.env`, credentials and any camera recordings out of version control.

## Repository layout

```text
backend/
  __main__.py         Load config, start Uvicorn (single worker)
  app.py              Runtime: commands, locking, tick, ownership, frame endpoint, snapshots
  policy.py           ReminderEngine: states, timers, reminders, events, REMINDER_MESSAGES
  config.py           Validated dataclasses from .env and environment
  camera.py           FrameProcessor: JPEG checks, decode, dedicated worker
  perception.py       Face Landmarker, quality gates, head pose with hysteresis
  eyes.py             Iris and blink diagnostics
  observations.py     Camera observation models
  hardware.py         SerialDisplay and FrameParser for the CoreS3
  weather.py          Open-Meteo weather for the robot's weather page
  behaviour.py        Legacy policy kept for historical tests
simulator/            index.html, app.js (rendering, log, controls), camera.js (capture, uploads), style.css
firmware/
  robot-adapter/      CoreS3 face, speech clips and camera streaming (PlatformIO)
  display-test/       Standalone static face
  camera-test/        Standalone camera preview
models/               Face Landmarker model (downloaded) and its URL/checksum
scripts/              setup.sh, dev.sh, setup_model.py
tests/                pytest suites, Node suites and fake DOM/camera helpers
docs/
  protocol.md         Protocol v10: WebSocket, camera upload and serial contracts
  stack.md            Technology choices
  verification.md     Dated verification evidence and limits
  agent-discussion.md Team and agent proposals, decisions and handoffs
environment.yml       Conda definition with pinned pip packages
.env.example          All settings with defaults
```

Dependencies (pinned in `environment.yml`): Python 3.13, FastAPI 0.162.0, Pydantic 2.14.1, Uvicorn 0.54.0, websockets 17.3, OpenCV contrib 5.0.0.93, MediaPipe 1.2.0, python-dotenv 1.2.4, pyserial, pytest 9.1.1, HTTPX 0.28.1. Rationale is in [docs/stack.md](docs/stack.md). Contributors and agents should read [AGENTS.md](AGENTS.md) and the relevant entries in [docs/agent-discussion.md](docs/agent-discussion.md) before changing shared contracts.

## Project status

Specifications: [Reminders](https://app.notion.com/p/40a66acb0c0380f5bacfc18ac6fa598a), [States Implementation](https://app.notion.com/p/40a66acb0c0380deaf4fd7dbefb28b04), [Debug Logs](https://app.notion.com/p/40a66acb0c0380078ca4ef9dcfaed7e9), [Camera Detection](https://app.notion.com/p/40a66acb0c038013b8b5eb483fa9e18e).

| Phase | Status |
| --- | --- |
| 1. Environment, transport, client | Done |
| 2. Camera input, presence, policy, reminders | Done in software; physical detector evaluation pending |
| Physical integration (CoreS3 face, speech, camera) | Implemented and run on the device; study-distance validation pending |
| 3. Test and validate | Automated suites done; manual and field validation in progress |

### Remaining work

- [ ] Evaluate the detector under poor lighting, distance, head positions and temporary tracking loss; record false reminders and missed events.
- [ ] Test missing/busy cameras, denied permission, resource release and recovery after interruption on real hardware.
- [ ] Validate backend, client, camera and robot restart/disconnect sequences without replaying old reminders.
- [ ] Complete an end-to-end real-camera and robot-camera demonstration: monitoring, absence, reminders, dismissal, standby and return.
- [ ] Validate the robot at the study desk and distance, and record it in `docs/verification.md`.
- [ ] Have teammates test installation and usability; validate Windows/Linux setup and HTTPS/WSS forwarding where used.

### Deferred

Pomodoro and session controls, voice recognition, physical buttons for dismissal, richer expressions and health reminders.
