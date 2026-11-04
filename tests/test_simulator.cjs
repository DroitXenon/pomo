const {test} = require("node:test");
const assert = require("node:assert/strict");
const {browser, snapshot} = require("./simulator_helpers.cjs");

function setup(t, overrides = {}) {
  const b = browser();
  const state = snapshot({
    monitoring_enabled: true, camera_status: "available", camera_capture_status: "available",
    input_source: "camera", camera_session: "owner-session",
    observation: {presence: "present", source: "camera", observed_at: 1800000000, age_seconds: 0},
    camera_tracking_status: "present", camera_armed: true, frames_received: 1,
    head_direction: "left",
    camera_observation: {presence: "present", reason: "usable",
      head_pose: {yaw: 40, pitch: 0, roll: 0}, blendshapes: {jawOpen: 0.25}},
    ...overrides
  });
  const message = (next) => b.sockets[0].receive(next);
  t.after(() => b.listeners.pagehide());
  return {...b, node: (id) => b.elements[id], state, message};
}

test("camera observations, diagnostics and normalized policy input coexist", (t) => {
  const {node, state, message} = setup(t);
  message(state);
  assert.equal(node("face-presence").textContent, "Present");
  assert.equal(node("head-direction").textContent, "left");
  assert.equal(node("reminder-panel").hidden, true);
  assert.match(node("mouth-movement").textContent, /jawOpen: 0.25/);
  assert.equal(node("observation-current").textContent, "Present");
  assert.equal(node("observation-source").textContent, "Camera");
});

test("real reminders use the shared dismissal id while expression previews have no prompt", (t) => {
  const {node, state, message, sockets} = setup(t, {monitoring_enabled: false, camera_session: null});
  state.display = "reminding";
  message(state);
  assert.equal(node("reminder-panel").hidden, true);
  assert.equal(node("preview-status").hidden, false);
  state.monitoring_enabled = true;
  state.behavior_state = "reminding";
  state.reminder = {active: true, id: 7, message: "A gentle reminder"};
  message(state);
  assert.equal(node("dismiss").disabled, false);
  assert.equal(node("reminder-panel").hidden, false);
  node("dismiss").onclick();
  assert.deepEqual(sockets[0].sent.at(-1), {type: "dismiss_reminder", reminder_id: 7});
});

test("uncertain camera observations stay distinct from capture availability", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation = {presence: "unknown", reason: "low_light"};
  state.observation = {presence: "unknown", source: "camera", observed_at: 1800000000, age_seconds: 0};
  state.display = state.behavior_state = "unavailable";
  state.camera_status = "unavailable";
  state.camera_tracking_status = "uncertain";
  message(state);
  assert.equal(node("face-presence").textContent, "Unknown");
  assert.equal(node("image-quality").textContent, "Low light");
  assert.match(node("detection-status").textContent, /reminders suspended/);
  assert.equal(node("input-status").textContent, "Unavailable");
  assert.equal(node("reminder-panel").hidden, true);
});

test("head direction and finite angles appear without selecting a robot expression", (t) => {
  const {node, state, message} = setup(t);
  message(state);
  assert.equal(node("head-direction").textContent, "left");
  assert.match(node("head-angles").textContent, /Yaw 40°/);
  assert.match(node("head-angles").textContent, /roll 0°/);
  assert.equal(node("screen").dataset.display, "ready");
});

test("eye and mouth movement retain separate labels and continuous scores", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation.eye_movement = {eyeLeft: {direction: "up", blink_score: 0.55},
    eyeRight: {direction: "right", blink_score: 0.48}};
  state.camera_observation.blendshapes = {jawOpen: 0, mouthSmileLeft: 0, mouthSmileRight: 0};
  message(state);
  assert.equal(node("eye-movement").textContent, "eyeLeft: up · eyeRight: right · eyeBlinkLeft: 0.55 · eyeBlinkRight: 0.48");
  assert.equal(node("mouth-movement").textContent, "jawOpen: 0.00 · mouthSmileLeft: 0.00 · mouthSmileRight: 0.00");
  state.camera_observation = null;
  message(state);
  assert.equal(node("eye-movement").textContent, "eyeLeft: unknown · eyeRight: unknown · eyeBlinkLeft: — · eyeBlinkRight: —");
  assert.equal(node("mouth-movement").textContent, "jawOpen: — · mouthSmileLeft: — · mouthSmileRight: —");
});

