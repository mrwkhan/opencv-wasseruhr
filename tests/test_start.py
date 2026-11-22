"""start.py: add-on options -> environment variables, without destroying Docker Compose variables."""

import os

import pytest

import start
from app.config import DEFAULT_SENSOR, LEGACY_ENV, Config


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for variable in [*start.MAPPING.values(), *LEGACY_ENV.values()]:
        monkeypatch.delenv(variable, raising=False)


def test_options_become_environment_variables():
    start.set_environment({
        "learning": False, "min_score": 0.75, "camera": "camera.water_meter",
        "admin_ingress_only": True, "log_level": "DEBUG",
    })
    assert os.environ["LEARNING"] == "false"
    assert os.environ["MIN_SCORE"] == "0.75"
    assert os.environ["CAMERA"] == "camera.water_meter"
    assert os.environ["ADMIN_INGRESS_ONLY"] == "true"
    assert os.environ["LOG_LEVEL"] == "DEBUG"
    config = Config.from_env()
    assert config.learning is False and config.admin_ingress_only is True


def test_without_options_json_compose_variables_stay(monkeypatch):
    monkeypatch.setenv("LEARNING", "false")
    monkeypatch.setenv("ROIS", "[[1,2,30,40],[1,2,30,40],[1,2,30,40],[1,2,30,40]]")
    start.set_environment({})  # Docker Compose: no /data/options.json
    assert os.environ["LEARNING"] == "false"
    assert os.environ["ROIS"].startswith("[[1,2")


def test_empty_option_overrides_nothing(monkeypatch):
    monkeypatch.setenv("CAMERA", "camera.from_compose")
    start.set_environment({"camera": "", "rois": "   "})
    assert os.environ["CAMERA"] == "camera.from_compose"
    assert "ROIS" not in os.environ


def test_cleared_entity_in_the_addon_means_none(monkeypatch):
    start.set_environment({"camera": "camera.x"}, addon=True)  # sensor/input_number cleared in the form
    config = Config.from_env()
    assert config.sensor is None and config.input_number is None
    monkeypatch.delenv("SENSOR")
    monkeypatch.delenv("INPUT_NUMBER")
    assert Config.from_env().sensor == DEFAULT_SENSOR  # Docker: default


def test_german_variables_of_version_1_still_work():
    config = Config.from_env({
        "KAMERA": "camera.x", "LERNEFFEKT": "aus", "MIN_ABSTAND": "0,1", "SPRACHE": "de",
        "ADMIN_NUR_INGRESS": "an", "MAX_VORLAGEN_PRO_ZIFFER": "12", "INTERVALL_MINUTEN": "7",
    })
    assert config.camera == "camera.x" and config.learning is False and config.min_margin == 0.1
    assert config.language == "de" and config.admin_ingress_only is True
    assert config.max_templates_per_digit == 12 and config.interval_minutes == 7
    # English names win if both are set
    assert Config.from_env({"CAMERA": "camera.new", "KAMERA": "camera.old"}).camera == "camera.new"
