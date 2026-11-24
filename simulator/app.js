"use strict";

const $ = (id) => document.getElementById(id);
const displayLabels = {
  happy: "Happy",
  idle: "Idle",
  sad: "Sad",
  surprised: "Surprised",
  bored: "Bored"
};
const presenceLabels = {present: "Present", absent: "Absent", uncertain: "Uncertain", unavailable: "Unavailable"};
const sourceLabels = {none: "None", simulated: "Simulated", camera: "Camera"};
let socket, retryTimer, connectTimer, inputTimer;
let attempts = 0, stopped = false, connected = false, protocolBlocked = false;
let state = null, simulatedInput = null, clearedEventsThrough = 0;
let audioContext = null, audioIssue = "", currentTone = null;
const seenReminders = new Set();
const camera = new CameraController($("camera-preview"), $("camera-status"), (message) => {
  const reason = typeof message === "string" ? message.replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, 300) : "Camera capture failed. Retry the camera when ready.";
  feedback(reason);
  log(`Camera: ${reason}`);
  if (connected && state?.input_source === "camera" && state.camera_session) send({type: "camera_failed"}, false);
});

function setText(id, text) {
  if ($(id).textContent !== text) $(id).textContent = text;
}

function log(message) {
  const item = document.createElement("li");
  item.textContent = `${new Date().toLocaleTimeString()}  ${message}`;
  $("journal").prepend(item);
  while ($("journal").children.length > 100) $("journal").lastChild.remove();
}

function feedback(message) {
  setText("feedback", message);
}

function seconds(value) {
  return `${Math.max(0, value).toFixed(1)}s`;
}

function validSnapshot(next) {
  const finite = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const positive = (value) => finite(value) && value > 0;
  const cameraSettings = object(next?.camera_settings) &&
    ["width", "height", "fps", "jpeg_quality", "max_bytes", "timeout_seconds"].every((key) => positive(next.camera_settings[key])) &&
    next.camera_settings.jpeg_quality <= 1;
  return object(next) && next.protocol_version === 10 &&
    typeof next.instance_id === "string" && next.instance_id.length > 0 &&
    Number.isSafeInteger(next.revision) && next.revision >= 0 &&
    ["dev_controls", "powered_on", "monitoring_enabled", "muted"].every((key) => typeof next[key] === "boolean") &&
    Object.hasOwn(displayLabels, next.display) && Object.hasOwn(displayLabels, next.behavior_state) &&
    ["available", "unavailable"].includes(next.camera_status) &&
    ["camera", "simulated", "robot"].includes(next.input_source) &&
    ["paused", "starting", "available", "unavailable"].includes(next.camera_capture_status) &&
    typeof next.camera_processor_ready === "boolean" && cameraSettings &&
    (next.camera_session === null || (typeof next.camera_session === "string" && next.camera_session.length > 0 &&
      next.powered_on && next.monitoring_enabled && next.input_source === "camera" && next.camera_processor_ready)) &&
    typeof next.observation_session === "string" && next.observation_session.length > 0 &&
    finite(next.absence_duration_seconds) && finite(next.cooldown_remaining_seconds) &&
    typeof next.standby === "boolean" && ["disabled", "connected", "unavailable"].includes(next.robot_display) && (next.next_step_seconds === null || finite(next.next_step_seconds)) &&
    object(next.observation) && Object.hasOwn(presenceLabels, next.observation.presence) &&
    object(next.camera_observation) && next.camera_observation.presence === next.observation.presence &&
    Object.hasOwn(sourceLabels, next.observation.source) &&
    (next.observation.age_seconds === null || finite(next.observation.age_seconds)) &&
    (next.observation.observed_at === null || finite(next.observation.observed_at)) &&
    object(next.reminder) && typeof next.reminder.active === "boolean" &&
    Number.isSafeInteger(next.reminder.id) && next.reminder.id >= 0 &&
    [0, 1, 2].includes(next.reminder.stage) &&
    (next.reminder.message === null || typeof next.reminder.message === "string") &&
    object(next.settings) && ["absence_seconds", "cooldown_seconds", "observation_timeout_seconds",
      "repeat_seconds", "standby_seconds"].every((key) => finite(next.settings[key])) &&
    Array.isArray(next.events);
}

