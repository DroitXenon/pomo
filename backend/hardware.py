"""Optional USB serial adapter for the CoreS3 robot.

The backend remains the only owner of behaviour. Host to device: each
published snapshot becomes one compact JSON line (display, reminder, sound and
whether the robot camera should stream). Device to host: binary JPEG frames
from the robot camera, framed as MAGIC + uint32 length + uint32 sequence
(little-endian) + JPEG bytes. A dedicated thread does all serial I/O, so a slow
or missing device never blocks the event loop.
"""

import json
import logging
import queue
import struct
import threading
import time

LOG = logging.getLogger("pomo.hardware")
MESSAGE_VERSION = 1
FRAME_MAGIC = b"PJPG"
FRAME_HEADER = struct.Struct("<4sII")


def display_message(snapshot):
    """Return the device message for a backend snapshot (see docs/protocol.md)."""
    reminder = snapshot["reminder"]
    return {
        "v": MESSAGE_VERSION,
        "display": snapshot["display"],
        "reminder": reminder["id"] if reminder["active"] else 0,
        "stage": reminder["stage"],
        "sound": not snapshot["muted"],
        "standby": snapshot["standby"],
        "camera": bool(snapshot.get("input_source") == "robot" and snapshot.get("powered_on")
                       and snapshot.get("monitoring_enabled")),
    }


def local_epoch():
    """Seconds since 1970 in the laptop's local time zone, for the robot clock."""
    now = time.time()
    return now + time.localtime(now).tm_gmtoff


class FrameParser:
    """Extract framed JPEGs from the device byte stream, resynchronising on MAGIC."""

    def __init__(self, max_bytes):
        self.max_bytes = max_bytes
        self.buffer = bytearray()

    def reset(self):
        self.buffer.clear()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while True:
            start = self.buffer.find(FRAME_MAGIC)
            if start < 0:
                # Keep a possible partial MAGIC at the end; drop other noise.
                del self.buffer[:max(0, len(self.buffer) - (len(FRAME_MAGIC) - 1))]
                return frames
            del self.buffer[:start]
            if len(self.buffer) < FRAME_HEADER.size:
                return frames
            _, length, _sequence = FRAME_HEADER.unpack_from(self.buffer)
            if not 0 < length <= self.max_bytes:
                del self.buffer[:len(FRAME_MAGIC)]
                continue
            end = FRAME_HEADER.size + length
            if len(self.buffer) < end:
                return frames
            frames.append(bytes(self.buffer[FRAME_HEADER.size:end]))
            del self.buffer[:end]


class SerialDisplay:
    """Latest-value serial writer with reconnect and explicit shutdown."""

    def __init__(self, port, baudrate=115200, *, serial_factory=None,
                 clock=time.monotonic, local_time=None, retry_seconds=2.0, heartbeat_seconds=2.0,
                 max_frame_bytes=524288, read_timeout=0.05):
        self.port = port
        self.baudrate = baudrate
        self._serial_factory = serial_factory
        self._clock = clock
        self.retry_seconds = retry_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.status = "disconnected"
        self._device = None
        self._next_attempt = 0.0
        self._last_sent = None
        self._last_write = None
        self._latest = None
        self._pending = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = None
        self.read_timeout = read_timeout
        self._local_time = local_time or local_epoch
        self._weather = {}
        self._timer = {}
        self.parser = FrameParser(max_frame_bytes)
        self.on_frame = None  # Called on the serial thread with each JPEG.
        self.frames_received = 0

    def set_weather(self, fields):
        """Replace the weather fields added to each line (called from the event loop)."""
        self._weather = dict(fields)

    def set_timer(self, fields):
        """Pomodoro durations for the robot's timer page (seconds and session count)."""
        self._timer = dict(fields)

    def _line(self, message):
        # Local wall time, weather and timer settings ride on every line,
        # including heartbeats, without affecting publish() de-duplication.
        return {**message, "time": int(self._local_time()), **self._weather, **self._timer}

    def publish(self, snapshot):
        """Queue the newest message without blocking; older pending ones are replaced."""
        message = display_message(snapshot)
        if message == self._latest:
            return
        self._latest = message
        try:
            self._pending.get_nowait()
        except queue.Empty:
            pass
        try:
            self._pending.put_nowait(message)
        except queue.Full:  # pragma: no cover - single producer under the runtime lock
            pass

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pomo-serial", daemon=True)
            self._thread.start()

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        self._disconnect()
        self.status = "disconnected"

    def _run(self):
        while not self._stop.is_set():
            try:
                # With an open port, the blocking serial read paces the loop.
                message = (self._pending.get_nowait() if self._device is not None
                           else self._pending.get(timeout=self.read_timeout))
            except queue.Empty:
                message = None
            self.deliver(message)
            self.receive()

    def receive(self):
        """Read available device bytes and hand complete JPEG frames to on_frame."""
        if self._device is None:
            return 0
        try:
            data = self._device.read(65536)
        except Exception as error:
            self._fail(error)
            return 0
        if data and b"pomo-robot " in data:
            # Best-effort: the firmware sends one plain-text status line per boot.
            line = data[data.index(b"pomo-robot "):].split(b"\n", 1)[0][:120]
            LOG.info("Robot: %s", line.decode("ascii", "replace"))
        frames = self.parser.feed(data) if data else []
        for frame in frames:
            self.frames_received += 1
            if self.on_frame is not None:
                try:
                    self.on_frame(frame)
                except Exception:
                    LOG.exception("Robot camera frame handler failed")
        return len(frames)

    def deliver(self, message=None):
        """Write a new message, or repeat the last one as a heartbeat when due."""
        if message is None:
            if self._last_sent is None or (
                    self._last_write is not None
                    and self._clock() - self._last_write < self.heartbeat_seconds):
                return False
            message = self._last_sent
        if not self._connect():
            # Keep the newest state so it is sent after reconnecting.
            self._last_sent = message
            return False
        line = (json.dumps(self._line(message), separators=(",", ":")) + "\n").encode("ascii")
        try:
            self._device.write(line)
            self._device.flush()
        except Exception as error:
            self._fail(error)
            self._last_sent = message
            return False
        self._last_sent = message
        self._last_write = self._clock()
        return True

    def _connect(self):
        if self._device is not None:
            return True
        now = self._clock()
        if now < self._next_attempt:
            return False
        self._next_attempt = now + self.retry_seconds
        try:
            factory = self._serial_factory
            if factory is None:
                import serial
                factory = serial.Serial
            self._device = factory(self.port, self.baudrate, timeout=self.read_timeout, write_timeout=1)
            self.parser.reset()
        except Exception as error:
            if self.status != "unavailable":
                LOG.warning("Robot display unavailable on %s: %s", self.port, error)
            self.status = "unavailable"
            return False
        self.status = "connected"
        LOG.info("Robot display connected on %s", self.port)
        return True

    def _fail(self, error):
        LOG.warning("Robot display disconnected from %s: %s", self.port, error)
        self._disconnect()
        self.status = "unavailable"
        self._next_attempt = self._clock() + self.retry_seconds

    def _disconnect(self):
        device, self._device = self._device, None
        if device is not None:
            try:
                device.close()
            except Exception:
                pass
