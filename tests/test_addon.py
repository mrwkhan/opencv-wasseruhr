"""Konsistenz des Add-ons: Versionen, Optionen, Übersetzungen, Repository."""

import re
from pathlib import Path

import yaml

import start
from app import __version__

WURZEL = Path(__file__).parent.parent
ADDON = WURZEL / "wasseruhr_cv"
KONFIG = yaml.safe_load((ADDON / "config.yaml").read_text())


def test_versionen_gleich():
    pyproject = re.search(r'^version = "(.+)"$', (WURZEL / "pyproject.toml").read_text(), re.M).group(1)
    assert KONFIG["version"] == __version__ == pyproject
    assert f"## {__version__}" in (ADDON / "CHANGELOG.md").read_text()


def test_jede_option_kommt_beim_dienst_an():
    assert set(KONFIG["schema"]) == set(start.ZUORDNUNG)
    assert set(KONFIG["options"]) <= set(KONFIG["schema"])


def test_jede_option_ist_uebersetzt():
    for sprache in ("de", "en"):
        uebersetzung = yaml.safe_load((ADDON / "translations" / f"{sprache}.yaml").read_text())
        for option in KONFIG["schema"]:
            eintrag = uebersetzung["configuration"][option]
            assert eintrag["name"] and eintrag["description"], (sprache, option)
        assert set(uebersetzung["network"]) == set(KONFIG["ports"])


def test_repository_passt_zum_addon():
    repo = yaml.safe_load((WURZEL / "repository.yaml").read_text())
    assert repo["url"] == KONFIG["url"]
    assert KONFIG["slug"] == ADDON.name
    assert KONFIG.get("ingress_port", 8099) == 8099 == int(start.PORT)  # 8099 = HA-Standard
    assert "HEALTHCHECK" in (ADDON / "Dockerfile").read_text()  # Watchdog
    for datei in ("Dockerfile", "DOCS.md", "README.md", "icon.png", "logo.png", "modell/lernbilder", "modell/vorlagen"):
        assert (ADDON / datei).exists(), datei


def test_mitgeliefertes_modell_ist_vollstaendig():
    """Das initiale Modell gehört zum Projekt: alle Ziffern 0–9, gültige Dateinamen."""
    from app.lernbilder import LernbildArchiv
    from app.vorlagen import _von_platte

    lernbilder = LernbildArchiv(ADDON / "modell" / "lernbilder").eintraege()
    assert len(lernbilder) >= 10
    assert all(e.pfad.suffix == ".png" for e in lernbilder)  # verlustfrei, plattformunabhängig
    vorlagen = _von_platte(ADDON / "modell" / "vorlagen")
    assert all(vorlagen[z] for z in range(10)), {z: len(v) for z, v in vorlagen.items()}


def test_mitgeliefertes_modell_zeigt_nur_das_zaehlwerk():
    """Datenschutz: außerhalb des Zählwerks (ROIs + 16 px) muss jedes Lernbild schwarz sein –
    sonst wären z. B. die Seriennummer der Uhr oder der Raum auf GitHub zu sehen."""
    import cv2
    import numpy as np
    from app.konfig import STANDARD_ROIS

    rand = 16
    x1, y1 = min(r[0] for r in STANDARD_ROIS) - rand, min(r[1] for r in STANDARD_ROIS) - rand
    x2, y2 = max(r[2] for r in STANDARD_ROIS) + rand, max(r[3] for r in STANDARD_ROIS) + rand
    bilder = [p for p in (ADDON / "modell" / "lernbilder").iterdir() if p.is_file()]
    for pfad in [*bilder, WURZEL / "tests" / "beispiel.jpg", WURZEL / "tests" / "anderes.jpg"]:
        bild = cv2.imread(str(pfad))
        aussen = bild.copy()
        aussen[y1:y2, x1:x2] = 0
        grenze = 0 if pfad.suffix == ".png" else 40  # JPEG: Kompressionsrauschen am Rand
        assert int(aussen.max()) <= grenze, f"{pfad.name} zeigt mehr als das Zählwerk"
        assert np.count_nonzero(aussen > 10) < (5000 if pfad.suffix != ".png" else 1), pfad.name


def test_mitgeliefertes_modell_wird_beim_ersten_start_uebernommen(tmp_path):
    from fastapi.testclient import TestClient

    from app.konfig import Konfig
    from app.main import create_app

    with TestClient(create_app(Konfig(daten_verzeichnis=tmp_path, modell_verzeichnis=ADDON / "modell"))) as c:
        status = c.get("/status").json()
        assert status["fehlende_vorlagen"] == [] and status["lernbilder"] >= 10
        assert c.get("/admin/info").json()["erstausstattung"]["uebernommen"] is True
