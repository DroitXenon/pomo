"""Optional weather for the robot's weather page, from Open-Meteo (no API key).

Only the configured coordinates are sent. The result is a few flat fields that
SerialDisplay adds to each robot line; the browser and the policy never use it.
"""

import asyncio
import json
import logging
import urllib.parse
import urllib.request

LOG = logging.getLogger("pomo.weather")
URL = "https://api.open-meteo.com/v1/forecast"


def condition(code):
    """Map a WMO weather code to one of the robot's icon names."""
    code = int(code)
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "storm"
    if 51 <= code <= 82:
        return "rain"
    return "cloudy"


def parse(payload):
    """Return robot fields from an Open-Meteo forecast response."""
    current, daily = payload["current"], payload["daily"]
    return {
        "wt": round(float(current["temperature_2m"])),
        "wh": round(float(daily["temperature_2m_max"][0])),
        "wl": round(float(daily["temperature_2m_min"][0])),
        "wc": condition(current["weather_code"]),
    }


def fetch_weather(latitude, longitude, opener=urllib.request.urlopen, timeout=10):
    query = urllib.parse.urlencode({
        "latitude": latitude, "longitude": longitude,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        "forecast_days": 1, "timezone": "auto",
    })
    with opener(f"{URL}?{query}", timeout=timeout) as response:
        return parse(json.loads(response.read(65536)))


async def weather_loop(adapter, config, fetch=fetch_weather, sleep=asyncio.sleep):
    """Refresh the robot's weather until cancelled; failures keep the last value."""
    failing = False
    while True:
        try:
            fields = await asyncio.to_thread(fetch, config.latitude, config.longitude)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not failing:
                LOG.warning("Weather unavailable: %s", error)
            failing = True
        else:
            if failing:
                LOG.info("Weather available again")
            failing = False
            adapter.set_weather({**fields, "wp": config.place})
        await sleep(config.refresh_seconds)
