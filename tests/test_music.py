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
