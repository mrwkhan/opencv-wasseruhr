"""Wasseruhr-CV: reads a water meter with classic computer vision (English/German)."""

import os

__version__ = "2.0.0"

# Protection against decompression bombs: a JPEG of a few hundred bytes can
# claim 30000x30000 pixels and request gigabytes when decoded. OpenCV reads this
# limit when the library is loaded, so it must be set before the first
# "import cv2" (in the image also via ENV in the Dockerfile).
MAX_PIXELS = 25_000_000
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(MAX_PIXELS))