test("blink diagnostics stay continuous independently of closed-eye labels", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation.eye_movement = {eyeRight: {direction: "center", blink_score: 0.2}};
  for (const [direction, score] of [["center", 0.50], ["center", 0.67], ["center", 0.83], ["closed", 0.92], ["closed", 1]]) {
    state.camera_observation.eye_movement.eyeLeft = {direction, blink_score: score};
    message(state);
    assert.ok(node("eye-movement").textContent.includes(`eyeLeft: ${direction}`));
    assert.ok(node("eye-movement").textContent.includes(`eyeBlinkLeft: ${score.toFixed(2)}`));
    assert.match(node("eye-movement").textContent, /eyeBlinkRight: 0.20/);
  }
});

test("vertical model signals and signed iris offsets remain available for evaluation", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation.blendshapes = {eyeLookUpLeft: 0.7, eyeLookDownLeft: 0.1, eyeLookUpRight: 0.2, eyeLookDownRight: 0.6};
  state.camera_observation.eye_movement = {eyeLeft: {direction: "up", vertical_offset: -0.125},
    eyeRight: {direction: "center", vertical_offset: 0.015}};
  message(state);
  assert.equal(node("eye-vertical-signals").textContent, "eyeLookUpLeft: 0.70 · eyeLookDownLeft: 0.10 · eyeLookUpRight: 0.20 · eyeLookDownRight: 0.60");
  assert.equal(node("eye-vertical-offsets").textContent, "eyeLeft: -0.125 · eyeRight: 0.015");
  state.camera_observation = null;
  message(state);
  assert.equal(node("eye-vertical-offsets").textContent, "eyeLeft: — · eyeRight: —");
});

test("unchanged robot expressions are not repainted by raw diagnostic updates", (t) => {
  const {node, state, message} = setup(t);
  state.display = state.behavior_state = "distraction";
  message(state);
  const writes = node("screen").datasetWrites.display;
  const titleWrites = node("state-title").textWrites;
  for (const status of ["present", "possible_absence", "reminding", "uncertain", "stale"]) {
    state.revision++;
    state.camera_tracking_status = status;
    message(state);
    assert.equal(node("screen").dataset.display, "distraction");
    assert.equal(node("screen").datasetWrites.display, writes);
    assert.equal(node("state-title").textWrites, titleWrites);
  }
  state.display = state.behavior_state = "ready";
  message(state);
  assert.equal(node("screen").datasetWrites.display, writes + 1);
});

test("absence duration comes from the shared reminder engine", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation = {presence: "not_detected", reason: "no_face"};
  state.observation = {presence: "absent", source: "camera", observed_at: 1800000000, age_seconds: 0};
  state.absence_duration_seconds = 2.5;
  state.camera_tracking_status = "absence";
  state.camera_absence_duration_seconds = 8;
  state.display = state.behavior_state = "distraction";
  message(state);
  assert.equal(node("absence-duration").textContent, "2.5s");
  assert.equal(node("detection-status").textContent, "Face not detected");
  assert.equal(node("camera-absence").textContent, "8.0s");
  assert.equal(node("camera-armed").textContent, "Confirmed");
  assert.equal(node("screen").dataset.display, "distraction");
});

test("raw diagnostics tolerate missing or malformed optional values", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation = {presence: "constructor", reason: "constructor",
    head_pose: {yaw: "bad", pitch: null}, face_box: [0, "bad", 1, 1], blendshapes: {jawOpen: "bad"}};
  state.head_direction = null;
  message(state);
  assert.equal(node("connection").textContent, "Connected");
  assert.equal(node("face-presence").textContent, "Unknown");
  assert.equal(node("head-angles").textContent, "—");
  assert.equal(node("image-quality").textContent, "—");
  assert.match(node("mouth-movement").textContent, /jawOpen: —/);
});

