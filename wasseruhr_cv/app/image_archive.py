"""Archive of every image sent to /learn: <directory>/<timestamp>_<value>.jpg.

The images are stored byte for byte as they were received. The templates can be
rebuilt from the archive at any time (e.g. after an ROI change). The timestamp
is the identity of a training image; the value in the file name can be
corrected later."""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from .i18n import T

log = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y%m%dT%H%M%S%fZ"  # UTC -> alphabetical = chronological
EXTENSIONS = {".jpg", ".jpeg", ".png", ".img", ".bild"}  # .bild: version 1.x


@dataclass(frozen=True)
class TrainingImage:
    timestamp: str
    value: float
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def time(self) -> datetime:
        return datetime.strptime(self.timestamp, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


def parse_name(name: str) -> tuple[str, float] | None:
    """'<timestamp>_<value>.<extension>' -> (timestamp, value), otherwise None."""
    path = Path(name)
    if path.name != name or name.startswith(".") or path.suffix.lower() not in EXTENSIONS:
        return None
    try:
        timestamp, value_text = path.stem.split("_", 1)
        datetime.strptime(timestamp, TIMESTAMP_FORMAT)
        value = float(value_text)
    except ValueError:
        return None
    if not value >= 0:  # also NaN
        return None
    return timestamp, value


def is_image(data: bytes) -> bool:
    return _extension(data) != ".img"


class ImageArchive:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self._lock = threading.Lock()
        self._latest: datetime | None = None

    def save(self, data: bytes, value: float) -> str:
        """Stores the image and returns its (unique) timestamp."""
        with self._lock:
            timestamp = self._new_timestamp()
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{timestamp}_{value:.3f}{_extension(data)}"
            path.write_bytes(data)
        log.info(T("log.image_archived", name=path.name))
        return timestamp

    def entries(self) -> list[TrainingImage]:
        """All readable archive entries, oldest first."""
        if not self.directory.is_dir():
            return []
        entries = []
        for path in sorted(p for p in self.directory.iterdir() if p.is_file() and not p.name.startswith(".")):
            try:
                timestamp, value_text = path.stem.split("_", 1)
                datetime.strptime(timestamp, TIMESTAMP_FORMAT)
                value = float(value_text)
            except ValueError:
                log.warning(T("log.image_name_unknown", name=path.name))
                continue
            entries.append(TrainingImage(timestamp, value, path))
        return entries

    def count(self) -> int:
        return len(self.entries())

    def find(self, name: str) -> TrainingImage | None:
        """Only names that really are in the archive – never a path from outside."""
        return next((e for e in self.entries() if e.name == name), None)

    # ---- Admin ----------------------------------------------------------------

    def delete(self, name: str) -> TrainingImage:
        with self._lock:
            entry = self.find(name)
            if entry is None:
                raise KeyError(name)
            entry.path.unlink()
        log.info(T("log.image_deleted", name=name))
        return entry

    def change_value(self, name: str, value: float) -> TrainingImage:
        """Corrects the value in the file name; timestamp and image stay."""
        with self._lock:
            entry = self.find(name)
            if entry is None:
                raise KeyError(name)
            new = entry.path.with_name(f"{entry.timestamp}_{value:.3f}{entry.path.suffix}")
            entry.path.rename(new)
        log.info(T("log.image_corrected", old=name, new=new.name))
        return TrainingImage(entry.timestamp, value, new)

    def merge(self, files: Mapping[str, bytes]) -> int:
        """Takes over training images whose timestamp does not exist yet.
        Returns the number of newly added images."""
        with self._lock:
            known = {e.timestamp for e in self.entries()}
            self.directory.mkdir(parents=True, exist_ok=True)
            new = 0
            for name, data in sorted(files.items()):
                timestamp = parse_name(name)[0]
                if timestamp in known:
                    continue
                (self.directory / name).write_bytes(data)
                known.add(timestamp)
                new += 1
            self._latest = None  # determine strictly monotonic timestamps again
        log.info(T("log.images_merged", new=new, known=len(files) - new))
        return new

    def replace(self, files: Mapping[str, bytes]) -> int:
        """Replaces the whole archive (atomically via a sibling directory)."""
        with self._lock:
            new_dir = self.directory.with_name(self.directory.name + ".new")
            old_dir = self.directory.with_name(self.directory.name + ".old")
            shutil.rmtree(new_dir, ignore_errors=True)
            shutil.rmtree(old_dir, ignore_errors=True)
            new_dir.mkdir(parents=True)
            for name, data in files.items():
                (new_dir / name).write_bytes(data)
            if self.directory.exists():
                self.directory.rename(old_dir)
            new_dir.rename(self.directory)
            shutil.rmtree(old_dir, ignore_errors=True)
            self._latest = None
        log.info(T("log.archive_replaced", n=len(files)))
        return len(files)

    def _new_timestamp(self) -> str:
        if self._latest is None:
            self._latest = max(
                (datetime.strptime(e.timestamp, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc) for e in self.entries()),
                default=datetime.min.replace(tzinfo=timezone.utc),
            )
        # strictly monotonic, even if the clock jumps back
        now = max(datetime.now(timezone.utc), self._latest + timedelta(microseconds=1))
        self._latest = now
        return now.strftime(TIMESTAMP_FORMAT)


def _extension(data: bytes) -> str:
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data.startswith(b"\x89PNG"):
        return ".png"
    return ".img"
