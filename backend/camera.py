"""Long-lived image decoder and perception worker; frames stay in memory."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

from .config import CameraConfig, PerceptionConfig
from .perception import FacePerception


class FrameProcessor:
    def __init__(self, config: CameraConfig, perception_config: PerceptionConfig | None = None):
        self.config = config
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='pomo-camera')
        self.perception = None
        self.perception_config = perception_config or PerceptionConfig()

    def open(self):
        self.perception = FacePerception(self.perception_config, self.config.model_path)

    def analyse(self, rgb):
        return self.perception.analyse(rgb)

    def process(self, encoded: bytes):
        import cv2
        import numpy as np
        from PIL import Image, UnidentifiedImageError
        # Inspect dimensions before allocating a decoded OpenCV image.
        try:
            with Image.open(BytesIO(encoded)) as image:
                width, height = image.size
                if image.format != 'JPEG' or not (0 < width <= self.config.width
                                                  and 0 < height <= self.config.height):
                    raise ValueError('Expected a JPEG within configured dimensions')
                image.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError('Invalid JPEG') from error
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if frame is None:
            raise ValueError('JPEG decode failed')
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return {'width': rgb.shape[1], 'height': rgb.shape[0],
                'observation': self.analyse(rgb)}

    def close(self):
        if self.perception is not None:
            self.perception.close()
            self.perception = None
