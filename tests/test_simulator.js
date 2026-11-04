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
  b.click(b.observations.find((button) => button.dataset.observation === "unknown"));
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
  socket.receive(simulatedSnapshot({powered_on: false, display: "shutdown", behavior_state: "shutdown"}));
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
  const active = {active: true, id: 1, message: "A gentle reminder"};
  socket.receive(snapshot({monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: active}));
  assert.equal(b.tones.length, 0);
  assert.equal(b.elements["audio-unlock"].hidden, false);
  await b.click("audio-unlock");
  socket.receive(snapshot({revision: 1, monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: active}));
  assert.equal(b.tones.length, 0, "unlocking does not replay an existing reminder");
  socket.receive(snapshot({revision: 2, monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: {...active, id: 2}}));
  assert.equal(b.tones.length, 1);
  socket.receive(snapshot({revision: 3, monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: {...active, id: 2}}));
  assert.equal(b.tones.length, 1, "timer snapshots do not repeat a cue");
  await b.click("sound");
  assert.equal(socket.sent.at(-1).muted, true);
  assert.ok(b.tones[0].stopCalls.includes(undefined), "mute stops an in-flight tone immediately");
  socket.close();
  const next = b.reconnect();
  next.receive(snapshot({monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: {...active, id: 3}}));
  assert.equal(b.tones.length, 1, "initial reconnect snapshot is silent");
  next.receive(snapshot({revision: 1, monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: {...active, id: 4}}));
  assert.equal(b.tones.length, 2);
});

test("previews are separate from reminders, and production-disabled developer controls stay disabled", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(snapshot());
  b.click(b.previews.find((button) => button.dataset.preview === "reminding"));
  assert.equal(socket.sent.at(-1).type, "preview_display");
  socket.receive(snapshot({display: "reminding"}));
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
    socket.receive(snapshot({revision: 2, monitoring_enabled: true, muted: false, display: "reminding", behavior_state: "reminding", reminder: {active: true, id: 1, message: "A gentle reminder"}}));
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
