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
      this.textWrites = 0;
      let content = "";
      Object.defineProperty(this, "textContent", {get: () => content, set: (value) => { content = value; this.textWrites++; }});
      this.children = [];
      this.datasetWrites = {};
      this.dataset = new Proxy({}, {set: (target, name, value) => { this.datasetWrites[name] = (this.datasetWrites[name] || 0) + 1; target[name] = value; return true; }});
      this.width = 640; this.height = 480;
      this.context = {clearCalls: 0, strokeCalls: [], clearRect() { this.clearCalls++; }, strokeRect(...args) { this.strokeCalls.push(args); }};
      this.attributes = {};
      this.hidden = false;
      this.disabled = false;
    }
    getContext() { return this.context; }
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
    elements[`preview-${match[1]}`] = element;
    return element;
  });
  const sources = [...html.matchAll(/data-source="([^"]+)"/g)].map((match) => {
    const element = new Element();
    element.dataset.source = match[1];
    return element;
  });
  const cameras = [];
  class Camera {
    constructor(video, status, reportFailure) { this.video = video; this.status = status; this.reportFailure = reportFailure; this.stopCalls = 0; this.updates = []; this.session = null; this.generation = 0; cameras.push(this); }
    update(next) {
      this.updates.push(next);
      if (next.input_source === "camera" && next.powered_on && next.monitoring_enabled && next.camera_processor_ready && next.camera_session) this.session = next.camera_session;
      else {
        this.stop();
        if (next.camera_capture_status === "unavailable" && this.failure) this.status.textContent = this.failure;
      }
    }
    stop() { this.stopCalls++; this.session = null; this.generation++; }
    fail(message, generation) {
      if (generation !== this.generation) return;
      this.stop();
      this.failure = message;
      this.status.textContent = message;
      this.reportFailure(message);
    }
  }
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
  const document = {
      hidden: false,
      addEventListener(name, fn) { listeners[name] = fn; },
      getElementById: (id) => elements[id],
      createElement: () => new Element(),
      querySelectorAll: (selector) => selector === "[data-observation]" ? observations : selector === "[data-preview]" ? previews : selector === "[data-source]" ? sources : []
  };
  vm.runInNewContext(code, {
    document, window, location, URL, WebSocket: Socket, CameraController: Camera, Date: ClockDate,
    setTimeout: (fn, delay) => addTimer(fn, delay, false),
    clearTimeout: (id) => timers.delete(id),
    setInterval: (fn, delay) => addTimer(fn, delay, true),
    clearInterval: (id) => timers.delete(id)
  }, {filename: "simulator/app.js"});
  return {
    elements, observations, previews, sources, cameras, sockets, tones, listeners, document,
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
    type: "state", protocol_version: 7, instance_id: "server-a", revision: 0,
    dev_controls: true, powered_on: true, monitoring_enabled: false, muted: true,
    behavior_state: "ready", display: "ready", camera_status: "unavailable",
    observation: {presence: "unknown", source: "none", observed_at: null, age_seconds: null},
    observation_session: "session-a", absence_duration_seconds: 0, cooldown_remaining_seconds: 0,
    reminder: {active: false, id: 0, message: null},
    settings: {absence_seconds: 5, cooldown_seconds: 30, observation_timeout_seconds: 3},
    input_source: "camera", camera_session: null, camera_capture_status: "paused", camera_processor_ready: true,
    camera_settings: {width: 640, height: 480, fps: 10, jpeg_quality: 0.75, max_bytes: 524288, timeout_seconds: 3},
    camera_observation: null, head_direction: "unknown", frames_received: 0, last_frame: null,
    camera_armed: false, camera_tracking_status: "paused",
    events: [], ...overrides
  };
}


module.exports = {browser, snapshot};
