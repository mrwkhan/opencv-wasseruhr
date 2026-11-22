"""Template store: PNGs in <directory>/<digit>/<timestamp>_r<wheel>.png, in
memory as greyscale images per digit 0–9."""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np

from .i18n import T
from .recognition import DIGIT_HEIGHT, DIGIT_WIDTH, correlation, has_no_contrast

log = logging.getLogger(__name__)

DIGITS = range(10)
DUPLICATE_CORRELATION = 0.97


@dataclass(frozen=True)
class Template:
    name: str  # "<timestamp>_r<wheel>.png" – alphabetical = chronological
    image: np.ndarray


Stock = dict[int, list[Template]]


class TemplateStore:
    def __init__(self, directory: Path, max_per_digit: int):
        self.directory = Path(directory)
        self.max_per_digit = max_per_digit
        self._lock = threading.Lock()
        self._templates: Stock = _empty()

    # ---- Reading -------------------------------------------------------------

    def load(self) -> None:
        """Load all templates from disk into memory."""
        with self._lock:
            self._templates = _from_disk(self.directory)
        log.info(T("log.templates_loaded", counts=self.count_per_digit()))

    def snapshot(self) -> dict[int, list[np.ndarray]]:
        """Copy of the lists (images are never changed) for lock-free matching."""
        with self._lock:
            return {d: [t.image for t in templates] for d, templates in self._templates.items()}

    def count_per_digit(self) -> dict[str, int]:
        return {str(d): len(templates) for d, templates in self._templates.items()}

    def missing_digits(self) -> list[int]:
        return [d for d, templates in self._templates.items() if not templates]

    def names(self) -> dict[str, list[str]]:
        """File names per digit, oldest first."""
        with self._lock:
            return {str(d): [t.name for t in templates] for d, templates in self._templates.items()}

    def image(self, digit: int, name: str) -> np.ndarray | None:
        with self._lock:
            return next((t.image for t in self._templates.get(digit, []) if t.name == name), None)

    # ---- Writing -------------------------------------------------------------

    def learn(self, timestamp: str, digits: Sequence[int], images: Sequence[np.ndarray]) -> int:
        """Adds the digits of an image as templates (see _add), writes/deletes
        the PNGs and reloads. Returns the number of newly saved templates."""
        with self._lock:
            stock = {d: list(templates) for d, templates in self._templates.items()}
            added, removed = self._add(stock, timestamp, digits, images)
            removed_at_once = {(d, t.name) for d, t in removed}
            saved = 0
            for d, t in added:
                if (d, t.name) not in removed_at_once:
                    _write(self.directory, d, t)
                    saved += 1
            for d, t in removed:
                (self.directory / str(d) / t.name).unlink(missing_ok=True)
                log.info(T("log.template_deleted", digit=d, name=t.name))
            self._templates = _from_disk(self.directory)
        return saved

    def rebuild(self, training: Iterable[tuple[str, Sequence[int], Sequence[np.ndarray]]]) -> int:
        """Replaces all templates by those that learning the given images
        (oldest first) would have produced. Returns the number of images."""
        stock = _empty()
        count = 0
        for timestamp, digits, images in training:
            self._add(stock, timestamp, digits, images)
            count += 1
        self.replace(stock)
        return count

    def replace(self, stock: Stock) -> None:
        """Atomically replaces all templates on disk with `stock` and reloads."""
        with self._lock:
            new_dir = self.directory.with_name(self.directory.name + ".new")
            old_dir = self.directory.with_name(self.directory.name + ".old")
            shutil.rmtree(new_dir, ignore_errors=True)
            shutil.rmtree(old_dir, ignore_errors=True)
            for d in DIGITS:
                (new_dir / str(d)).mkdir(parents=True, exist_ok=True)
                for t in stock.get(d, []):
                    _write(new_dir, d, t)
            if self.directory.exists():
                self.directory.rename(old_dir)
            new_dir.rename(self.directory)
            shutil.rmtree(old_dir, ignore_errors=True)
            self._templates = _from_disk(self.directory)

    def _add(
        self, stock: Stock, timestamp: str, digits: Sequence[int], images: Sequence[np.ndarray]
    ) -> tuple[list[tuple[int, Template]], list[tuple[int, Template]]]:
        """Inserts every digit into `stock` unless it is almost identical to an
        existing template of the same digit (correlation > 0.97), then trims
        each digit to max_per_digit (oldest go first).
        Returns (added, removed) as lists of (digit, Template)."""
        if len(digits) != len(images):
            raise ValueError("digits and images must have the same length")
        added, removed = [], []
        for wheel, (d, image) in enumerate(zip(digits, images), start=1):
            if has_no_contrast(image):
                log.warning(T("log.no_contrast", wheel=wheel, digit=d))
                continue
            closest = max((correlation(image, t.image) for t in stock[d]), default=-1.0)
            if closest > DUPLICATE_CORRELATION:
                log.debug(T("log.duplicate", wheel=wheel, digit=d, value=f"{closest:.3f}"))
                continue
            t = Template(f"{timestamp}_r{wheel}.png", image)
            stock[d].append(t)
            added.append((d, t))
        for d in set(digits):
            stock[d].sort(key=lambda t: t.name)
            while len(stock[d]) > self.max_per_digit:
                removed.append((d, stock[d].pop(0)))
        return added, removed


def _empty() -> Stock:
    return {d: [] for d in DIGITS}


def _write(directory: Path, digit: int, template: Template) -> None:
    folder = directory / str(digit)
    folder.mkdir(parents=True, exist_ok=True)
    ok, png = cv2.imencode(".png", template.image)
    if not ok:
        raise RuntimeError(T("error.png"))
    (folder / template.name).write_bytes(png.tobytes())


def _from_disk(directory: Path) -> Stock:
    stock = _empty()
    for d in DIGITS:
        folder = directory / str(d)
        if not folder.is_dir():
            continue
        for path in sorted(p for p in folder.glob("*.png") if p.is_file() and not p.name.startswith(".")):
            image = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                log.warning(T("log.template_unreadable", path=path))
                continue
            if image.shape != (DIGIT_HEIGHT, DIGIT_WIDTH):
                image = cv2.resize(image, (DIGIT_WIDTH, DIGIT_HEIGHT), interpolation=cv2.INTER_AREA)
            if has_no_contrast(image):
                log.warning(T("log.template_no_contrast", path=path))
                continue
            stock[d].append(Template(path.name, image))
    return stock
