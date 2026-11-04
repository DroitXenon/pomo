import logging
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from backend.app import create_app
from backend.config import Settings

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
logging.basicConfig(level=logging.INFO)
settings = Settings.from_env()
uvicorn.run(
    create_app(
        settings.dev_controls, config=settings.policy,
        initially_muted=not settings.sound_enabled,
        camera_config=settings.camera, perception_config=settings.perception,
        behaviour_config=settings.behaviour,
    ),
    host=settings.host, port=settings.port, ws_max_size=4096,
)
