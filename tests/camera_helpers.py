"""Use the actual JPEG decoder without requiring a model or physical camera."""
from backend.camera import FrameProcessor


class DecodeProcessor(FrameProcessor):
    def open(self):
        pass

    def analyse(self, rgb):
        return {'presence': 'unknown', 'reason': 'test_decoder'}

    def close(self):
        pass
