import logging
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from backend.app import create_app
from backend.config import CameraConfig, PerceptionConfig, BehaviourConfig

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
logging.basicConfig(level=logging.INFO)
port = int(os.getenv("POMO_PORT", "8000"))
if not 1 <= port <= 65535:
    raise ValueError("POMO_PORT must be between 1 and 65535")
dev = os.getenv("POMO_DEV_CONTROLS", "true").lower()
if dev not in {"true", "false"}:
    raise ValueError("POMO_DEV_CONTROLS must be true or false")
uvicorn.run(create_app(dev == "true", camera_config=CameraConfig.from_env(),
                       perception_config=PerceptionConfig.from_env(),
                       behaviour_config=BehaviourConfig.from_env()), host=os.getenv("POMO_HOST", "127.0.0.1"),
            port=port, ws_max_size=4096)
