"""The "model" is the training images (source of truth) plus the templates made
from them. This module packs both into a ZIP, reads ZIPs and directories back
and installs the bundled model on the very first start of the Home Assistant
add-on.

Layout (ZIP and directory alike):
    model.json                       export info (optional)
    images/<timestamp>_<value>.jpg
    templates/<digit>/<timestamp>_r<wheel>.png

Exports of version 1.x (lernbilder/, vorlagen/, modell.json) are read as well.
Any common prefix is tolerated, e.g. a ZIP of the whole data/ folder
(data/images/…)."""

from __future__ import annotations

import io
import json
import logging
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import cv2
import numpy as np

from .i18n import T
from .image_archive import ImageArchive, is_image, parse_name
from .recognition import DIGIT_HEIGHT, DIGIT_WIDTH
from .templates import DIGITS, Stock, Template, TemplateStore

log = logging.getLogger(__name__)

MARKER = ".bundled_model.json"
MAX_SIZE = 300 * 1024 * 1024  # bytes, for the ZIP and its unpacked content
FORMAT = 2
IMAGE_DIRS = {"images", "lernbilder"}  # lernbilder, vorlagen, modell.json: version 1.x
TEMPLATE_DIRS = {"templates", "vorlagen"}
INFO_FILES = {"model.json", "modell.json"}


class ModelError(ValueError):
    pass


@dataclass
class ModelContent:
    images: dict[str, bytes] = field(default_factory=dict)
    templates: dict[int, list[Template]] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    @property
    def template_count(self) -> int:
        return sum(len(t) for t in self.templates.values())

    def stock(self) -> Stock:
        return {d: sorted(self.templates.get(d, []), key=lambda t: t.name) for d in DIGITS}

    def is_empty(self) -> bool:
        return not self.images and not self.template_count


# ---- Reading --------------------------------------------------------------------


def read_zip(data: bytes) -> ModelContent:
    megabytes = MAX_SIZE // (1024 * 1024)
    if not data:
        raise ModelError(T("model.empty"))
    if len(data) > MAX_SIZE:
        raise ModelError(T("model.too_large", mb=megabytes))
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ModelError(T("model.not_zip")) from None
    with archive:
        files = [i for i in archive.infolist() if not i.is_dir()]
        if sum(i.file_size for i in files) > MAX_SIZE:
            raise ModelError(T("model.unpacked_too_large", mb=megabytes))
        try:
            return _collect((PurePosixPath(i.filename).parts, lambda i=i: archive.read(i)) for i in files)
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as e:
            raise ModelError(T("model.damaged", error=e)) from None
        except RuntimeError as e:  # encrypted entries
            raise ModelError(T("model.unreadable", error=e)) from None


def read_directory(source: Path) -> ModelContent:
    return _collect(
        (p.relative_to(source).parts, p.read_bytes) for p in sorted(source.rglob("*")) if p.is_file()
    )


def _collect(entries: Iterable[tuple[tuple[str, ...], Callable[[], bytes]]]) -> ModelContent:
    content = ModelContent()
    for parts, read in entries:
        path = "/".join(parts)
        if any(p.startswith(".") or p == "__MACOSX" for p in parts):
            continue  # silently ignore macOS extras (._*, .DS_Store)
        if parts[-1] in INFO_FILES:
            continue
        kind = _classify(parts)
        if kind is None:
            content.skipped.append(path)
            continue
        if kind == "image":
            name, data = parts[-1], read()
            if parse_name(name) is None or not is_image(data):
                content.skipped.append(path)
                continue
            content.images[name] = data
        else:
            digit, name = int(parts[-2]), parts[-1]
            try:
                image = cv2.imdecode(np.frombuffer(read(), np.uint8), cv2.IMREAD_GRAYSCALE)
            except cv2.error:  # pixel limit exceeded
                image = None
            if image is None:
                content.skipped.append(path)
                continue
            if image.shape != (DIGIT_HEIGHT, DIGIT_WIDTH):
                image = cv2.resize(image, (DIGIT_WIDTH, DIGIT_HEIGHT), interpolation=cv2.INTER_AREA)
            content.templates.setdefault(digit, []).append(Template(name, image))
    if content.skipped:
        log.warning(T("log.model_skipped", files=", ".join(content.skipped[:10])))
    return content


def _classify(parts: tuple[str, ...]) -> str | None:
    if len(parts) >= 2 and parts[-2] in IMAGE_DIRS:
        return "image"
    if (
        len(parts) >= 3
        and parts[-3] in TEMPLATE_DIRS
        and parts[-2] in {str(d) for d in DIGITS}
        and parts[-1].lower().endswith(".png")
    ):
        return "template"
    return None


# ---- Writing --------------------------------------------------------------------


def export(archive: ImageArchive, templates_dir: Path, info: dict) -> bytes:
    """ZIP with all training images and templates. JPEG/PNG are compressed
    already, so they are stored without compression (spares the CPU of the HA Green)."""
    buffer = io.BytesIO()
    images = archive.entries()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        template_count = 0
        for entry in images:
            z.write(entry.path, f"images/{entry.name}")
        for digit in DIGITS:
            folder = templates_dir / str(digit)
            if not folder.is_dir():
                continue
            for p in sorted(folder.glob("*.png")):
                if p.is_file() and not p.name.startswith("."):
                    z.write(p, f"templates/{digit}/{p.name}")
                    template_count += 1
        z.writestr(
            "model.json",
            json.dumps(
                {
                    "format": FORMAT,
                    "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "images": len(images),
                    "templates": template_count,
                    **info,
                },
                ensure_ascii=False,
                indent=2,
            ),
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return buffer.getvalue()


def install_bundled(source: Path, data_dir: Path, archive: ImageArchive, store: TemplateStore) -> dict | None:
    """Installs the bundled model exactly once – and only into an empty data
    directory, so an add-on update never overwrites what was learned.
    Returns the content of the marker file, None = nothing to do."""
    marker = data_dir / MARKER
    if marker.exists():
        return None
    content = read_directory(source) if source.is_dir() else ModelContent()
    if content.is_empty():
        # No marker, so a model added to the image later still gets installed.
        log.debug(T("log.no_bundled_model", path=source))
        return None
    has_data = archive.count() > 0 or any(p.name[:1] != "." for p in store.directory.glob("*/*.png"))
    if has_data:
        info = {"installed": False, "reason": "data_present"}
        log.info(T("log.bundled_model_skipped"))
    else:
        archive.replace(content.images)
        store.replace(content.stock())
        info = {"installed": True, "images": len(content.images), "templates": content.template_count}
        log.info(T("log.bundled_model_installed", images=len(content.images), templates=content.template_count))
    info["time"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(info, ensure_ascii=False))
    return info


def bundled_info(data_dir: Path) -> dict | None:
    try:
        return json.loads((data_dir / MARKER).read_text())
    except (OSError, ValueError):
        return None
