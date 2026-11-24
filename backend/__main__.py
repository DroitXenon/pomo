import logging
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from backend.app import create_app
from backend.config import Settings
from backend.hardware import SerialDisplay

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
logging.basicConfig(level=logging.INFO)
settings = Settings.from_env()
display = (SerialDisplay(settings.serial_port, settings.serial_baudrate)
           if settings.serial_port else None)
uvicorn.run(
    create_app(
        settings.dev_controls, config=settings.policy,
        initially_muted=not settings.sound_enabled,
        camera_config=settings.camera, perception_config=settings.perception,
        behaviour_config=settings.behaviour, display_adapter=display,
    ),
    host=settings.host, port=settings.port, ws_max_size=4096,
)
