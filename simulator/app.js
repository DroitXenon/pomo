"use strict";
const $ = (id) => document.getElementById(id);
const displayLabels = {
  ready: "Ready",
  possible_absence: "Possible absence",
  reminding: "Reminder",
  unavailable: "Unavailable"
};
let socket, retryTimer, connectTimer, attempts = 0, stopped = false, state = null;
const camera = new CameraController($("camera-preview"), $("camera-status"), (message) => {
  setText("feedback", message);
  send({type: "camera_failed"});
});
function log(text) {
  const item = document.createElement("li");
  item.textContent = `${new Date().toLocaleTimeString()}  ${text}`;
  $("journal").prepend(item);
  while ($("journal").children.length > 12) $("journal").lastChild.remove();
}
function controls(connected) {
  $("monitor").disabled = !connected;
  $("dismiss-reminder").disabled = !connected || !state?.behaviour?.reminder_active;
  document.querySelectorAll("[data-preview]").forEach((button) => {
    button.disabled = !connected || !state?.dev_controls;
  });
}
function setText(id, value) {
  const element = $(id);
  const text = String(value);
  if (element.textContent !== text) element.textContent = text;
}
function render(next) {
  const expressionTransition = !state || state.display !== next.display;
  state = next;
  if (expressionTransition) {
    $("screen").dataset.display = state.display;
    setText("state-title", displayLabels[state.display]);
    document.querySelectorAll("[data-preview]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.preview === state.display)));
  }
  setText("monitor", state.monitoring_enabled ? "Pause monitoring" : "Enable monitoring");
  $("monitor").setAttribute("aria-pressed", String(state.monitoring_enabled));
  setText("monitor-status", state.monitoring_enabled ? "Camera monitoring enabled" : "Monitoring paused");
  setText("revision", state.revision);
  setText("feedback", state.dev_controls ? "" : "Expression controls disabled.");
  controls(true);
  camera.update(state);
  renderDetection(state);
}
function renderDetection(next) {
  const observation = next.observation;
  const behaviour = next.behaviour || {};
  const statuses = {
    paused: "Detection paused", unavailable: "Camera unavailable",
    awaiting_face: "Waiting for a visible face before monitoring absence",
    confirming_face: "Confirming face presence", present: "Face visible",
    tracking_loss: "Brief face tracking loss", possible_absence: "Possible absence",
    reminding: "Sustained face absence",
    uncertain: "Input uncertain · reminders suspended", stale: "Input stale · reminders suspended"
  };
  const reasons = {usable: "Usable", no_face: "No face detected", low_light: "Low light",
    overexposed: "Overexposed", low_detail_or_blur: "Low detail or blur", invalid_landmarks: "Uncertain landmarks"};
  setText("detection-status", statuses[behaviour.status] || "Waiting for observations");
  setText("face-presence", {present: "Present", not_detected: "Not detected", unknown: "Unknown"}[observation?.presence] || "Unknown");
  setText("head-direction", next.head_direction || "unknown");
  const pose = observation?.head_pose;
  setText("head-angles", pose ? `Yaw ${pose.yaw.toFixed(0)}° / pitch ${pose.pitch.toFixed(0)}° / roll ${pose.roll.toFixed(0)}°` : "—");
  setText("image-quality", reasons[observation?.reason] || "—");
  setText("absence-duration", `${behaviour.absence_seconds || 0} s`);
  const scores = observation?.blendshapes || {};
  const formatScore = (name) => `${name}: ${Number.isFinite(scores[name]) ? scores[name].toFixed(2) : "—"}`;
  const eyes = observation?.eye_movement;
  const formatBlink = (name, eye) => `${name}: ${Number.isFinite(eye?.blink_score) ? eye.blink_score.toFixed(2) : "—"}`;
  setText("eye-movement", [
    `eyeLeft: ${eyes?.eyeLeft?.direction || "unknown"}`,
    `eyeRight: ${eyes?.eyeRight?.direction || "unknown"}`,
    formatBlink("eyeBlinkLeft", eyes?.eyeLeft), formatBlink("eyeBlinkRight", eyes?.eyeRight)
  ].join(" · "));
  setText("eye-vertical-signals", ["eyeLookUpLeft", "eyeLookDownLeft", "eyeLookUpRight", "eyeLookDownRight"]
    .map(formatScore).join(" · "));
  const formatOffset = (name, eye) => `${name}: ${Number.isFinite(eye?.vertical_offset) ? eye.vertical_offset.toFixed(3) : "—"}`;
  setText("eye-vertical-offsets", [formatOffset("eyeLeft", eyes?.eyeLeft), formatOffset("eyeRight", eyes?.eyeRight)].join(" · "));
  setText("mouth-movement", ["jawOpen", "mouthSmileLeft", "mouthSmileRight"]
    .map(formatScore).join(" · "));
  $("reminder-message").hidden = !behaviour.reminder_active;
  $("dismiss-reminder").hidden = !behaviour.reminder_active;
  const overlay = $("face-overlay");
  const context = overlay.getContext("2d");
  context.clearRect(0, 0, overlay.width, overlay.height);
  if (next.camera_session && observation?.presence === "present" && observation.face_box && next.last_frame) {
    const {width, height} = next.last_frame;
    const scale = Math.min(overlay.width / width, overlay.height / height);
    const offsetX = (overlay.width - width * scale) / 2;
    const offsetY = (overlay.height - height * scale) / 2;
    const [left, top, right, bottom] = observation.face_box;
    context.strokeStyle = "#fff";
    context.lineWidth = 2;
    context.strokeRect(offsetX + left * width * scale, offsetY + top * height * scale,
                       (right - left) * width * scale, (bottom - top) * height * scale);
  }
}
function connect() {
  if (stopped) return;
  controls(false);
  setText("connection", "Connecting");
  $("connection").dataset.connected = "false";
  const url = new URL("ws", window.location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(url);
  connectTimer = setTimeout(() => socket.close(), 10000);
  socket.onmessage = ({data}) => {
    try {
      const message = JSON.parse(data);
      if (message.type === "state" && message.protocol_version === 6 && displayLabels[message.display]) {
        clearTimeout(connectTimer);
        attempts = 0;
        setText("connection", "Connected");
        $("connection").dataset.connected = "true";
        const changed = !state || state.display !== message.display ||
          state.camera_status !== message.camera_status || state.behaviour?.status !== message.behaviour?.status;
        render(message);
        if (changed) log(`State ${message.revision}: ${message.display} · ${message.behaviour?.status || message.camera_status}`);
      } else if (message.type === "error") {
        setText("feedback", message.message);
        log(`Command rejected: ${message.code}`);
      }
    } catch { log("Unrecognised backend message"); }
  };
  socket.onerror = () => socket.close();
  socket.onclose = () => {
    clearTimeout(connectTimer);
    controls(false);
    camera.stop();
    setText("detection-status", "Disconnected · observations may be stale");
    $("face-overlay").getContext("2d").clearRect(0, 0, 640, 480);
    setText("camera-status", "Camera stopped · backend disconnected");
    setText("connection", "Disconnected");
    $("connection").dataset.connected = "false";
    setText("monitor-status", "Disconnected · displayed state may be stale");
    if (!stopped) {
      const delay = Math.min(1000 * 2 ** attempts++, 10000);
      log(`Disconnected; retrying in ${delay / 1000}s`);
      retryTimer = setTimeout(connect, delay);
    }
  };
}
function send(command) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify(command));
}
$("dismiss-reminder").onclick = () => send({type: "dismiss_reminder"});
$("monitor").onclick = () => send({type: "set_monitoring", enabled: !state.monitoring_enabled});
document.querySelectorAll("[data-preview]").forEach((button) => {
  button.onclick = () => send({type: "preview_display", display: button.dataset.preview});
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && camera.session) {
    camera.stop();
    send({type: "set_monitoring", enabled: false});
  }
});
$("clear").onclick = () => $("journal").replaceChildren();
window.addEventListener("pagehide", () => {
  camera.stop();
  stopped = true; clearTimeout(retryTimer); clearTimeout(connectTimer); socket?.close();
});
window.addEventListener("pageshow", (event) => { if (event.persisted) { stopped = false; connect(); } });
connect();