function controls(isConnected) {
  $("monitor").disabled = !isConnected || !state?.powered_on ||
    (!state.monitoring_enabled && state.input_source !== "simulated" && !state.camera_processor_ready);
  $("power").disabled = !isConnected;
  $("sound").disabled = !isConnected;
  $("dismiss").disabled = !isConnected || !state?.reminder.active;
  $("audio-unlock").disabled = !isConnected;
  const canSimulate = isConnected && state?.dev_controls && state.powered_on && state.monitoring_enabled && state.input_source === "simulated";
  document.querySelectorAll("[data-observation]").forEach((button) => { button.disabled = !canSimulate; });
  const canPreview = isConnected && state?.dev_controls && state.powered_on && !state.monitoring_enabled;
  document.querySelectorAll("[data-preview]").forEach((button) => { button.disabled = !canPreview; });
  $("clear-preview").disabled = !canPreview;
  document.querySelectorAll("[data-source]").forEach((button) => {
    button.disabled = !isConnected || !state?.powered_on || state.monitoring_enabled ||
      (button.dataset.source === "simulated" && !state.dev_controls) ||
      (button.dataset.source === "robot" && state.robot_display === "disabled");
  });
  $("retry-camera").disabled = !isConnected || !state?.powered_on || !state.monitoring_enabled ||
    state.input_source === "simulated" || !state.camera_processor_ready || state.camera_capture_status !== "unavailable";
}

function stopSimulation() {
  clearInterval(inputTimer);
  inputTimer = null;
  simulatedInput = null;
}

function updateSimulationStatus() {
  let label;
  if (!connected) label = "Connect to the backend to simulate input.";
  else if (!state.dev_controls) label = "Simulated inputs are disabled by the backend.";
  else if (state.input_source !== "simulated") label = "Select simulated input while monitoring is paused.";
  else if (!state.powered_on) label = "Wake Pomo to use simulated input.";
  else if (!state.monitoring_enabled) label = "Enable monitoring, then select an input.";
  else if (simulatedInput) label = `Sending simulated ${presenceLabels[simulatedInput].toLowerCase()} observations.`;
  else label = "Select an input. It stops when this tab disconnects or monitoring pauses.";
  setText("simulation-status", label);
  document.querySelectorAll("[data-observation]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.observation === simulatedInput));
  });
}

function stopTone() {
  try { if (window.speechSynthesis?.speaking || window.speechSynthesis?.pending) window.speechSynthesis.cancel(); } catch {}
  if (!currentTone) return;
  const tone = currentTone;
  currentTone = null;
  try { tone.oscillator.stop(); } catch {}
  try { tone.oscillator.disconnect(); tone.gain.disconnect(); } catch {}
}

function audioStatus() {
  const muted = state?.muted ?? true;
  const ready = audioContext?.state === "running";
  const robot = state?.robot_display === "connected";
  $("audio-unlock").hidden = muted || ready || robot;
  if (muted) setText("audio-status", "Sound muted");
  else if (robot) setText("audio-status", "Sound on · the robot speaks reminders");
  else if (audioIssue) setText("audio-status", audioIssue);
  else if (!ready) setText("audio-status", "Sound on");
  else setText("audio-status", "Sound on in this tab");
}

async function unlockAudio() {
  audioIssue = "";
  try {
    const Audio = window.AudioContext || window.webkitAudioContext;
    if (!Audio) throw new Error("unsupported");
    audioContext ??= new Audio();
    if (audioContext.state !== "running") await audioContext.resume();
    if (audioContext.state !== "running") throw new Error("permission");
  } catch {
    audioIssue = "Audio unavailable in this tab. Visual reminders still work.";
  }
  audioStatus();
}

