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
    for datei in ("Dockerfile", "DOCS.md", "README.md", "icon.png", "logo.png", "modell/.gitkeep"):
        assert (ADDON / datei).exists(), datei


def test_kein_persoenliches_modell_im_addon():
    """Im Repository bleibt modell/ leer – sonst bekäme jeder die Uhr eines anderen Haushalts."""
    inhalt = [p for p in (ADDON / "modell").rglob("*") if p.is_file() and p.name != ".gitkeep"]
    assert inhalt == [] or not (WURZEL / ".git").exists() or _ignoriert(inhalt)


def _ignoriert(dateien) -> bool:
    import subprocess

    ergebnis = subprocess.run(
        ["git", "check-ignore", "--no-index", *map(str, dateien)], cwd=WURZEL, capture_output=True, text=True
    )
    return len(ergebnis.stdout.splitlines()) == len(dateien)
