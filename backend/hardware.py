"""Optional USB serial adapter that mirrors backend display state to the CoreS3.

The backend remains the only owner of behaviour. This adapter converts each
published snapshot into one compact JSON line and writes it from a dedicated
thread, so a slow or missing device never blocks the event loop. Messages are
one-way; the device only renders them.
"""

import json
import logging
import queue
import threading
import time

LOG = logging.getLogger("pomo.hardware")
MESSAGE_VERSION = 1


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
    }


class SerialDisplay:
    """Latest-value serial writer with reconnect and explicit shutdown."""

    def __init__(self, port, baudrate=115200, *, serial_factory=None,
                 clock=time.monotonic, retry_seconds=2.0, heartbeat_seconds=2.0):
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
                message = self._pending.get(timeout=min(self.heartbeat_seconds, self.retry_seconds))
            except queue.Empty:
                message = None
            self.deliver(message)

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
        line = (json.dumps(message, separators=(",", ":")) + "\n").encode("ascii")
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
            self._device = factory(self.port, self.baudrate, timeout=0, write_timeout=1)
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
