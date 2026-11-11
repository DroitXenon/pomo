"""Startup configuration validation without running a server or reading .env."""

import pytest

from backend.config import CameraConfig, PerceptionConfig, Settings
from backend.policy import PolicyConfig


def test_defaults_are_local_muted_and_match_policy_defaults():
    settings = Settings.from_env({})
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.dev_controls is True
    assert settings.sound_enabled is False
    assert settings.policy == PolicyConfig()


def test_explicit_environment_overrides_all_settings():
    settings = Settings.from_env({
        "POMO_HOST": " 0.0.0.0 ", "POMO_PORT": "8765",
        "POMO_DEV_CONTROLS": " False ", "POMO_SOUND_ENABLED": "TRUE",
        "POMO_ABSENCE_SECONDS": "2.5",
        "POMO_REMINDER_COOLDOWN_SECONDS": "0",
        "POMO_OBSERVATION_TIMEOUT_SECONDS": "4.25",
        "POMO_UNCERTAINTY_SECONDS": "2",
    })
    assert settings.host == "0.0.0.0"
    assert settings.port == 8765
    assert settings.dev_controls is False
    assert settings.sound_enabled is True
    assert settings.policy == PolicyConfig(2.5, 0, 4.25, 2)


def test_process_environment_is_used_only_when_no_mapping_is_supplied(monkeypatch):
    for name in ("POMO_HOST", "POMO_DEV_CONTROLS", "POMO_SOUND_ENABLED",
                 "POMO_ABSENCE_SECONDS", "POMO_REMINDER_COOLDOWN_SECONDS",
                 "POMO_OBSERVATION_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("POMO_PORT", "8123")
    assert Settings.from_env().port == 8123
    assert Settings.from_env({}).port == 8000


@pytest.mark.parametrize("name", ["POMO_DEV_CONTROLS", "POMO_SOUND_ENABLED"])
@pytest.mark.parametrize("value", ["", "1", "0", "yes", "off", "truthy"])
def test_boolean_settings_reject_non_boolean_words(name, value):
    with pytest.raises(ValueError, match=name):
        Settings.from_env({name: value})


@pytest.mark.parametrize("value", ["0", "65536", "-1", "8.5", "nan", "", "port"])
def test_invalid_ports_are_rejected(value):
    with pytest.raises(ValueError, match="POMO_PORT"):
        Settings.from_env({"POMO_PORT": value})


@pytest.mark.parametrize("value", ["1", "65535"])
def test_port_boundaries_are_accepted(value):
    assert Settings.from_env({"POMO_PORT": value}).port == int(value)


@pytest.mark.parametrize("name", [
    "POMO_ABSENCE_SECONDS", "POMO_REMINDER_COOLDOWN_SECONDS",
    "POMO_OBSERVATION_TIMEOUT_SECONDS",
    "POMO_UNCERTAINTY_SECONDS",
])
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-1", "", "fast"])
def test_invalid_duration_settings_are_rejected(name, value):
    with pytest.raises(ValueError):
        Settings.from_env({name: value})


@pytest.mark.parametrize("name", ["POMO_ABSENCE_SECONDS", "POMO_OBSERVATION_TIMEOUT_SECONDS", "POMO_UNCERTAINTY_SECONDS"])
def test_detection_durations_must_be_positive(name):
    with pytest.raises(ValueError):
        Settings.from_env({name: "0"})


@pytest.mark.parametrize("host", ["", " \t "])
def test_empty_bind_host_is_rejected(host):
    with pytest.raises(ValueError, match="POMO_HOST"):
        Settings.from_env({"POMO_HOST": host})


def test_camera_and_reminder_settings_share_one_environment_mapping(monkeypatch):
    monkeypatch.setenv("POMO_CAMERA_WIDTH", "1280")
    settings = Settings.from_env({
        "POMO_CAMERA_WIDTH": "800", "POMO_CAMERA_HEIGHT": "600",
        "POMO_PERCEPTION_MIN_BLUR_VARIANCE": "7",
        "POMO_ABSENCE_SECONDS": "8",
        "POMO_RETURN_SECONDS": "0.75",
        "POMO_TRACKING_LOSS_GRACE_SECONDS": "0.5",
    })
    assert settings.camera.width == 800 and settings.camera.height == 600
    assert settings.perception.min_blur_variance == 7
    assert settings.policy.absence_seconds == settings.behaviour.absence_seconds == 8
    assert settings.behaviour.return_seconds == 0.75
    assert Settings.from_env({}).camera.width == 640


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_camera_and_perception_configuration_is_rejected(value):
    with pytest.raises(ValueError):
        CameraConfig(timeout_seconds=value)
    with pytest.raises(ValueError):
        PerceptionConfig(min_blur_variance=value)
