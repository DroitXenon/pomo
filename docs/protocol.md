# Protocol v2

The backend serves the simulator at `/`, reports health at `/health` and accepts WebSocket connections at `/ws` on the same origin. Use `ws` for HTTP and `wss` for HTTPS.

Version 2 adds the reminder policy, observation ingestion, power/mute controls and bounded debug events. The display identifier `possible_absence` from v1 is replaced by `distraction`. Update the backend and simulator together; the v2 simulator rejects incompatible snapshots.

`GET /health` returns:

```json
{"status":"ok","phase":2,"protocol_version":2}
```

## Transport and State Ownership

Messages are JSON text. The startup configuration limits incoming WebSocket messages to 4,096 bytes; the application also rejects binary messages, oversized command text, malformed JSON, unknown types, extra fields and incorrect field types.

Every connected client controls the same in-memory robot. Backend operations and broadcasts are serialised. Use one backend worker while state remains process-local; state, cooldowns, reminder IDs and events are not persisted across backend restarts.

The last client to submit an accepted observation owns the current observation source. If that client disconnects or fails a broadcast send, the backend invalidates its observations, clears any reminder and broadcasts the resulting state. A viewer disconnect does not clear another client's input. Prefer one active observation producer at a time.

The `camera` source is a trusted metadata label, not an authenticated device identity. This development server has no authentication. Restrict access through localhost or private workspace controls. No physical camera capture or camera-processing adapter is implemented by this protocol.

## Complete State Snapshot

A client receives the current complete snapshot on connection. Every accepted command broadcasts a new snapshot to all clients. The 250 ms backend timer also publishes changes to policy state, elapsed-time diagnostics and debug events.

The following example shows the complete shape; instance/session IDs, revision and event contents vary:

```json
{
  "type": "state",
  "protocol_version": 2,
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
  "events": []
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

## Strict Commands

Booleans must be JSON booleans, not strings or numbers. Commands accept only the fields shown.

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

### Observation ingestion

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
- `source`: `simulated` or `camera`.
- `observed_at`: a finite JSON number in Unix seconds.
- `session_id`: a non-empty string of at most 100 characters, matching the current session.
- Observations require power on and monitoring enabled.
- Source timestamps must be strictly newer than the previous accepted timestamp in the session, including when changing source.
- At receipt, an observation must be younger than `observation_timeout_seconds` and no more than one second in the future. Age equal to the timeout is already expired.
- Freshness after receipt uses a monotonic clock and includes the age the observation already had at receipt.

With `POMO_DEV_CONTROLS=false`, simulated observations and both preview commands are rejected. Camera-labelled observations remain available for a future real adapter; this flag does not implement or authenticate camera capture. Monitoring, power, mute and dismissal controls remain available.

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

## Camera Adapter Integration

The ingestion endpoint accepts metadata only. A future camera processor should:

1. Connect to `/ws` and read a protocol-v2 snapshot.
2. Power on if necessary, enable monitoring if required, and wait for the resulting snapshot with its current session token.
3. Convert each fresh detector result to an allowed presence value and its actual Unix observation timestamp.
4. Send observations while continuing to receive snapshots; copy the latest token after lifecycle changes. Respect power/monitoring state and discard buffered frames on disconnect.
5. Send `presence: "unavailable"` for lost camera input. Stop treating unavailable or uncertain input as absence.

Example packet construction after receiving the latest snapshot:

```python
import json
import time

packet = {
    "type": "submit_observation",
    "presence": "present",  # Replace with this frame's detector result.
    "source": "camera",
    "observed_at": time.time(),
    "session_id": snapshot["observation_session"],
}
ws.send(json.dumps(packet))
```

This example defines adapter communication; it does not capture camera frames.

## Debug Events and Errors

Events include an increasing integer `id`, UTC ISO-8601 `at`, `level` (`info`, `warning` or `error`), `kind` and bounded `message`. They record transitions, reminder activity, source changes, lifecycle changes, connections and command rejections. Unchanged observation heartbeats do not add log entries.

The backend keeps only the latest 100 events in memory and writes event summaries through Python logging. The simulator displays the bounded backend log separately from its local connection journal. Clearing the browser log hides existing entries in that tab; it does not delete shared backend history.

Rejected commands return:

```json
{"type":"error","code":"invalid_command","message":"Explanation"}
```

Rejected commands do not apply the requested policy operation or directly increment revision. Rejection itself is recorded as a debug event. The timer may subsequently publish logs or independently advance elapsed-time policy state.

No frame/image/video fields are accepted. Do not send or persist raw camera media in protocol messages or logs.

## Reconnection and Sound Delivery

The simulator retries after 1, 2, 4 and 8 seconds, then at most every 10 seconds. Controls remain disabled until a valid snapshot arrives. While disconnected, the previous display is marked stale, simulated-input heartbeats and any local tone stop, and commands are not queued.

On reconnect, restore the current snapshot and require a new simulated-input selection. The first snapshot never plays an old reminder sound. Subsequent newly observed active reminders may play one short cue per audio-enabled tab, identified by `instance_id:reminder.id`. Manual previews, mute/unmute and later snapshots of the same reminder do not replay sound.

A backend restart creates a new instance ID, resets reminder/event counters and revision, powers the simulated robot on with monitoring paused, and clears observations/cooldowns. Sound preference resets to the configured startup default.

## Configuration and Deterministic Checks

| Environment setting | Default | Constraint |
| --- | --- | --- |
| `POMO_ABSENCE_SECONDS` | `5` | Finite, greater than zero |
| `POMO_REMINDER_COOLDOWN_SECONDS` | `30` | Finite, non-negative |
| `POMO_OBSERVATION_TIMEOUT_SECONDS` | `3` | Finite, greater than zero |
| `POMO_SOUND_ENABLED` | `false` | Startup preference; browser audio still requires a user gesture |
| `POMO_DEV_CONTROLS` | `true` | Gates simulated input and manual expression previews |

Tests can construct `create_app(config=PolicyConfig(...), clock=fake_monotonic, wall_clock=fake_epoch, run_ticker=False)` and explicitly await `app.state.runtime.tick()`. Pure policy tests inject both clocks into `ReminderEngine`. No test-only command for advancing time is exposed over the WebSocket.

## Task Sources

- [Reminders](https://app.notion.com/p/40a66acb0c0380f5bacfc18ac6fa598a)
- [States Implementation](https://app.notion.com/p/40a66acb0c0380deaf4fd7dbefb28b04)
- [Debug Logs](https://app.notion.com/p/40a66acb0c0380078ca4ef9dcfaed7e9)