test("source switching is paused-only and simulated mode does not start camera or heartbeat itself", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(snapshot());
  assert.equal(b.cameras[0].session, null);
  b.click(b.sources.find((button) => button.dataset.source === "simulated"));
  assert.deepEqual(socket.sent.at(-1), {type: "set_input_source", source: "simulated"});
  socket.receive(snapshot({input_source: "simulated"}));
  assert.equal(b.elements["camera-panel"].hidden, true);
  assert.equal(b.elements["simulation-panel"].hidden, false);
  b.click("monitor");
  socket.receive(snapshot({input_source: "simulated", monitoring_enabled: true}));
  b.intervals();
  assert.equal(socket.sent.filter((command) => command.type === "submit_observation").length, 0);
  assert.ok(b.sources.every((button) => button.disabled));
  b.click(b.observations.find((button) => button.dataset.observation === "absent"));
  b.intervals();
  assert.equal(socket.sent.filter((command) => command.type === "submit_observation").length, 2);
  socket.receive(snapshot({input_source: "camera", monitoring_enabled: false}));
  const count = socket.sent.length;
  b.intervals();
  assert.equal(socket.sent.length, count);
  assert.equal(b.cameras[0].session, null);
});

test("only a valid owner snapshot starts capture and lifecycle actions stop it immediately", () => {
  const b = browser();
  assert.equal(b.cameras[0].updates.length, 0);
  const socket = b.sockets[0];
  socket.receive(snapshot({monitoring_enabled: true, camera_session: "owner-session", camera_capture_status: "starting"}));
  assert.equal(b.cameras[0].session, "owner-session");
  b.click("monitor");
  assert.equal(b.cameras[0].session, null, "pause stops locally before waiting for its acknowledgement");
  socket.receive(snapshot({monitoring_enabled: true, camera_session: "second-session", camera_capture_status: "starting"}));
  b.click("power");
  assert.equal(b.cameras[0].session, null);
  socket.receive(snapshot({monitoring_enabled: true, camera_session: "third-session", camera_capture_status: "starting"}));
  socket.close();
  assert.equal(b.cameras[0].session, null);
  assert.match(b.elements["camera-status"].textContent, /backend disconnected/);
});

test("a missing processor does not prevent selecting simulated input", () => {
  const b = browser();
  b.sockets[0].receive(snapshot({camera_processor_ready: false}));
  assert.equal(b.elements.monitor.disabled, true);
  assert.equal(b.sources.find((button) => button.dataset.source === "simulated").disabled, false);
  b.click(b.sources.find((button) => button.dataset.source === "simulated"));
  b.sockets[0].receive(snapshot({input_source: "simulated", camera_processor_ready: false}));
  assert.equal(b.elements.monitor.disabled, false);
});

test("dev-controls gating applies to simulation while camera remains usable", () => {
  const b = browser();
  b.sockets[0].receive(snapshot({dev_controls: false}));
  assert.equal(b.sources.find((button) => button.dataset.source === "simulated").disabled, true);
  assert.equal(b.sources.find((button) => button.dataset.source === "camera").disabled, false);
  assert.equal(b.elements.monitor.disabled, false);
  assert.ok(b.previews.every((button) => button.disabled));
});

test("face overlay is owner-only and clears when observations are stale", (t) => {
  const {node, state, message} = setup(t);
  state.camera_observation.face_box = [0.1, 0.2, 0.6, 0.8];
  state.last_frame = {width: 640, height: 480};
  message(state);
  assert.equal(node("face-overlay").context.strokeCalls.length, 1);
  state.observation.age_seconds = 10;
  message(state);
  assert.equal(node("face-overlay").context.strokeCalls.length, 1);
  state.observation.age_seconds = 0;
  state.camera_session = null;
  message(state);
  assert.equal(node("face-overlay").context.strokeCalls.length, 1);
  assert.ok(node("face-overlay").context.clearCalls >= 3);
});

test("legacy protocol 6 is rejected before camera permission is requested", () => {
  const b = browser();
  b.sockets[0].receive(snapshot({protocol_version: 6, monitoring_enabled: true, camera_session: "legacy-session"}));
  assert.equal(b.cameras[0].updates.length, 0);
  assert.equal(b.elements.monitor.disabled, true);
  assert.equal(b.elements.connection.textContent, "Incompatible");
});
