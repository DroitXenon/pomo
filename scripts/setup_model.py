"""Fetch a versioned model once and verify its recorded SHA-256."""
import hashlib
from pathlib import Path
import urllib.request

URL = ('https://storage.googleapis.com/mediapipe-models/face_landmarker/'
       'face_landmarker/float16/1/face_landmarker.task')
SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff'
TARGET = Path(__file__).resolve().parents[1] / 'models/face_landmarker.task'


def main():
    if TARGET.exists() and hashlib.sha256(TARGET.read_bytes()).hexdigest() == SHA256:
        print('Face Landmarker model checksum verified')
        return
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read(8 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError('Model checksum mismatch; existing file was preserved')
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    temporary = TARGET.with_suffix('.download')
    temporary.write_bytes(data)
    temporary.replace(TARGET)
    print('Face Landmarker model downloaded and verified')


if __name__ == '__main__':
    main()
