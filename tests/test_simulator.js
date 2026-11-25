const test = require("node:test");
const assert = require("node:assert/strict");
const {browser, snapshot} = require("./simulator_helpers.cjs");
const simulatedSnapshot = (overrides = {}) => snapshot({input_source: "simulated", ...overrides});

test("simulation heartbeats are fresh and never resume themselves after pause or disconnect", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(simulatedSnapshot({monitoring_enabled: true}));
  b.click(b.observations.find((button) => button.dataset.observation === "absent"));
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0].presence, "absent");
  assert.equal(socket.sent[0].source, "simulated");
  b.intervals();
  assert.equal(socket.sent.length, 2);
  assert.ok(socket.sent[1].observed_at > socket.sent[0].observed_at);
  socket.receive(simulatedSnapshot({monitoring_enabled: true, observation_session: "session-b"}));
  b.intervals();
  assert.equal(socket.sent.at(-1).session_id, "session-b");
  socket.receive(simulatedSnapshot({monitoring_enabled: false}));
  const count = socket.sent.length;
  b.intervals();
  assert.equal(socket.sent.length, count);
  socket.receive(simulatedSnapshot({monitoring_enabled: true}));
  b.intervals();
  assert.equal(socket.sent.length, count);
  b.click(b.observations.find((button) => button.dataset.observation === "uncertain"));
  socket.close();
  const oldCount = socket.sent.length;
  b.intervals();
  assert.equal(socket.sent.length, oldCount);
  const next = b.reconnect();
  next.receive(simulatedSnapshot({monitoring_enabled: true, observation_session: "session-c"}));
  b.intervals();
  assert.equal(next.sent.length, 0);
});

test("unavailable input is sent once and stopping or powering off disables simulated input", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(simulatedSnapshot({monitoring_enabled: true}));
  b.click(b.observations.find((button) => button.dataset.observation === "unavailable"));
  b.intervals();
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0].presence, "unavailable");
  b.click(b.observations.find((button) => button.dataset.observation === "present"));
  socket.receive(simulatedSnapshot({powered_on: false, display: "idle", behavior_state: "idle"}));
  const count = socket.sent.length;
  b.intervals();
  assert.equal(socket.sent.length, count);
  assert.equal(b.elements.monitor.disabled, true);
  assert.equal(b.elements.power.textContent, "Wake Pomo");
  assert.ok(b.observations.every((button) => button.disabled));
});

test("sound requires a local gesture and never replays current reminders on reconnect", async () => {
  const b = browser();
  const socket = b.sockets[0];
  const active = {active: true, id: 1, stage: 1, message: "A gentle reminder"};
  socket.receive(snapshot({monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: active}));
  assert.equal(b.tones.length, 0);
  assert.equal(b.elements["audio-unlock"].hidden, false);
  await b.click("audio-unlock");
  socket.receive(snapshot({revision: 1, monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: active}));
  assert.equal(b.tones.length, 0, "unlocking does not replay an existing reminder");
  socket.receive(snapshot({revision: 2, monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: {...active, id: 2}}));
  assert.equal(b.tones.length, 1);
  socket.receive(snapshot({revision: 3, monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: {...active, id: 2}}));
  assert.equal(b.tones.length, 1, "timer snapshots do not repeat a cue");
  await b.click("sound");
  assert.equal(socket.sent.at(-1).muted, true);
  assert.ok(b.tones[0].stopCalls.includes(undefined), "mute stops an in-flight tone immediately");
  socket.close();
  const next = b.reconnect();
  next.receive(snapshot({monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: {...active, id: 3}}));
  assert.equal(b.tones.length, 1, "initial reconnect snapshot is silent");
  next.receive(snapshot({revision: 1, monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: {...active, id: 4}}));
  assert.equal(b.tones.length, 2);
});

test("previews are separate from reminders, and production-disabled developer controls stay disabled", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(snapshot());
  b.click(b.previews.find((button) => button.dataset.preview === "surprised"));
  assert.equal(socket.sent.at(-1).type, "preview_display");
  socket.receive(snapshot({display: "surprised"}));
  assert.equal(b.elements["reminder-panel"].hidden, true);
  assert.equal(b.elements["preview-status"].hidden, false);
  assert.equal(b.tones.length, 0);
  socket.receive(snapshot({dev_controls: false, monitoring_enabled: true}));
  assert.ok(b.previews.every((button) => button.disabled));
  assert.ok(b.observations.every((button) => button.disabled));
  assert.equal(b.elements.monitor.disabled, false);
  assert.equal(b.elements.power.disabled, false);
  assert.equal(b.elements.sound.disabled, false);
});

