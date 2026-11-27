"""Robot music tooling: user audio stays out of Git; titles are firmware-safe."""

import importlib.util
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "firmware/robot-adapter/tools/make_music.py"
spec = importlib.util.spec_from_file_location("make_music", TOOL)
make_music = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_music)


def test_user_music_header_is_gitignored():
    result = subprocess.run(["git", "check-ignore", "-q", "firmware/robot-adapter/include/music_user.h"],
                            cwd=ROOT)
    assert result.returncode == 0


def test_titles_are_plain_ascii_without_quotes_or_backslashes():
    assert make_music.c_title('My "song" \\ café') == "My song  caf"
    assert make_music.c_title("x" * 40) == "x" * 24
    assert make_music.c_title("") == "My music"


def test_builtin_tune_is_present():
    header = (ROOT / "firmware/robot-adapter/include/music_tune.h").read_text()
    assert 'TUNE_TITLE = "Pomo Theme"' in header and "constexpr TuneNote TUNE[]" in header


VIDEO_TOOL = ROOT / "firmware/robot-adapter/tools/make_video.py"
video_spec = importlib.util.spec_from_file_location("make_video", VIDEO_TOOL)
make_video = importlib.util.module_from_spec(video_spec)
video_spec.loader.exec_module(make_video)


def test_user_video_header_is_gitignored():
    result = subprocess.run(["git", "check-ignore", "-q", "firmware/robot-adapter/include/video_user.h"],
                            cwd=ROOT)
    assert result.returncode == 0


def test_jpeg_size_reads_the_frame_header():
    # SOI, then an SOF0 segment for a 320x180 baseline JPEG.
    sof = bytes([0xFF, 0xC0, 0x00, 0x11, 0x08, 0x00, 0xB4, 0x01, 0x40]) + bytes(12)
    assert make_video.jpeg_size(bytes([0xFF, 0xD8]) + sof) == (320, 180)
