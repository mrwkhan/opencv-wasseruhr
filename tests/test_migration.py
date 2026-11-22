"""Update from version 1.x: data directory, add-on options and sensor are taken over."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import start
from app.config import DEFAULT_SENSOR, LEGACY_DEFAULT_SENSOR, Config
from app.main import create_app
from app.migration import is_legacy_installation, migrate_data, migrate_options

EXAMPLE = Path(__file__).parent / "example.jpg"
MODEL = Path(__file__).parent.parent / "wasseruhr_cv" / "model"


def _data_of_version_1(data: Path) -> None:
    (data / "lernbilder").mkdir(parents=True)
    (data / "lernbilder" / "20261109T192122393524Z_506.388.jpg").write_bytes(EXAMPLE.read_bytes())
    (data / "vorlagen" / "5").mkdir(parents=True)
    png = cv2.imencode(".png", np.random.default_rng(2).integers(0, 256, (40, 24), dtype=np.uint8))[1]
    (data / "vorlagen" / "5" / "20261109T192122393524Z_r3.png").write_bytes(png.tobytes())
    (data / "zaehlerstand.json").write_text(json.dumps({"wert": 506.388, "zeit": "2026-11-22T12:00:00+00:00"}))
    (data / ".modell_erstausstattung.json").write_text(json.dumps(
        {"uebernommen": True, "lernbilder": 21, "vorlagen": 60, "zeit": "2026-11-09T19:00:00+00:00"}
    ))
    (data / "tls").mkdir()
    (data / "tls" / "selbstsigniert.crt").write_text("crt")
    (data / "tls" / "selbstsigniert.key").write_text("key")


def test_data_directory_is_migrated_once(tmp_path):
    _data_of_version_1(tmp_path)
    assert is_legacy_installation(tmp_path)
    done = migrate_data(tmp_path)
    assert len(done) == 6, done
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".bundled_model.json", "images", "meter_reading.json", "templates", "tls",
    ]
    assert json.loads((tmp_path / "meter_reading.json").read_text()) == {
        "value": 506.388, "time": "2026-11-22T12:00:00+00:00", "legacy_sensor": LEGACY_DEFAULT_SENSOR,
    }
    marker = json.loads((tmp_path / ".bundled_model.json").read_text())
    assert marker == {"installed": True, "time": "2026-11-09T19:00:00+00:00", "images": 21, "templates": 60}
    assert sorted(p.name for p in (tmp_path / "tls").iterdir()) == ["self-signed.crt", "self-signed.key"]
    assert migrate_data(tmp_path) == []  # idempotent
    assert not is_legacy_installation(tmp_path)


def test_app_starts_on_data_of_version_1(tmp_path):
    _data_of_version_1(tmp_path)
    with TestClient(create_app(Config(data_dir=tmp_path, model_dir=MODEL))) as c:
        status = c.get("/status").json()
        assert status["training_images"] == 1 and status["meter_reading"] == 506.388
        assert c.get("/admin/info").json()["bundled_model"]["installed"] is True  # not installed again
        assert c.post("/read", content=EXAMPLE.read_bytes()).json()["value"] == 506.388
        assert c.get("/admin/auto-reading").json()["sensor"] == LEGACY_DEFAULT_SENSOR


def test_migrate_options():
    current = {"camera": "", "learning": True, "min_margin": 0.08, "sensor": DEFAULT_SENSOR, "language": "auto"}
    stored = {**current, "kamera": "camera.water_meter", "lerneffekt": False, "min_abstand": 0.1, "sprache": "de",
              "sensor": DEFAULT_SENSOR}
    new = migrate_options(current, stored, legacy_installation=True)
    assert new == {"camera": "camera.water_meter", "learning": False, "min_margin": 0.1,
                   "sensor": LEGACY_DEFAULT_SENSOR, "language": "de"}
    # an own sensor stays; nothing to do without old keys and without old data
    assert migrate_options({**current, "sensor": "sensor.own"}, {}, legacy_installation=True) is None
    assert migrate_options(current, current, legacy_installation=False) is None


class _Supervisor(BaseHTTPRequestHandler):
    options: dict = {}
    saved: list = []

    def _answer(self, body: dict):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._answer({"result": "ok", "data": {"options": _Supervisor.options}})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Supervisor.saved.append(body["options"])
        self._answer({"result": "ok", "data": {}})

    def log_message(self, *_):
        pass


@pytest.fixture
def supervisor(monkeypatch, tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _Supervisor)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("SUPERVISOR_TOKEN", "secret")
    monkeypatch.setenv("SUPERVISOR_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _Supervisor.saved = []
    yield _Supervisor
    server.shutdown()
    server.server_close()


def test_start_takes_over_the_options_of_version_1(supervisor, tmp_path, capsys):
    (tmp_path / "zaehlerstand.json").write_text("{}")  # installation of version 1.x
    # unchanged names (input_number) are in options.json already, renamed ones hold their defaults
    options = {"camera": "", "interval_minutes": 5, "sensor": DEFAULT_SENSOR, "input_number": "input_number.water_meter",
               "language": "auto"}
    supervisor.options = {**options, "kamera": "camera.water_meter", "intervall_minuten": 10}
    new = start.migrate_addon_options(options)
    assert new == {"camera": "camera.water_meter", "interval_minutes": 10, "sensor": LEGACY_DEFAULT_SENSOR,
                   "input_number": "input_number.water_meter", "language": "auto"}
    assert supervisor.saved == [new]
    assert "Options of version 1.x taken over" in capsys.readouterr().out


def test_start_without_old_options_changes_nothing(supervisor):
    options = {"camera": "camera.water_meter", "sensor": DEFAULT_SENSOR}
    supervisor.options = dict(options)
    assert start.migrate_addon_options(options) is options
    assert supervisor.saved == []
