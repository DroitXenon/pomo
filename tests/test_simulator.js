const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "simulator/index.html"), "utf8");
const code = fs.readFileSync(path.join(root, "simulator/app.js"), "utf8");

function browser({audioSupport = true, audioResumeFails = false} = {}) {
  class Element {
    constructor() {
      this.textContent = "";
      this.children = [];
      this.dataset = {};
      this.attributes = {};
      this.hidden = false;
      this.disabled = false;
    }
    setAttribute(name, value) { this.attributes[name] = value; }
    prepend(child) { child.parent = this; this.children.unshift(child); }
    replaceChildren(...children) {
      this.children = children;
      for (const child of children) child.parent = this;
    }
    get lastChild() { return this.children.at(-1); }
    remove() {
      if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this);
    }
  }
  const elements = Object.fromEntries([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const observations = [...html.matchAll(/data-observation="([^"]+)"/g)].map((match) => {
    const element = new Element();
    element.dataset.observation = match[1];
    return element;
  });
  const previews = [...html.matchAll(/data-preview="([^"]+)"/g)].map((match) => {
    const element = new Element();
    element.dataset.preview = match[1];
    return element;
  });
  let epoch = 1800000000000;
  let sequence = 0;
  const timers = new Map();
  const addTimer = (fn, delay, interval) => {
    const id = ++sequence;
    timers.set(id, {fn, delay, interval});
    return id;
  };
  const sockets = [];
  class Socket {
    static OPEN = 1;
    constructor(url) { this.url = url.href; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(value) {
      assert.equal(this.readyState, 1);
      this.sent.push(JSON.parse(value));
    }
    receive(value) { this.readyState = 1; this.onmessage({data: JSON.stringify(value)}); }
    close() {
      if (this.readyState === 3) return;
      this.readyState = 3;
      this.onclose?.();
    }
  }
  const tones = [];
  class AudioContext {
    constructor() { this.state = "suspended"; this.currentTime = 0; this.destination = {}; }
    async resume() {
      if (audioResumeFails) throw new Error("Audio permission unavailable");
      this.state = "running";
    }
    createOscillator() {
      const tone = {
        frequency: {setValueAtTime() {}},
        stopCalls: [],
        connect() {},
        disconnect() {},
        start() { tones.push(tone); },
        stop(at) { tone.stopCalls.push(at); }
      };
      return tone;
    }
    createGain() {
      return {gain: {setValueAtTime() {}, linearRampToValueAtTime() {}}, connect() {}, disconnect() {}};
    }
  }
  class ClockDate extends Date {
    constructor(...args) { super(...(args.length ? args : [epoch])); }
    static now() { return epoch; }
  }
  const listeners = {};
  const location = {href: "http://127.0.0.1:8000/", protocol: "http:"};
  const window = {
    location,
    AudioContext: audioSupport ? AudioContext : undefined,
    addEventListener(name, fn) { listeners[name] = fn; }
  };
  vm.runInNewContext(code, {
    document: {
      getElementById: (id) => elements[id],
      createElement: () => new Element(),
      querySelectorAll: (selector) => selector === "[data-observation]" ? observations : selector === "[data-preview]" ? previews : []
    },
    window, location, URL, WebSocket: Socket, Date: ClockDate,
    setTimeout: (fn, delay) => addTimer(fn, delay, false),
    clearTimeout: (id) => timers.delete(id),
    setInterval: (fn, delay) => addTimer(fn, delay, true),
    clearInterval: (id) => timers.delete(id)
  }, {filename: "simulator/app.js"});
  return {
    elements, observations, previews, sockets, tones, listeners,
    click(id) {
      const element = typeof id === "string" ? elements[id] : id;
      assert.equal(element.disabled, false);
      return element.onclick();
    },
    intervals() {
      epoch += 500;
      for (const [id, timer] of [...timers]) if (timer.interval && timers.has(id)) timer.fn();
    },
    reconnect() {
      const next = [...timers].filter(([, timer]) => !timer.interval).sort((a, b) => a[1].delay - b[1].delay)[0];
      assert.ok(next, "a reconnect timer exists");
      timers.delete(next[0]);
      next[1].fn();
      return sockets.at(-1);
    },
    timerCount: () => timers.size
  };
}

function snapshot(overrides = {}) {
  return {
    type: "state", protocol_version: 2, instance_id: "server-a", revision: 0,
    dev_controls: true, powered_on: true, monitoring_enabled: false, muted: true,
    behavior_state: "ready", display: "ready", camera_status: "unavailable",
    observation: {presence: "unknown", source: "none", observed_at: null, age_seconds: null},
    observation_session: "session-a", absence_duration_seconds: 0, cooldown_remaining_seconds: 0,
    reminder: {active: false, id: 0, message: null},
    settings: {absence_seconds: 5, cooldown_seconds: 30, observation_timeout_seconds: 3},
    events: [], ...overrides
  };
}

test("simulation heartbeats are fresh and never resume themselves after pause or disconnect", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(snapshot({monitoring_enabled: true}));
  b.click(b.observations.find((button) => button.dataset.observation === "absent"));
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0].presence, "absent");
  assert.equal(socket.sent[0].source, "simulated");
  b.intervals();
  assert.equal(socket.sent.length, 2);
  assert.ok(socket.sent[1].observed_at > socket.sent[0].observed_at);
  socket.receive(snapshot({monitoring_enabled: true, observation_session: "session-b"}));
  b.intervals();
  assert.equal(socket.sent.at(-1).session_id, "session-b");
  socket.receive(snapshot({monitoring_enabled: false}));
  const count = socket.sent.length;
  b.intervals();
  assert.equal(socket.sent.length, count);
  socket.receive(snapshot({monitoring_enabled: true}));
  b.intervals();
  assert.equal(socket.sent.length, count);
  b.click(b.observations.find((button) => button.dataset.observation === "unknown"));
  socket.close();
  const oldCount = socket.sent.length;
  b.intervals();
  assert.equal(socket.sent.length, oldCount);
  const next = b.reconnect();
  next.receive(snapshot({monitoring_enabled: true, observation_session: "session-c"}));
  b.intervals();
  assert.equal(next.sent.length, 0);
});

test("unavailable input is sent once and stopping or powering off disables simulated input", () => {
  const b = browser();
  const socket = b.sockets[0];
  socket.receive(snapshot({monitoring_enabled: true}));
  b.click(b.observations.find((button) => button.dataset.observation === "unavailable"));
  b.intervals();
  assert.equal(socket.sent.length, 1);
  assert.equal(socket.sent[0].presence, "unavailable");
  b.click(b.observations.find((button) => button.dataset.observation === "present"));
  socket.receive(snapshot({powered_on: false, display: "shutdown", behavior_state: "shutdown"}));
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
