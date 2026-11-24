"""Serial display adapter checks with a fake port; no CoreS3 is needed."""

import io
import json
import struct
import time

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.config import Settings
from backend.hardware import FRAME_MAGIC, FrameParser, SerialDisplay, display_message
from backend.policy import PolicyConfig
from tests.camera_helpers import DecodeProcessor


class FakePort:
    def __init__(self, fail_writes=0, incoming=b""):
        self.lines = []
        self.closed = False
        self.fail_writes = fail_writes
        self.incoming = bytearray(incoming)

    def read(self, size):
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data

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
                       "sound": True, "standby": False, "camera": False}
    robot = {**snapshot(), "input_source": "robot", "powered_on": True, "monitoring_enabled": True}
    assert display_message(robot)["camera"] is True
    assert display_message({**robot, "monitoring_enabled": False})["camera"] is False
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
        time.sleep(0.01)
    display.close()
    assert port.lines[0]["display"] == "sad"
    assert port.closed and display.status == "disconnected"


class RecordingAdapter:
    def __init__(self, fail=False):
        self.published = []
        self.started = self.closed = False
        self.fail = fail
        self.status = "disconnected"

    def start(self):
        self.started = True

    def publish(self, state):
        if self.fail:
            raise RuntimeError("adapter bug")
        self.published.append(display_message(state))

    def close(self):
        self.closed = True


def test_snapshot_reports_robot_display_status():
    adapter = RecordingAdapter()
    app = create_app(config=PolicyConfig(), run_ticker=False, processor_factory=DecodeProcessor,
                     display_adapter=adapter)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["robot_display"] == "unavailable"
        adapter.status = "connected"
        ws.send_json({"type": "set_muted", "muted": False})
        assert ws.receive_json()["robot_display"] == "connected"
    plain = create_app(config=PolicyConfig(), run_ticker=False, processor_factory=DecodeProcessor)
    with TestClient(plain) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["robot_display"] == "disabled"


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


def test_firmware_clips_match_reminder_messages():
    from pathlib import Path
    from backend.policy import REMINDER_MESSAGES
    header = (Path(__file__).resolve().parents[1] / "firmware/robot-adapter/include/clips.h").read_text()
    for stage, text in REMINDER_MESSAGES.items():
        assert f"// Stage {stage}: {text}\n" in header, "rerun firmware/robot-adapter/tools/make_clips.py"


def framed(jpeg, sequence=0):
    return FRAME_MAGIC + struct.pack("<II", len(jpeg), sequence) + jpeg


def synthetic_jpeg(width=64, height=48):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 128, 128)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_frame_parser_resynchronises_and_rejects_oversized_frames():
    parser = FrameParser(max_bytes=100)
    stream = b"boot noise" + framed(b"A" * 10, 1) + framed(b"B" * 5, 2)
    assert parser.feed(stream[:7]) == []
    assert parser.feed(stream[7:20]) == []
    assert parser.feed(stream[20:]) == [b"A" * 10, b"B" * 5]
    bogus = FRAME_MAGIC + struct.pack("<II", 1000, 3)
    assert parser.feed(bogus + framed(b"C", 4)) == [b"C"], "an oversized length is skipped"
    assert parser.feed(b"xxPJ") == [] and parser.buffer == bytearray(b"xPJ")[-3:]
    assert parser.feed(b"PG" + struct.pack("<II", 1, 5) + b"D") == [b"D"]


def test_receive_hands_frames_to_the_handler_and_survives_handler_errors(caplog):
    caplog.set_level("INFO", logger="pomo.hardware")
    port = FakePort(incoming=b"pomo-robot boot reset_reason=1 camera=1\n" + framed(b"one") + framed(b"two"))
    display = SerialDisplay("/dev/fake", serial_factory=Factory([port]))
    seen = []

    def handler(frame):
        seen.append(frame)
        raise RuntimeError("handler bug")

    display.on_frame = handler
    display.deliver(display_message(snapshot()))
    assert display.receive() == 2
    assert seen == [b"one", b"two"] and display.frames_received == 2
    assert "pomo-robot boot reset_reason=1 camera=1" in caplog.text


class PresentProcessor(DecodeProcessor):
    def analyse(self, rgb):
        return {"presence": "present", "reason": "usable"}


def robot_app(adapter):
    return create_app(config=PolicyConfig(), run_ticker=False, processor_factory=PresentProcessor,
                      display_adapter=adapter)


def test_robot_camera_frames_drive_the_reminder_engine():
    adapter = RecordingAdapter()
    adapter.status = "connected"
    app = robot_app(adapter)
    runtime = app.state.runtime
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert command(ws, "set_input_source", source="robot")["input_source"] == "robot"
        state = command(ws, "set_monitoring", enabled=True)
        assert state["camera_capture_status"] == "starting"
        assert state["camera_session"] is None, "the robot token never reaches browsers"
        assert adapter.published[-1]["camera"] is True
        adapter.on_frame(synthetic_jpeg())
        state = ws.receive_json()
        assert state["observation"]["presence"] == "present"
        assert state["observation"]["source"] == "camera"
        assert state["camera_capture_status"] == "available"
        assert state["frames_received"] == 1 and state["last_frame"]["width"] == 64
        assert client.portal.call(runtime.robot_frame, synthetic_jpeg()) is True
        assert ws.receive_json()["frames_received"] == 2
        assert client.portal.call(runtime.robot_frame, b"not a jpeg") is False
        adapter.status = "unavailable"
        client.portal.call(runtime.tick)
        state = ws.receive_json()
        assert state["camera_capture_status"] == "unavailable"
        assert state["display"] == "bored"
        assert client.portal.call(runtime.robot_frame, synthetic_jpeg()) is False
        assert command(ws, "set_monitoring", enabled=False)["camera_capture_status"] == "paused"
        assert adapter.published[-1]["camera"] is False


def test_robot_camera_requires_a_configured_and_connected_robot():
    app = create_app(config=PolicyConfig(), run_ticker=False, processor_factory=PresentProcessor)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert command(ws, "set_input_source", source="robot")["type"] == "error"
    adapter = RecordingAdapter()
    with TestClient(robot_app(adapter)) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        command(ws, "set_input_source", source="robot")
        error = command(ws, "set_monitoring", enabled=True)
        assert error["type"] == "error" and "Robot not connected" in error["message"]


def test_frames_are_ignored_unless_robot_input_is_monitoring():
    adapter = RecordingAdapter()
    adapter.status = "connected"
    app = robot_app(adapter)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.receive_json()
        assert client.portal.call(app.state.runtime.robot_frame, synthetic_jpeg()) is False
        command(ws, "set_input_source", source="robot")
        assert client.portal.call(app.state.runtime.robot_frame, synthetic_jpeg()) is False


def command(ws, kind, **fields):
    ws.send_json({"type": kind, **fields})
    return ws.receive_json()
