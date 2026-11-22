"""start.py: Add-on-Optionen -> Umgebungsvariablen, ohne Docker-Compose-Variablen zu zerstören."""

import os

import pytest

import start


@pytest.fixture(autouse=True)
def saubere_umgebung(monkeypatch):
    for variable in start.ZUORDNUNG.values():
        monkeypatch.delenv(variable, raising=False)


def test_optionen_werden_zu_umgebungsvariablen():
    start.umgebung_setzen({
        "lerneffekt": False, "min_score": 0.75, "kamera": "camera.wasseruhr",
        "admin_nur_ueber_ingress": True, "log_level": "DEBUG",
    })
    assert os.environ["LERNEFFEKT"] == "aus"
    assert os.environ["MIN_SCORE"] == "0.75"
    assert os.environ["KAMERA"] == "camera.wasseruhr"
    assert os.environ["ADMIN_NUR_INGRESS"] == "an"
    assert os.environ["LOG_LEVEL"] == "DEBUG"


def test_ohne_options_json_bleiben_compose_variablen(monkeypatch):
    monkeypatch.setenv("LERNEFFEKT", "aus")
    monkeypatch.setenv("ROIS", "[[1,2,30,40],[1,2,30,40],[1,2,30,40],[1,2,30,40]]")
    start.umgebung_setzen({})  # Docker Compose: keine /data/options.json
    assert os.environ["LERNEFFEKT"] == "aus"
    assert os.environ["ROIS"].startswith("[[1,2")


def test_leere_option_ueberschreibt_nichts(monkeypatch):
    monkeypatch.setenv("KAMERA", "camera.aus_compose")
    start.umgebung_setzen({"kamera": "", "rois": "   "})
    assert os.environ["KAMERA"] == "camera.aus_compose"
    assert "ROIS" not in os.environ
