"""Serial display adapter checks with a fake port; no CoreS3 is needed."""

import json

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.config import Settings
from backend.hardware import SerialDisplay, display_message
from backend.policy import PolicyConfig
from tests.camera_helpers import DecodeProcessor


class FakePort:
    def __init__(self, fail_writes=0):
        self.lines = []
        self.closed = False
        self.fail_writes = fail_writes

    def write(self, data):
        if self.fail_writes:
            self.fail_writes -= 1
            raise OSError("device unplugged")
        self.lines.append(json.loads(data.decode("ascii")))
        assert data.endswith(b"\n")

    def flush(self):
        pass

    def close(self):
        self.closed = True


class Factory:
    def __init__(self, ports=None, failures=0):
        self.ports = list(ports or [])
        self.failures = failures
        self.calls = 0

    def __call__(self, port, baudrate, **kwargs):
        self.calls += 1
        assert kwargs["write_timeout"] > 0
        if self.failures:
            self.failures -= 1
            raise OSError(f"could not open {port}")
        return self.ports.pop(0)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def snapshot(display="happy", active=False, reminder_id=0, stage=0, muted=False, standby=False):
    return {"display": display, "muted": muted, "standby": standby,
            "reminder": {"active": active, "id": reminder_id, "stage": stage, "message": None}}


def test_message_is_compact_and_only_carries_render_state():
    message = display_message(snapshot("sad", True, 3, 1))
    assert message == {"v": 1, "display": "sad", "reminder": 3, "stage": 1,
                       "sound": True, "standby": False}
    assert display_message(snapshot("bored", False, 4, 2, muted=True, standby=True))["reminder"] == 0


def test_publish_keeps_only_the_newest_pending_message_and_skips_duplicates():
    display = SerialDisplay("/dev/fake", serial_factory=Factory([FakePort()]))
    display.publish(snapshot("happy"))
    display.publish(snapshot("happy"))
    display.publish(snapshot("surprised"))
    assert display._pending.qsize() == 1
    assert display._pending.get_nowait()["display"] == "surprised"


def test_missing_device_is_unavailable_then_retried_with_latest_state():
    clock = Clock()
    port = FakePort()
    factory = Factory([port], failures=1)
    display = SerialDisplay("/dev/fake", serial_factory=factory, clock=clock, retry_seconds=2)
    assert display.deliver(display_message(snapshot("surprised"))) is False
    assert display.status == "unavailable"
    assert display.deliver(display_message(snapshot("sad", True, 1, 1))) is False
    assert factory.calls == 1, "no reconnect before the retry interval"
    clock.now = 2.0
    assert display.deliver() is True, "heartbeat resends the newest state after reconnect"
    assert display.status == "connected"
    assert port.lines == [display_message(snapshot("sad", True, 1, 1))]


def test_write_failure_disconnects_and_reconnects_without_raising():
    clock = Clock()
    first, second = FakePort(fail_writes=1), FakePort()
    display = SerialDisplay("/dev/fake", serial_factory=Factory([first, second]), clock=clock,
                            retry_seconds=1, heartbeat_seconds=5)
    assert display.deliver(display_message(snapshot("happy"))) is False
    assert first.closed and display.status == "unavailable"
    clock.now = 1.0
    assert display.deliver() is True
    assert second.lines[-1]["display"] == "happy"


def test_heartbeat_repeats_last_message_only_when_due():
    clock = Clock()
    port = FakePort()
    display = SerialDisplay("/dev/fake", serial_factory=Factory([port]), clock=clock,
                            heartbeat_seconds=2)
    assert display.deliver() is False, "nothing to repeat before the first message"
    display.deliver(display_message(snapshot("bored")))
    clock.now = 1.0
    assert display.deliver() is False
    clock.now = 2.0
    assert display.deliver() is True
    assert len(port.lines) == 2


def test_thread_writes_published_state_and_close_releases_port():
    port = FakePort()
    display = SerialDisplay("/dev/fake", serial_factory=Factory([port]), heartbeat_seconds=0.05)
    display.start()
    display.publish(snapshot("sad", True, 2, 1))
    for _ in range(200):
        if port.lines:
            break
        import time
        time.sleep(0.01)
    display.close()
    assert port.lines[0]["display"] == "sad"
    assert port.closed and display.status == "disconnected"


class RecordingAdapter:
    def __init__(self, fail=False):
        self.published = []
        self.started = self.closed = False
        self.fail = fail

    def start(self):
        self.started = True

    def publish(self, state):
        if self.fail:
            raise RuntimeError("adapter bug")
        self.published.append(display_message(state))

    def close(self):
        self.closed = True


@pytest.mark.parametrize("fail", [False, True])
def test_app_mirrors_broadcasts_to_the_display_adapter(fail):
    adapter = RecordingAdapter(fail=fail)
    app = create_app(config=PolicyConfig(), run_ticker=False, processor_factory=DecodeProcessor,
                     display_adapter=adapter)
    with TestClient(app) as client:
        assert adapter.started
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            ws.send_json({"type": "set_power", "enabled": False})
            assert ws.receive_json()["display"] == "idle", "adapter errors never break broadcasts"
    assert adapter.closed
    if not fail:
        assert adapter.published[0]["display"] == "bored"
        assert adapter.published[-1]["display"] == "idle"


def test_serial_settings_are_optional_and_validated():
    assert Settings.from_env({}).serial_port == ""
    settings = Settings.from_env({"POMO_SERIAL_PORT": " /dev/cu.usbmodem1 ", "POMO_SERIAL_BAUDRATE": "9600"})
    assert (settings.serial_port, settings.serial_baudrate) == ("/dev/cu.usbmodem1", 9600)
    for value in ("0", "fast"):
        with pytest.raises(ValueError, match="POMO_SERIAL_BAUDRATE"):
            Settings.from_env({"POMO_SERIAL_BAUDRATE": value})