test("unsupported or blocked audio leaves visual reminders and global mute controls usable", async () => {
  for (const options of [{audioSupport: false}, {audioResumeFails: true}]) {
    const b = browser(options);
    const socket = b.sockets[0];
    socket.receive(snapshot());
    await b.click("sound");
    assert.equal(socket.sent.at(-1).muted, false);
    socket.receive(snapshot({revision: 1, monitoring_enabled: true, muted: false}));
    socket.receive(snapshot({revision: 2, monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", reminder: {active: true, id: 1, stage: 1, message: "A gentle reminder"}}));
    assert.equal(b.elements["reminder-panel"].hidden, false);
    assert.equal(b.elements.dismiss.disabled, false);
    assert.ok(b.elements["audio-status"].textContent.includes("Visual reminders still work"));
    assert.equal(b.tones.length, 0);
    assert.equal(b.elements.sound.disabled, false);
  }
});

test("errors survive timer snapshots and backend log text is rendered without HTML interpretation", () => {
  const b = browser();
  const socket = b.sockets[0];
  const event = {id: 1, at: "2026-10-31T14:00:00Z", level: "info", kind: "test", message: "<img src=x onerror=bad()>"};
  socket.receive(snapshot({events: [event]}));
  assert.ok(b.elements.events.children[0].textContent.includes(event.message));
  socket.receive({type: "error", code: "invalid_command", message: "Select a fresh observation."});
  socket.receive(snapshot({revision: 1, events: [event]}));
  assert.equal(b.elements.feedback.textContent, "Select a fresh observation.");
  b.click("clear");
  socket.receive(snapshot({revision: 2, events: [event]}));
  assert.equal(b.elements.events.children.length, 0);
  assert.equal(socket.sent.length, 0, "clearing logs only affects this browser's view");
});

test("an incompatible protocol never enables controls or enters a reconnect loop", () => {
  const b = browser();
  b.sockets[0].receive(snapshot({protocol_version: 1}));
  assert.equal(b.elements.monitor.disabled, true);
  assert.equal(b.elements.connection.textContent, "Incompatible");
  assert.ok(b.elements.feedback.textContent.includes("protocol mismatch"));
  assert.equal(b.timerCount(), 0);
});

test("each new reminder speaks its message and mute or clearing cancels speech", async () => {
  const b = browser({speechSupport: true});
  const socket = b.sockets[0];
  const active = {active: true, id: 1, stage: 1, message: "I miss you. Please come back."};
  const base = {monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad"};
  socket.receive(snapshot({...base, reminder: {active: false, id: 0, stage: 0, message: null}, display: "surprised", behavior_state: "surprised"}));
  await b.click("audio-unlock");
  socket.receive(snapshot({...base, revision: 1, reminder: active}));
  assert.deepEqual(b.spoken.map((u) => u.text), ["I miss you. Please come back."]);
  assert.equal(b.tones.length, 0, "speech replaces the fallback tone");
  socket.receive(snapshot({...base, revision: 2, reminder: active}));
  assert.equal(b.spoken.length, 1, "timer snapshots do not repeat speech");
  socket.receive(snapshot({...base, revision: 3, reminder: {active: true, id: 2, stage: 2, message: "Still here."}}));
  assert.deepEqual(b.spoken.map((u) => u.text), ["I miss you. Please come back.", "Still here."]);
  const cancels = b.speech.cancels;
  socket.receive(snapshot({...base, revision: 4, display: "happy", behavior_state: "happy", reminder: {active: false, id: 2, stage: 0, message: null}}));
  assert.ok(b.speech.cancels > cancels, "a cleared reminder cancels speech");
  b.speech.speaking = true;
  await b.click("sound");
  assert.equal(b.speech.speaking, false, "mute cancels speech");
});

test("a connected robot speaks reminders instead of the browser", async () => {
  const b = browser({speechSupport: true});
  const socket = b.sockets[0];
  const base = {monitoring_enabled: true, muted: false, display: "sad", behavior_state: "sad", robot_display: "connected"};
  socket.receive(snapshot({...base, display: "surprised", behavior_state: "surprised"}));
  assert.equal(b.elements["audio-unlock"].hidden, true, "no browser audio unlock is needed");
  assert.ok(b.elements["audio-status"].textContent.includes("robot speaks"));
  assert.equal(b.elements["robot-display"].textContent, "Connected");
  socket.receive(snapshot({...base, revision: 1, reminder: {active: true, id: 1, stage: 1, message: "I miss you."}}));
  assert.equal(b.spoken.length, 0);
  assert.equal(b.tones.length, 0);
  assert.equal(b.elements["reminder-panel"].hidden, false, "the visual reminder and dismissal remain");
  socket.receive(snapshot({...base, revision: 2, robot_display: "unavailable"}));
  await b.click("audio-unlock");
  socket.receive(snapshot({...base, revision: 3, robot_display: "unavailable", reminder: {active: true, id: 2, stage: 2, message: "Still here."}}));
  assert.deepEqual(b.spoken.map((u) => u.text), ["Still here."], "the browser speaks when the robot is unavailable");
});

test("robot camera input hides the browser preview and never starts browser capture", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(snapshot({robot_display: "disabled"}));
  const robot = b.sources.find((button) => button.dataset.source === "robot");
  assert.equal(robot.disabled, true, "robot input needs a configured serial port");
  socket.receive(snapshot({revision: 1, robot_display: "connected"}));
  assert.equal(robot.disabled, false);
  b.click(robot);
  assert.deepEqual(socket.sent.at(-1), {type: "set_input_source", source: "robot"});
  socket.receive(snapshot({revision: 2, robot_display: "connected", input_source: "robot", monitoring_enabled: true,
    camera_capture_status: "starting"}));
  assert.equal(b.elements["camera-panel"].hidden, false);
  assert.equal(b.elements["camera-view"].hidden, true);
  assert.equal(b.elements["detection-status"].textContent, "Waiting for robot camera frames");
  assert.equal(b.cameras.at(-1).session, null, "the browser camera stays off");
});

test("the session log keeps history beyond the backend window, filters, searches and summarises", () => {
  const b = browser();
  const socket = b.sockets[0];
  const at = "2026-11-24T10:00:00Z";
  const event = (id, kind, message, level = "info") => ({id, at, level, kind, message});
  const first = [
    event(1, "departure_detected", "camera: user away since 10:00"),
    event(2, "reminder_triggered", "Reminder 1 (first) after 10.0s away"),
    event(3, "user_returned", "User returned 4.0s after reminder 1 (first); away 14.0s"),
    event(4, "observations_invalidated", "Camera input timed out or disconnected.", "warning")
  ];
  socket.receive(snapshot({events: first}));
  // The next snapshot no longer carries the oldest events; the page keeps them.
  socket.receive(snapshot({revision: 1, events: [
    event(5, "departure_detected", "camera: user away since 10:05"),
    event(6, "reminder_triggered", "Reminder 2 (first) after 10.0s away"),
    event(7, "reminder_triggered", "Reminder 3 (second) after 310.0s away"),
    event(8, "user_returned", "User returned 6.0s after reminder 3 (second); away 316.0s")
  ]}));
  assert.equal(b.elements.events.children.length, 8);
  assert.ok(b.elements.events.children[0].textContent.includes("User returned 6.0s"), "newest first");
  assert.equal(b.elements["log-count"].textContent, "8 events");
  assert.equal(b.elements["stat-departures"].textContent, "2");
  assert.equal(b.elements["stat-first"].textContent, "2");
  assert.equal(b.elements["stat-second"].textContent, "1");
  assert.equal(b.elements["stat-returns"].textContent, "2");
  assert.equal(b.elements["stat-latency"].textContent, "5.0 s");
  b.click(b.filters.find((button) => button.dataset.filter === "warnings"));
  assert.equal(b.elements.events.children.length, 1);
  assert.equal(b.elements.events.children[0].dataset.level, "warning");
  assert.equal(b.elements["log-count"].textContent, "1 of 8 events");
  b.click(b.filters.find((button) => button.dataset.filter === "all"));
  b.elements["log-search"].value = "SECOND";
  b.elements["log-search"].oninput();
  assert.equal(b.elements.events.children.length, 2);
  b.elements["log-search"].value = "";
  b.elements["log-search"].oninput();
  b.click("tab-journal");
  assert.equal(b.elements["journal-view"].hidden, false);
  assert.equal(b.elements["events-view"].hidden, true);
  assert.equal(b.elements["log-filters"].hidden, true);
  b.click("clear");
  assert.equal(b.elements.events.children.length, 0);
  assert.equal(b.elements["stat-departures"].textContent, "0");
  assert.equal(b.elements["export-log"].disabled, true);
  socket.receive(snapshot({revision: 2, instance_id: "server-b", events: [event(1, "client_connected", "Client connected.")]}));
  assert.equal(b.elements.events.children.length, 1, "a backend restart starts a fresh history");
});
