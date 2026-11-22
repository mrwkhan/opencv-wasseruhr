"""Classic image processing: cut out the digits, prepare them and compare them
with learned templates by template matching (TM_CCOEFF_NORMED)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

import cv2
import numpy as np

from .i18n import T

DIGIT_WIDTH = 24
DIGIT_HEIGHT = 40
SIDE_TRIM = 3  # px cut off on the left and right of each ROI
MIN_CONTRAST_STD = 10.0  # real digits are at ~60–80 after MINMAX


class ImageError(ValueError):
    """Input image unusable (not a JPEG, ROI outside the image …)."""


@dataclass
class DigitResult:
    wheel: int
    digit: int | None
    score: float | None
    second: int | None
    second_score: float | None

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("score", "second_score"):
            if d[k] is not None:
                d[k] = round(d[k], 3)
        return d


def decode_image(data: bytes) -> np.ndarray:
    if not data:
        raise ImageError(T("image.empty"))
    try:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:
        # OPENCV_IO_MAX_IMAGE_PIXELS exceeded (see app/__init__.py)
        raise ImageError(T("image.too_large")) from None
    if image is None:
        raise ImageError(T("image.unreadable"))
    return image


def prepare_digit(roi_bgr: np.ndarray) -> np.ndarray:
    """ROI (BGR) -> normalised 24x40 greyscale image, digit bright on dark."""
    roi = roi_bgr[:, SIDE_TRIM:-SIDE_TRIM]
    # "Ink": black and red digits both have little blue AND green, the bright
    # background does not – whatever the colour of the lighting.
    ink = 255 - np.minimum(roi[:, :, 0], roi[:, :, 1])
    ink = cv2.normalize(ink, None, 0, 255, cv2.NORM_MINMAX)
    ink = cv2.GaussianBlur(ink, (3, 3), 0)
    return cv2.resize(ink, (DIGIT_WIDTH, DIGIT_HEIGHT), interpolation=cv2.INTER_AREA)


def cut_digits(image: np.ndarray, rois: Sequence[Sequence[int]]) -> list[np.ndarray]:
    height, width = image.shape[:2]
    digits = []
    for wheel, (x1, y1, x2, y2) in enumerate(rois, start=1):
        if x2 > width or y2 > height:
            raise ImageError(T("image.roi_outside", wheel=wheel, roi=str([x1, y1, x2, y2]), width=width, height=height))
        digits.append(prepare_digit(image[y1:y2, x1:x2]))
    return digits


def has_no_contrast(image: np.ndarray) -> bool:
    """Almost uniform digit (camera dark/overexposed). Useless as a template:
    TM_CCOEFF_NORMED returns 1.0 for a constant template against any image."""
    return float(image.std()) < MIN_CONTRAST_STD


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised correlation of two images of the same size (without shift)."""
    value = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])
    return value if np.isfinite(value) and abs(value) <= 1.0 + 1e-6 else 0.0


def scores_per_digit(
    digit_image: np.ndarray,
    templates: Mapping[int, Sequence[np.ndarray]],
    shift: int,
) -> dict[int, float]:
    """Best TM_CCOEFF_NORMED score per digit over all its templates, each over
    all shifts of ±shift px."""
    s = shift
    padded = cv2.copyMakeBorder(digit_image, s, s, s, s, cv2.BORDER_REPLICATE)
    scores: dict[int, float] = {}
    for digit, templates_of_digit in templates.items():
        best = None
        for template in templates_of_digit:
            result = cv2.matchTemplate(padded, template, cv2.TM_CCOEFF_NORMED)
            # Constant images give NaN/Inf – count as "no similarity".
            value = float(np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0).max())
            if best is None or value > best:
                best = value
        if best is not None:
            scores[digit] = best
    return scores


def recognise_digit(
    wheel: int,
    digit_image: np.ndarray,
    templates: Mapping[int, Sequence[np.ndarray]],
    shift: int,
) -> DigitResult:
    ranking = sorted(scores_per_digit(digit_image, templates, shift).items(), key=lambda kv: kv[1], reverse=True)
    first = ranking[0] if ranking else (None, None)
    second = ranking[1] if len(ranking) > 1 else (None, None)
    return DigitResult(wheel, first[0], first[1], second[0], second[1])


def is_certain(result: DigitResult, min_score: float, min_margin: float) -> bool:
    return (
        result.digit is not None
        and result.second_score is not None
        and result.score >= min_score
        and result.score - result.second_score >= min_margin
    )


def combine(results: Sequence[DigitResult], decimals: int) -> float | None:
    """[0,0,5,0,6,3,8,8] -> 506.388; None if a wheel was not recognised."""
    if not results or any(r.digit is None for r in results):
        return None
    whole = int("".join(str(r.digit) for r in results))
    return round(whole / 10**decimals, decimals)


def split_value(value: float, wheel_count: int, decimals: int) -> list[int]:
    """506.388 -> [0,0,5,0,6,3,8,8] (like "%09.3f" without the point for 8 wheels)."""
    if not np.isfinite(value) or value < 0:
        raise ValueError(T("value.negative"))
    width = wheel_count + 1  # +1 for the decimal point
    text = f"{value:0{width}.{decimals}f}".replace(".", "")
    if len(text) != wheel_count:
        raise ValueError(T("value.too_long", value=value, n=wheel_count))
    return [int(c) for c in text]
