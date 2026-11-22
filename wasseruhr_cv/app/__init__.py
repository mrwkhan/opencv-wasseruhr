"""Wasseruhr-CV: liest eine Wasseruhr per klassischem Computer Vision ab."""

import os

__version__ = "1.3.1"

# Schutz vor Dekompressionsbomben: Ein JPEG von wenigen hundert Bytes kann
# 30000x30000 Pixel behaupten und beim Dekodieren Gigabytes anfordern. OpenCV
# liest diese Grenze beim Laden der Bibliothek, sie muss also vor dem ersten
# "import cv2" gesetzt sein (im Image zusätzlich per ENV im Dockerfile).
MAX_BILDPUNKTE = 25_000_000
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(MAX_BILDPUNKTE))