function speakCue(message) {
  const synth = window.speechSynthesis;
  const Utterance = window.SpeechSynthesisUtterance;
  if (!synth || typeof Utterance !== "function" || typeof message !== "string" || !message) return false;
  try {
    synth.cancel();
    const utterance = new Utterance(message.slice(0, 300));
    utterance.lang = "en-GB";
    utterance.rate = 0.95;
    synth.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

function playCue(message) {
  // Speech still needs the tab's audio unlock gesture, like the fallback tone.
  if (audioContext?.state === "running" && speakCue(message)) return;
  if (!audioContext || audioContext.state !== "running") {
    audioStatus();
    return;
  }
  stopTone();
  try {
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    const now = audioContext.currentTime;
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(660, now);
    gain.gain.setValueAtTime(0, now);
    gain.gain.linearRampToValueAtTime(0.035, now + 0.025);
    gain.gain.linearRampToValueAtTime(0, now + 0.25);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    const tone = {oscillator, gain};
    currentTone = tone;
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
      if (currentTone === tone) currentTone = null;
    };
    oscillator.start(now);
    oscillator.stop(now + 0.26);
  } catch {
    stopTone();
    audioIssue = "Audio unavailable in this tab. Visual reminders still work.";
    audioStatus();
  }
}

// The backend sends only its latest 100 events, so the page keeps a longer
// per-instance history for this tab (not persisted, not shared).
const EVENT_HISTORY_LIMIT = 2000, EVENT_ROWS_LIMIT = 500;
const eventHistory = new Map();
let historyInstance = null, logFilter = "all", logQuery = "", lastLogSignature = "";
const eventGroups = {
  study: new Set(["departure_detected", "reminder_triggered", "reminder_dismissed", "reminder_cleared",
    "standby_entered", "user_returned", "absence_interrupted"]),
  state: new Set(["state_changed", "observation_changed", "display_preview", "monitoring_changed",
    "power_changed", "sound_changed"]),
  input: new Set(["camera_started", "camera_unavailable", "input_source_changed", "observations_invalidated",
    "client_connected", "client_disconnected", "command_rejected"])
};

function validEvent(entry) {
  return entry && Number.isSafeInteger(entry.id) && typeof entry.at === "string" &&
    typeof entry.kind === "string" && typeof entry.message === "string" &&
    ["info", "warning", "error"].includes(entry.level);
}

function visibleHistory() {
  return [...eventHistory.values()].filter((entry) => entry.id > clearedEventsThrough);
}

function matchesFilter(entry) {
  if (logFilter === "warnings" && entry.level === "info") return false;
  if (eventGroups[logFilter] && !eventGroups[logFilter].has(entry.kind)) return false;
  return !logQuery || `${entry.kind} ${entry.message}`.toLowerCase().includes(logQuery);
}

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

function renderStats(entries) {
  const count = (kind, text) => entries.filter((entry) => entry.kind === kind && (!text || entry.message.includes(text))).length;
  const latencies = entries.filter((entry) => entry.kind === "user_returned")
    .map((entry) => /returned ([\d.]+)s after reminder/.exec(entry.message)).filter(Boolean).map((match) => Number(match[1]));
  setText("stat-departures", String(count("departure_detected")));
  setText("stat-first", String(count("reminder_triggered", "(first)")));
  setText("stat-second", String(count("reminder_triggered", "(second)")));
  setText("stat-standby", String(count("standby_entered")));
  setText("stat-returns", String(count("user_returned")));
  const middle = median(latencies);
  setText("stat-latency", middle === null ? "—" : `${middle.toFixed(1)} s`);
}

function eventRow(entry) {
  const item = document.createElement("li");
  item.dataset.level = entry.level;
  const date = new Date(entry.at);
  const cells = [Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString(), entry.level, entry.kind, entry.message];
  ["time", "level", "kind", "message"].forEach((name, index) => {
    const cell = document.createElement("span");
    cell.className = `log-${name}`;
    cell.textContent = cells[index];
    item.append(cell);
  });
  item.title = `${entry.at}  ${entry.kind}: ${entry.message}`;
  return item;
}

function renderEvents(events) {
  if (state && historyInstance !== state.instance_id) {
    eventHistory.clear();
    historyInstance = state.instance_id;
  }
  for (const entry of events.slice(-100)) if (validEvent(entry)) eventHistory.set(entry.id, entry);
  while (eventHistory.size > EVENT_HISTORY_LIMIT) eventHistory.delete(eventHistory.keys().next().value);
  const lastId = Math.max(0, ...eventHistory.keys());
  const signature = `${historyInstance}:${lastId}:${eventHistory.size}:${clearedEventsThrough}:${logFilter}:${logQuery}`;
  if (signature === lastLogSignature) return;
  lastLogSignature = signature;
  const entries = visibleHistory();
  const shown = entries.filter(matchesFilter);
  $("events").replaceChildren(...shown.slice(-EVENT_ROWS_LIMIT).reverse().map(eventRow));
  setText("log-count", !entries.length ? "No events" :
    shown.length === entries.length ? `${entries.length} event${entries.length === 1 ? "" : "s"}` :
      `${shown.length} of ${entries.length} events`);
  $("export-log").disabled = !entries.length;
  renderStats(entries);
}

function exportLog() {
  const entries = visibleHistory();
  if (!entries.length || typeof Blob !== "function" || !window.URL?.createObjectURL) return;
  const clean = (text) => String(text).replace(/[\t\r\n]+/g, " ");
  const lines = ["time\tlevel\tevent\tmessage", ...entries.map((entry) =>
    [entry.at, entry.level, entry.kind, entry.message].map(clean).join("\t"))];
  const url = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], {type: "text/tab-separated-values"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = `pomo-log-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.tsv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function clearOverlay() {
  const overlay = $("face-overlay");
  const context = overlay.getContext?.("2d");
  context?.clearRect(0, 0, overlay.width, overlay.height);
}

function stopCamera(message) {
  camera.stop();
  clearOverlay();
  if (message) setText("camera-status", message);
}

function renderCameraDiagnostics(next) {
  const raw = next.camera_observation;
  const observation = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : null;
  const statuses = {
    paused: "Detection paused", unavailable: "Camera unavailable · reminders suspended",
    awaiting_face: "Waiting for a visible face before monitoring absence",
    confirming_face: "Confirming face presence", present: "Face visible",
    tracking_loss: next.camera_armed ? "Face briefly lost · waiting before counting absence" : "Waiting for a visible face",
    possible_absence: "No face detected · waiting for a visible face",
    absence: next.reminder.active ? "Face not detected · reminder active" : "Face not detected · monitoring absence",
    uncertain: "Input uncertain · reminders suspended", stale: "Input stale · reminders suspended"
  };
  const uncertainReasons = {
    low_light: "Image too dark · detection paused", overexposed: "Image too bright · detection paused",
    low_detail_or_blur: "Image unclear or blurry · detection paused",
    invalid_landmarks: "Face tracking uncertain · detection paused",
    stale: "Detection result too old · detection paused"
  };
  let detectionStatus;
  if (next.input_source === "simulated") detectionStatus = "Camera detection off · simulated input selected";
  else if (!next.powered_on || !next.monitoring_enabled) detectionStatus = "Detection paused";
  else if (next.camera_capture_status === "starting")
    detectionStatus = next.input_source === "robot" ? "Waiting for robot camera frames" : "Waiting for camera frames";
  else if (next.camera_tracking_status === "uncertain" && Object.hasOwn(uncertainReasons, observation?.reason))
    detectionStatus = uncertainReasons[observation.reason];
  else detectionStatus = (Object.hasOwn(statuses, next.camera_tracking_status) ? statuses[next.camera_tracking_status] : null) ||
      (next.camera_status === "unavailable" ? statuses.unavailable : "Waiting for observations");
  setText("detection-status", detectionStatus);
  setText("face-presence", Object.hasOwn(presenceLabels, observation?.presence) ? presenceLabels[observation.presence] : "Unavailable");
  setText("head-direction", typeof next.head_direction === "string" ? next.head_direction.slice(0, 60) : "unknown");
  const pose = observation?.head_pose;
  setText("head-angles", pose && [pose.yaw, pose.pitch, pose.roll].every(Number.isFinite) ?
    `Yaw ${pose.yaw.toFixed(0)}° / pitch ${pose.pitch.toFixed(0)}° / roll ${pose.roll.toFixed(0)}°` : "—");
  const reasons = {usable: "Usable", no_face: "No face detected", low_light: "Low light",
    overexposed: "Overexposed", low_detail_or_blur: "Low detail or blur", invalid_landmarks: "Uncertain landmarks"};
  setText("image-quality", Object.hasOwn(reasons, observation?.reason) ? reasons[observation.reason] : "—");
  setText("camera-armed", typeof next.camera_armed === "boolean" ? (next.camera_armed ? "Confirmed" : "Waiting for a visible face") : "—");
  setText("camera-absence", Number.isFinite(next.camera_absence_duration_seconds) && next.camera_absence_duration_seconds >= 0 ? seconds(next.camera_absence_duration_seconds) : "—");
  setText("frames-received", Number.isSafeInteger(next.frames_received) && next.frames_received >= 0 ? String(next.frames_received) : "0");
  const scores = observation?.blendshapes || {};
  const formatScore = (name) => `${name}: ${Number.isFinite(scores[name]) ? scores[name].toFixed(2) : "—"}`;
  const eyes = observation?.eye_movement;
  const formatEye = (name, eye) => `${name}: ${typeof eye?.direction === "string" ? eye.direction.slice(0, 30) : "unknown"}`;
  const formatBlink = (name, eye) => `${name}: ${Number.isFinite(eye?.blink_score) ? eye.blink_score.toFixed(2) : "—"}`;
  setText("eye-movement", [formatEye("eyeLeft", eyes?.eyeLeft), formatEye("eyeRight", eyes?.eyeRight),
    formatBlink("eyeBlinkLeft", eyes?.eyeLeft), formatBlink("eyeBlinkRight", eyes?.eyeRight)].join(" · "));
  setText("eye-vertical-signals", ["eyeLookUpLeft", "eyeLookDownLeft", "eyeLookUpRight", "eyeLookDownRight"].map(formatScore).join(" · "));
  const formatOffset = (name, eye) => `${name}: ${Number.isFinite(eye?.vertical_offset) ? eye.vertical_offset.toFixed(3) : "—"}`;
  setText("eye-vertical-offsets", [formatOffset("eyeLeft", eyes?.eyeLeft), formatOffset("eyeRight", eyes?.eyeRight)].join(" · "));
  setText("mouth-movement", ["jawOpen", "mouthSmileLeft", "mouthSmileRight"].map(formatScore).join(" · "));

  clearOverlay();
  const box = observation?.face_box;
  const frame = next.last_frame;
  const overlay = $("face-overlay");
  const context = overlay.getContext?.("2d");
  const fresh = next.observation.source === "camera" && next.observation.age_seconds !== null &&
    next.observation.age_seconds < next.settings.observation_timeout_seconds;
  if (context && next.camera_session && next.input_source === "camera" && next.powered_on && next.monitoring_enabled &&
      fresh && next.camera_status === "available" && observation?.presence === "present" &&
      Array.isArray(box) && box.length === 4 && box.every((value) => Number.isFinite(value) && value >= 0 && value <= 1) &&
      box[2] > box[0] && box[3] > box[1] && Number.isFinite(frame?.width) && frame.width > 0 &&
      Number.isFinite(frame?.height) && frame.height > 0) {
    const scale = Math.min(overlay.width / frame.width, overlay.height / frame.height);
    const offsetX = (overlay.width - frame.width * scale) / 2;
    const offsetY = (overlay.height - frame.height * scale) / 2;
    context.strokeStyle = "#fff";
    context.lineWidth = 2;
    context.strokeRect(offsetX + box[0] * frame.width * scale, offsetY + box[1] * frame.height * scale,
      (box[2] - box[0]) * frame.width * scale, (box[3] - box[1]) * frame.height * scale);
  }
}

function render(next, initialSnapshot) {
  const previous = state;
  if (previous && previous.instance_id !== next.instance_id) clearedEventsThrough = 0;
  state = next;
  if (!state.powered_on || !state.monitoring_enabled || !state.dev_controls || state.input_source !== "simulated") stopSimulation();
  if (!previous || previous.display !== state.display) $("screen").dataset.display = state.display;
  setText("state-title", displayLabels[state.display]);
  const previewing = state.display !== state.behavior_state;
  $("preview-status").hidden = !previewing;
  setText("preview-status", previewing ? `Expression preview · Actual state: ${displayLabels[state.behavior_state]}` : "");
  setText("monitor", state.monitoring_enabled ? "Pause monitoring" : "Enable monitoring");
  $("monitor").setAttribute("aria-pressed", String(state.monitoring_enabled));
  setText("power", state.powered_on ? "Power off" : "Wake Pomo");
  setText("monitor-status", !state.powered_on ? "Powered off · monitoring stopped" : state.monitoring_enabled ? "Monitoring enabled" : "Monitoring paused");
  setText("sound", state.muted ? "Unmute sound" : "Mute sound");
  $("sound").setAttribute("aria-pressed", String(state.muted));
  $("reminder-panel").hidden = !state.reminder.active;
  setText("reminder-message", state.reminder.active ? state.reminder.message || "Take a moment to return when you’re ready." : "");
  setText("observation-current", presenceLabels[state.observation.presence]);
  setText("observation-source", sourceLabels[state.observation.source]);
  setText("input-status", state.camera_status === "available" ? "Available" : "Unavailable");
  $("camera-panel").hidden = state.input_source === "simulated";
  $("camera-view").hidden = state.input_source !== "camera";
  $("simulation-panel").hidden = state.input_source !== "simulated";
  document.querySelectorAll("[data-source]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.source === state.input_source));
  });
  setText("source-status", state.monitoring_enabled ? "Pause monitoring to change the input source." :
    state.input_source !== "simulated" && !state.camera_processor_ready ? "Camera processor unavailable. Simulated input is available for development." :
    state.input_source === "robot" && state.robot_display !== "connected" ? "Robot not connected. Check the USB cable, then enable monitoring." :
    !state.dev_controls ? "Camera input selected. Development simulation is disabled." : "Select a source, then enable monitoring.");
  $("retry-camera").hidden = state.input_source === "simulated" || !state.powered_on || !state.monitoring_enabled ||
    !state.camera_processor_ready || state.camera_capture_status !== "unavailable";
  camera.update(state);
  renderCameraDiagnostics(state);
  setText("absence-duration", seconds(state.absence_duration_seconds));
  setText("cooldown-status", seconds(state.cooldown_remaining_seconds));
  setText("robot-display", {disabled: "Not configured", connected: "Connected", unavailable: "Unavailable"}[state.robot_display]);
  const stages = {0: "None", 1: "First", 2: "Second"};
  setText("reminder-stage", state.standby ? "Standby" : stages[state.reminder.stage]);
  setText("next-step", state.next_step_seconds === null ? "—" : seconds(state.next_step_seconds));
  setText("observation-age", state.observation.age_seconds === null ? "—" : seconds(state.observation.age_seconds));
  setText("policy-settings", `First reminder ${seconds(state.settings.absence_seconds)} after leaving · Second ${seconds(state.settings.repeat_seconds)} later · Standby ${seconds(state.settings.standby_seconds)} after the first` +
    (state.settings.cooldown_seconds > 0 ? ` · Cooldown ${seconds(state.settings.cooldown_seconds)}` : "") +
    ` · Input expires after ${seconds(state.settings.observation_timeout_seconds)}`);
  setText("behavior-state", displayLabels[state.behavior_state]);
  setText("revision", String(state.revision));
  setText("previews-status", !state.dev_controls ? "Expression previews are disabled by the backend." : state.monitoring_enabled ? "Pause monitoring to preview expressions." : "Display previews do not trigger reminders or sound.");
  document.querySelectorAll("[data-preview]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.preview === state.display));
  });
  renderEvents(state.events);
  controls(true);
  updateSimulationStatus();
  audioStatus();
  if (state.muted || !state.reminder.active || !state.powered_on || !state.monitoring_enabled) stopTone();
  if (state.reminder.active) {
    const key = `${state.instance_id}:${state.reminder.id}`;
    const unseen = !seenReminders.has(key);
    seenReminders.add(key);
    while (seenReminders.size > 100) seenReminders.delete(seenReminders.values().next().value);
    if (unseen && !initialSnapshot && !state.muted && state.powered_on && state.monitoring_enabled &&
      state.robot_display !== "connected") playCue(state.reminder.message);
  }
}

function send(command, clearFeedback = true) {
  if (!connected || !socket || socket.readyState !== WebSocket.OPEN) return false;
  if (clearFeedback) feedback("");
  try {
    socket.send(JSON.stringify(command));
    return true;
  } catch {
    feedback("The command could not be sent. Reconnect and try again.");
    socket.close();
    return false;
  }
}

function submitSimulatedObservation(presence) {
  if (!connected || !state?.dev_controls || !state.powered_on || !state.monitoring_enabled || state.input_source !== "simulated") return false;
  return send({
    type: "submit_observation",
    presence,
    source: "simulated",
    observed_at: Date.now() / 1000,
    session_id: state.observation_session
  }, false);
}

function simulate(presence) {
  stopSimulation();
  feedback("");
  if (!submitSimulatedObservation(presence)) return;
  if (presence !== "unavailable") {
    simulatedInput = presence;
    const interval = Math.max(25, Math.min(500, state.settings.observation_timeout_seconds * 1000 / 3));
    inputTimer = setInterval(() => {
      if (!submitSimulatedObservation(simulatedInput)) {
        stopSimulation();
        updateSimulationStatus();
      }
    }, interval);
  }
  updateSimulationStatus();
}

function connect() {
  if (stopped) return;
  clearTimeout(retryTimer);
  connected = false;
  protocolBlocked = false;
  controls(false);
  setText("connection", "Connecting");
  $("connection").dataset.connected = "false";
  if (state) setText("monitor-status", "Connecting · displayed state may be stale");
  updateSimulationStatus();
  const url = new URL("ws", window.location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(url);
  socket = ws;
  let receivedSnapshot = false;
  connectTimer = setTimeout(() => ws.close(), 10000);
  ws.onmessage = ({data}) => {
    if (socket !== ws || stopped) return;
    let message;
    try { message = JSON.parse(data); } catch {
      feedback("Invalid backend message. Waiting for a valid snapshot.");
      log("Invalid backend message");
      return;
    }
    if (message?.type === "state") {
      if (!validSnapshot(message)) {
        connected = false;
        controls(false);
        stopSimulation();
        stopCamera("Camera stopped · incompatible backend");
        stopTone();
        protocolBlocked = true;
        feedback("Backend protocol mismatch. Update the backend and refresh this page.");
        log("Incompatible state snapshot");
        ws.close();
        return;
      }
      if (receivedSnapshot && state?.instance_id === message.instance_id && message.revision < state.revision) return;
      clearTimeout(connectTimer);
      attempts = 0;
      connected = true;
      setText("connection", "Connected");
      $("connection").dataset.connected = "true";
      render(message, !receivedSnapshot);
      if (!receivedSnapshot) log("Connected · current state restored");
      receivedSnapshot = true;
    } else if (message?.type === "error") {
      stopSimulation();
      updateSimulationStatus();
      feedback(typeof message.message === "string" ? message.message.slice(0, 500) : "The backend rejected the command.");
      log(`Command rejected: ${typeof message.code === "string" ? message.code : "unknown"}`);
    } else {
      log("Unrecognised backend message");
    }
  };
  ws.onerror = () => ws.close();
  ws.onclose = () => {
    if (socket !== ws) return;
    clearTimeout(connectTimer);
    connected = false;
    controls(false);
    stopSimulation();
    stopCamera("Camera stopped · backend disconnected");
    setText("detection-status", "Disconnected · observations may be stale");
    stopTone();
    setText("connection", protocolBlocked ? "Incompatible" : "Disconnected");
    $("connection").dataset.connected = "false";
    setText("monitor-status", "Disconnected · displayed state may be stale");
    updateSimulationStatus();
    if (!stopped && !protocolBlocked) {
      const delay = Math.min(1000 * 2 ** attempts++, 10000);
      log(`Disconnected; retrying in ${delay / 1000}s`);
      retryTimer = setTimeout(connect, delay);
    }
  };
}

$("monitor").onclick = () => {
  if (!state) return;
  stopSimulation();
  if (state.monitoring_enabled) stopCamera("Camera paused");
  send({type: "set_monitoring", enabled: !state.monitoring_enabled});
};
$("power").onclick = () => {
  if (!state) return;
  stopSimulation();
  stopCamera("Camera stopped");
  send({type: "set_power", enabled: !state.powered_on});
};
$("retry-camera").onclick = () => {
  stopCamera("Retrying camera…");
  send({type: "set_monitoring", enabled: true});
};
$("dismiss").onclick = () => {
  if (state?.reminder.active) send({type: "dismiss_reminder", reminder_id: state.reminder.id});
};
$("sound").onclick = async () => {
  if (!state || !connected) return;
  const mute = !state.muted;
  if (mute) stopTone();
  else await unlockAudio();
  send({type: "set_muted", muted: mute});
};
$("audio-unlock").onclick = () => unlockAudio();
document.querySelectorAll("[data-observation]").forEach((button) => {
  button.onclick = () => simulate(button.dataset.observation);
});
document.querySelectorAll("[data-source]").forEach((button) => {
  button.onclick = () => {
    if (!state || state.monitoring_enabled || !state.powered_on) return;
    stopSimulation();
    stopCamera("Camera paused");
    send({type: "set_input_source", source: button.dataset.source});
  };
});
document.querySelectorAll("[data-preview]").forEach((button) => {
  button.onclick = () => send({type: "preview_display", display: button.dataset.preview});
});
$("clear-preview").onclick = () => send({type: "clear_preview"});
$("clear").onclick = () => {
  $("journal").replaceChildren();
  clearedEventsThrough = Math.max(clearedEventsThrough, 0, ...eventHistory.keys(),
    ...(state?.events || []).map((entry) => Number.isSafeInteger(entry.id) ? entry.id : 0));
  renderEvents(state?.events || []);
};
$("export-log").onclick = exportLog;
document.querySelectorAll("[data-filter]").forEach((button) => {
  button.onclick = () => {
    logFilter = button.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
    renderEvents(state?.events || []);
  };
});
$("log-search").oninput = () => {
  logQuery = String($("log-search").value || "").trim().toLowerCase().slice(0, 100);
  renderEvents(state?.events || []);
};
for (const [tab, view, other, otherView] of [["tab-events", "events-view", "tab-journal", "journal-view"],
  ["tab-journal", "journal-view", "tab-events", "events-view"]]) {
  $(tab).onclick = () => {
    $(tab).setAttribute("aria-selected", "true");
    $(other).setAttribute("aria-selected", "false");
    $(view).hidden = false;
    $(otherView).hidden = true;
    $("log-filters").hidden = $("log-search").hidden = tab === "tab-journal";
  };
}
window.addEventListener("pagehide", () => {
  stopped = true;
  connected = false;
  clearTimeout(retryTimer);
  clearTimeout(connectTimer);
  stopSimulation();
  stopCamera("Camera stopped");
  stopTone();
  socket?.close();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    stopped = false;
    connect();
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && camera.session) {
    camera.fail("Pomo tab hidden. Keep this tab visible and retry the camera.", camera.generation);
  }
});
connect();


// Adjustable split between the top panels and the session log (desktop layout
// only). The chosen share is remembered in this browser; double-click resets.
(() => {
  const query = window.matchMedia?.("(min-width: 701px) and (min-height: 600px)");
  const workspace = $("workspace"), splitter = $("layout-splitter");
  if (!query || !workspace || !splitter || typeof getComputedStyle !== "function") return;
  const KEY = "pomo.layout.topShare", MIN_TOP = 160, MIN_LOG = 300;
  let share = null;
  try {
    const saved = Number(localStorage.getItem(KEY));
    if (saved >= 0.15 && saved <= 0.8) share = saved;
  } catch {}

  const available = () => {
    const main = workspace.parentElement, style = getComputedStyle(main);
    return main.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom) - splitter.offsetHeight;
  };
  const show = (top, total) => {
    const percent = Math.round(top / total * 100);
    splitter.setAttribute("aria-valuenow", String(percent));
    splitter.setAttribute("aria-valuetext", `Top ${percent}%, log ${100 - percent}%`);
    setText("layout-split-label", `Top ${percent}% · Log ${100 - percent}%`);
  };
  const apply = () => {
    if (!query.matches) {
      workspace.style.removeProperty("grid-template-rows");
      return;
    }
    const total = available();
    if (total <= 0) return;
    if (share === null) {
      workspace.style.removeProperty("grid-template-rows");
      show(workspace.getBoundingClientRect().height, total);
      return;
    }
    const top = Math.round(Math.min(Math.max(share * total, MIN_TOP), Math.max(MIN_TOP, total - MIN_LOG)));
    workspace.style.gridTemplateRows = `${top}px`;
    show(top, total);
  };
  const save = () => {
    try { share === null ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, share.toFixed(3)); } catch {}
  };
  const setShare = (next) => {
    share = Math.min(0.8, Math.max(0.15, next));
    apply();
  };

  splitter.addEventListener("pointerdown", (event) => {
    if (!query.matches || event.button !== 0) return;
    event.preventDefault();
    splitter.setPointerCapture(event.pointerId);
    splitter.dataset.dragging = "true";
    document.body.dataset.resizing = "true";
  });
  splitter.addEventListener("pointermove", (event) => {
    if (splitter.dataset.dragging !== "true") return;
    setShare((event.clientY - workspace.getBoundingClientRect().top - splitter.offsetHeight / 2) / available());
  });
  const stop = () => {
    if (splitter.dataset.dragging !== "true") return;
    splitter.dataset.dragging = "false";
    document.body.dataset.resizing = "false";
    save();
  };
  splitter.addEventListener("pointerup", stop);
  splitter.addEventListener("pointercancel", stop);
  splitter.addEventListener("dblclick", () => { share = null; save(); apply(); });
  splitter.addEventListener("keydown", (event) => {
    const current = share ?? workspace.getBoundingClientRect().height / available();
    const steps = {ArrowUp: -0.02, ArrowDown: 0.02, PageUp: -0.1, PageDown: 0.1};
    if (event.key in steps) setShare(current + steps[event.key]);
    else if (event.key === "Home") setShare(0.15);
    else if (event.key === "End") setShare(0.8);
    else if (event.key === "Enter" || event.key === "Escape") share = null, apply();
    else return;
    event.preventDefault();
    save();
  });
  window.addEventListener("resize", apply);
  query.addEventListener?.("change", apply);
  apply();
})();
