"""Consistency of the add-on: versions, options, translations, repository."""

import re
from pathlib import Path

import yaml

import start
from app import __version__
from app.migration import LEGACY_OPTIONS

ROOT = Path(__file__).parent.parent
ADDON = ROOT / "wasseruhr_cv"
CONFIG = yaml.safe_load((ADDON / "config.yaml").read_text())


def test_versions_match():
    pyproject = re.search(r'^version = "(.+)"$', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
    assert CONFIG["version"] == __version__ == pyproject
    assert f"## {__version__}" in (ADDON / "CHANGELOG.md").read_text()


def test_every_option_reaches_the_service():
    assert set(CONFIG["schema"]) == set(start.MAPPING)
    assert set(CONFIG["options"]) <= set(CONFIG["schema"])


def test_option_names_are_english_and_old_ones_are_migrated():
    for option in CONFIG["schema"]:
        assert re.fullmatch(r"[a-z0-9_]+", option) and option not in LEGACY_OPTIONS, option
    assert set(LEGACY_OPTIONS.values()) <= set(CONFIG["schema"])


def test_every_option_is_translated():
    for language in ("en", "de"):
        translation = yaml.safe_load((ADDON / "translations" / f"{language}.yaml").read_text())
        assert set(translation["configuration"]) == set(CONFIG["schema"]), language
        for option in CONFIG["schema"]:
            entry = translation["configuration"][option]
            assert entry["name"] and entry["description"], (language, option)
        assert set(translation["network"]) == set(CONFIG["ports"])


def test_repository_matches_the_addon():
    repository = yaml.safe_load((ROOT / "repository.yaml").read_text())
    assert repository["url"] == CONFIG["url"]
    assert CONFIG["slug"] == ADDON.name
    assert CONFIG.get("ingress_port", 8099) == 8099 == int(start.PORT)  # 8099 = HA default
    assert "HEALTHCHECK" in (ADDON / "Dockerfile").read_text()  # watchdog
    for file in ("Dockerfile", "DOCS.md", "README.md", "icon.png", "logo.png", "model/images", "model/templates"):
        assert (ADDON / file).exists(), file


def test_bundled_model_is_complete():
    """The initial model is part of the project: all digits 0–9, valid file names."""
    from app.image_archive import ImageArchive
    from app.templates import _from_disk

    images = ImageArchive(ADDON / "model" / "images").entries()
    assert len(images) >= 10
    assert all(e.path.suffix == ".png" for e in images)  # lossless, platform independent
    templates = _from_disk(ADDON / "model" / "templates")
    assert all(templates[d] for d in range(10)), {d: len(t) for d, t in templates.items()}


def test_bundled_model_shows_only_the_counter():
    """Privacy: outside the counter (ROIs + 16 px) every training image must be black –
    otherwise e.g. the serial number of the meter or the room would be visible on GitHub."""
    import cv2
    import numpy as np
    from app.config import DEFAULT_ROIS

    margin = 16
    x1, y1 = min(r[0] for r in DEFAULT_ROIS) - margin, min(r[1] for r in DEFAULT_ROIS) - margin
    x2, y2 = max(r[2] for r in DEFAULT_ROIS) + margin, max(r[3] for r in DEFAULT_ROIS) + margin
    images = [p for p in (ADDON / "model" / "images").iterdir() if p.is_file()]
    for path in [*images, ROOT / "tests" / "example.jpg", ROOT / "tests" / "other.jpg"]:
        image = cv2.imread(str(path))
        outside = image.copy()
        outside[y1:y2, x1:x2] = 0
        limit = 0 if path.suffix == ".png" else 40  # JPEG: compression noise at the edge
        assert int(outside.max()) <= limit, f"{path.name} shows more than the counter"
        assert np.count_nonzero(outside > 10) < (5000 if path.suffix != ".png" else 1), path.name


def test_bundled_model_is_installed_on_first_start(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Config
    from app.main import create_app

    with TestClient(create_app(Config(data_dir=tmp_path, model_dir=ADDON / "model"))) as c:
        status = c.get("/status").json()
        assert status["missing_templates"] == [] and status["training_images"] >= 10
        assert c.get("/admin/info").json()["bundled_model"]["installed"] is True
