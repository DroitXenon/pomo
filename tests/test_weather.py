"""Weather parsing and refresh loop with a fake opener; no network access."""

import asyncio
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest

from backend.config import Settings, WeatherConfig
from backend.weather import condition, fetch_weather, weather_loop

SAMPLE = {
    "current": {"time": "2026-11-27T10:00", "temperature_2m": 8.6, "weather_code": 61},
    "daily": {"time": ["2026-11-27"], "temperature_2m_max": [10.4], "temperature_2m_min": [4.5]},
}


class Opener:
    def __init__(self, payload=SAMPLE):
        self.urls = []
        self.payload = payload

    def __call__(self, url, timeout):
        assert timeout > 0
        self.urls.append(url)
        return io.BytesIO(json.dumps(self.payload).encode())


def test_fetch_parses_open_meteo_and_sends_only_coordinates():
    opener = Opener()
    assert fetch_weather(51.4988, -0.1749, opener=opener) == {"wt": 9, "wh": 10, "wl": 4, "wc": "rain"}
    url = urlparse(opener.urls[0])
    assert url.netloc == "api.open-meteo.com"
    query = parse_qs(url.query)
    assert query["latitude"] == ["51.4988"] and query["longitude"] == ["-0.1749"]
    assert set(query) == {"latitude", "longitude", "current", "daily", "forecast_days", "timezone"}


@pytest.mark.parametrize("code, name", [
    (0, "clear"), (2, "partly"), (3, "cloudy"), (45, "fog"), (53, "rain"), (66, "rain"),
    (80, "rain"), (73, "snow"), (86, "snow"), (95, "storm"), (99, "storm"), (42, "cloudy"),
])
def test_wmo_codes_map_to_robot_icons(code, name):
    assert condition(code) == name


def test_loop_publishes_weather_and_keeps_last_value_on_failure(caplog):
    caplog.set_level("INFO", logger="pomo.weather")
    results = [{"wt": 9, "wh": 10, "wl": 4, "wc": "rain"}, OSError("offline"), OSError("offline")]
    published, sleeps = [], []

    class Adapter:
        def set_weather(self, fields):
            published.append(fields)

    def fetch(latitude, longitude):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def sleep(seconds):
        sleeps.append(seconds)
        if not results:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(weather_loop(Adapter(), WeatherConfig(), fetch=fetch, sleep=sleep))
    assert published == [{"wt": 9, "wh": 10, "wl": 4, "wc": "rain", "wp": "London"}]
    assert sleeps == [900, 900, 900]
    assert sum("Weather unavailable" in record.message for record in caplog.records) == 1


def test_weather_settings_defaults_validation_and_disable():
    defaults = Settings.from_env({}).weather
    assert (defaults.enabled, defaults.latitude, defaults.longitude, defaults.place) == (True, 51.4988, -0.1749, "London")
    custom = Settings.from_env({"POMO_WEATHER_LATITUDE": "48.85", "POMO_WEATHER_LONGITUDE": "2.35",
                                "POMO_WEATHER_PLACE": "Paris", "POMO_WEATHER_ENABLED": "FALSE"}).weather
    assert (custom.latitude, custom.place, custom.enabled) == (48.85, "Paris", False)
    for bad in ({"POMO_WEATHER_LATITUDE": "91"}, {"POMO_WEATHER_LONGITUDE": "-181"},
                {"POMO_WEATHER_REFRESH_SECONDS": "60"}, {"POMO_WEATHER_PLACE": 'Lon"don'},
                {"POMO_WEATHER_PLACE": "A very long place name"}, {"POMO_WEATHER_ENABLED": "yes"}):
        with pytest.raises(ValueError):
            Settings.from_env(bad)
