"""Debug image: camera image with the ROIs drawn in, below it the processed digits."""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from .i18n import T, translate
from .recognition import DigitResult

GREEN = (0, 200, 0)
RED = (0, 0, 255)
GREY = (170, 170, 170)
FONT = cv2.FONT_HERSHEY_SIMPLEX
ZOOM = 3
GAP = 8


def draw(
    image: np.ndarray,
    rois: Sequence[Sequence[int]],
    digits: Sequence[np.ndarray],
    results: Sequence[DigitResult],
    certain_per_wheel: Sequence[bool],
    value: float | None,
    certain: bool,
    language: str | None = None,
) -> bytes:
    top = image.copy()
    for (x1, y1, x2, y2), r, ok in zip(rois, results, certain_per_wheel):
        colour = GREEN if ok else RED
        cv2.rectangle(top, (x1, y1), (x2 - 1, y2 - 1), colour, 1)
        cv2.putText(top, str(r.wheel), (x1, y1 - 4), FONT, 0.4, colour, 1, cv2.LINE_AA)

    # Tiles: processed digit enlarged + caption
    tile_w = digits[0].shape[1] * ZOOM
    tile_h = digits[0].shape[0] * ZOOM
    text_h = 44
    tiles = []
    for d, r, ok in zip(digits, results, certain_per_wheel):
        tile = cv2.cvtColor(np.zeros((tile_h + text_h, tile_w), np.uint8), cv2.COLOR_GRAY2BGR)
        large = cv2.resize(d, (tile_w, tile_h), interpolation=cv2.INTER_NEAREST)
        tile[:tile_h] = cv2.cvtColor(large, cv2.COLOR_GRAY2BGR)
        colour = GREEN if ok else RED
        cv2.rectangle(tile, (0, 0), (tile_w - 1, tile_h - 1), colour, 1)
        digit = "?" if r.digit is None else str(r.digit)
        score = "" if r.score is None else f"{r.score:.2f}"
        cv2.putText(tile, f"{digit} {score}", (2, tile_h + 16), FONT, 0.45, colour, 1, cv2.LINE_AA)
        if r.second is not None:
            cv2.putText(tile, f"{r.second} {r.second_score:.2f}", (2, tile_h + 36), FONT, 0.4, GREY, 1, cv2.LINE_AA)
        tiles.append(tile)

    spacer = np.zeros((tile_h + text_h, GAP, 3), np.uint8)
    parts = []
    for tile in tiles:
        parts += [tile, spacer]
    strip = np.hstack(parts[:-1])

    # ASCII only: OpenCV's Hershey fonts know no umlauts
    title = translate("debug.title", language, value="-" if value is None else f"{value:.3f}",
                      verdict=T("ui.certain" if certain else "ui.uncertain"))
    head = np.zeros((28, max(top.shape[1], strip.shape[1]), 3), np.uint8)
    cv2.putText(head, title, (6, 19), FONT, 0.55, GREEN if certain else RED, 1, cv2.LINE_AA)

    width = head.shape[1]
    ok, png = cv2.imencode(".png", np.vstack([_pad(top, width), head, _pad(strip, width)]))
    if not ok:
        raise RuntimeError(T("error.png"))
    return png.tobytes()


def _pad(part: np.ndarray, width: int) -> np.ndarray:
    rest = width - part.shape[1]
    if rest <= 0:
        return part
    return cv2.copyMakeBorder(part, 0, 0, 0, rest, cv2.BORDER_CONSTANT, value=(0, 0, 0))
