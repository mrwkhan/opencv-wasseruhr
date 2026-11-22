"""Automatic reading: read, check and write to Home Assistant – against a
simulated Home Assistant (camera, states, services, Supervisor)."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auto_reading, i18n
from app.auto_reading import ACCEPTED, ERROR, REJECTED, SET, UNCHANGED, Rules, check
from app.config import DEFAULT_SENSOR, LEGACY_DEFAULT_SENSOR, Config
from app.i18n import render
from app.main import create_app

MODEL = Path(__file__).parent.parent / "wasseruhr_cv" / "model"
IMAGE = {p.stem.split("_")[1]: p for p in (MODEL / "images").glob("*.png")}
RULES = Rules(max_m3_per_hour=3, tolerance_m3=0.002, require_all_digits=True, min_score=0.7, min_margin=0.08)
T0 = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
HELPER = "input_number.water_meter"


def _result(value, certain=True, missing=()):
    digits = [{"wheel": 1, "digit": 0, "score": 0.95 if certain else 0.5, "second": 8, "second_score": 0.4}]
    return {"value": value, "certain": certain, "digits": digits, "missing_templates": list(missing)}


# ---- Plausibility -------------------------------------------------------------------


@pytest.mark.parametrize(
    "result, previous, minutes, status, reason",
    [
        (_result(None), 506.0, 5, REJECTED, "no templates"),
        (_result(506.1, certain=False), 506.0, 5, REJECTED, "uncertain 506.100 – R1=0 (0.5 vs 8: 0.4)"),
        (_result(506.1, missing=[2, 7]), 506.0, 5, REJECTED, "digit 2, 7"),
        (_result(506.1), None, 0, ACCEPTED, "first"),
        (_result(506.0), 506.0, 5, UNCHANGED, ""),
        (_result(505.999), 506.0, 5, UNCHANGED, "backward"),
        (_result(505.9), 506.0, 5, REJECTED, "lower than the previous reading 506.000"),
        (_result(506.3), 506.0, 5, REJECTED, "+0.300 m³ in 5 min is implausible"),
        (_result(506.2), 506.0, 5, ACCEPTED, "+0.200 m³"),  # 3 m³/h * 5 min = 0.25
        (_result(512.0), 506.0, 180, ACCEPTED, "+6.000 m³"),  # 3 h without a reading
    ],
)
def test_check(result, previous, minutes, status, reason):
    s, r = check(result, previous, T0, T0 + timedelta(minutes=minutes), RULES)
    assert s == status and reason in render(r, "en"), (s, r)


def test_check_reasons_in_german():
    _, r = check(_result(506.3), 506.0, T0, T0 + timedelta(minutes=5), RULES)
    assert render(r, "de") == "506.300: +0.300 m³ in 5 min ist unplausibel"


def test_check_without_complete_templates_allowed():
    rules = Rules(3, 0.002, require_all_digits=False, min_score=0.7, min_margin=0.08)
    assert check(_result(506.1, missing=[2]), None, None, T0, rules)[0] == ACCEPTED


# ---- Simulated Home Assistant ------------------------------------------------------


class FakeHA:
    def __init__(self):
        self.image: bytes = b""
        self.camera_status = 200
        # like in an HA in which the helper exists (fresh: 0)
        self.states: dict[str, dict] = {HELPER: {"state": "0.0", "last_changed": "2026-01-01T00:00:00+00:00"}}
        self.services: list[tuple[str, dict]] = []
        self.requests: list[str] = []
        self.fail_states = False
        self.cameras = {"camera.water_meter": "Water meter", "camera.garden": "Garden"}
        self.options = {"interval_minutes": 5, "sensor": DEFAULT_SENSOR, "http": False}
        self.options_error = None
        self.restarts = 0
        self.language = "en"  # language in the configuration of Home Assistant
        self.config_status = 200
        ha = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, code, body=b"", kind="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", kind)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                ha.requests.append(f"GET {self.path}")
                if self.headers.get("Authorization") != "Bearer secret":
                    return self._answer(401)
                if self.path in (f"/core/api/camera_proxy/{c}" for c in ha.cameras):
                    return self._answer(ha.camera_status, ha.image if ha.camera_status == 200 else b"", "image/png")
                if self.path == "/core/api/states":
                    states = [{"entity_id": e, **s} for e, s in ha.states.items()]
                    states += [{"entity_id": e, "state": "idle", "attributes": {"friendly_name": n}} for e, n in ha.cameras.items()]
                    return self._answer(200, json.dumps(states).encode())
                if self.path == "/core/api/config":
                    if ha.config_status != 200:
                        return self._answer(ha.config_status)
                    return self._answer(200, json.dumps({"language": ha.language, "version": "2026.11.0"}).encode())
                if self.path == "/addons/self/info":
                    return self._answer(200, json.dumps({"result": "ok", "data": {"options": ha.options}}).encode())
                if self.path.startswith("/core/api/states/"):
                    s = ha.states.get(self.path.rsplit("/", 1)[1])
                    return self._answer(200, json.dumps(s).encode()) if s else self._answer(404)
                self._answer(404)

            def do_POST(self):
                ha.requests.append(f"POST {self.path}")
                if self.headers.get("Authorization") != "Bearer secret":
                    return self._answer(401)
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length)) if length else {}
                if self.path == "/addons/self/options":
                    if ha.options_error:
                        return self._answer(400, json.dumps({"result": "error", "message": ha.options_error}).encode())
                    ha.options = data["options"]
                    return self._answer(200, b'{"result": "ok", "data": {}}')
                if self.path == "/addons/self/restart":
                    ha.restarts += 1
                    return self._answer(200, b'{"result": "ok", "data": {}}')
                if self.path.startswith("/core/api/states/"):
                    if ha.fail_states:
                        return self._answer(500)
                    ha.states[self.path.rsplit("/", 1)[1]] = {**data, "last_changed": _now_iso()}
                    return self._answer(200, b"{}")
                if self.path == "/core/api/services/input_number/set_value":
                    ha.services.append(("input_number.set_value", data))
                    ha.states[data["entity_id"]] = {"state": str(data["value"]), "last_changed": _now_iso()}
                    return self._answer(200, b"[]")
                self._answer(404)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.url = f"{self.base}/core/api"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


CLOCK = [T0]


def _now_iso():
    return CLOCK[0].isoformat()


@pytest.fixture
def ha(monkeypatch):
    CLOCK[0] = T0
    monkeypatch.setattr(auto_reading, "_now", lambda: CLOCK[0])
    fake = FakeHA()
    yield fake
    fake.close()


def _client(tmp_path, ha, **kwargs):
    config = dict(
        data_dir=tmp_path, model_dir=MODEL, camera="camera.water_meter",
        ha_url=ha.url, ha_token="secret", interval_minutes=0,
        sensor=DEFAULT_SENSOR, input_number=HELPER,
        supervisor_url=ha.base, is_addon=True, language="en",
    )
    config.update(kwargs)
    return TestClient(create_app(Config(**config)))


def _run(c):
    response = c.post("/admin/auto-reading/run")
    assert response.status_code == 200, response.text
    return response.json()


def test_read_check_write(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        # 1. first certain value -> sensor + helper
        ha.image = IMAGE["506.616"].read_bytes()
        a = _run(c)
        assert a["last"]["status"] == ACCEPTED and a["meter_reading"] == 506.616
        sensor = ha.states[DEFAULT_SENSOR]
        assert sensor["state"] == "506.616"
        attributes = sensor["attributes"]
        assert attributes["device_class"] == "water" and attributes["state_class"] == "total_increasing"
        assert attributes["unit_of_measurement"] == "m³"
        # attribute names and status language-neutral, texts in the service language (here English)
        assert set(attributes) >= {"last_check", "status", "reason", "recognized", "source"}
        assert attributes["status"] == "accepted" and attributes["reason"] == "first certain value"
        assert attributes["friendly_name"] == "Water meter" and attributes["recognized"] == 506.616
        assert ha.services == [("input_number.set_value", {"entity_id": HELPER, "value": 506.616})]

        # 2. same value 5 min later -> unchanged, helper not set again, sensor updated
        CLOCK[0] += timedelta(minutes=5)
        assert _run(c)["last"]["status"] == UNCHANGED
        assert len(ha.services) == 1
        assert ha.states[DEFAULT_SENSOR]["attributes"]["status"] == UNCHANGED

        # 3. jump of 3.8 m³ in 5 min -> implausible, meter reading stays
        CLOCK[0] += timedelta(minutes=5)
        ha.image = IMAGE["510.406"].read_bytes()
        a = _run(c)
        assert a["last"]["status"] == REJECTED and "implausible" in a["last"]["reason"]
        assert a["meter_reading"] == 506.616 and ha.states[DEFAULT_SENSOR]["state"] == "506.616"

        # 4. after 2 hours the increase is plausible
        CLOCK[0] += timedelta(hours=2)
        a = _run(c)
        assert a["last"]["status"] == ACCEPTED and a["meter_reading"] == 510.406
        assert ha.services[-1][1]["value"] == 510.406

        # the training page shows the meter reading and the auto-reading
        page = c.get("/").text
        assert "Meter reading 510.406 m³" in page and "Auto-reading off" in page  # interval 0 in the test


def test_correction_via_helper_and_by_hand(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        ha.image = IMAGE["510.406"].read_bytes()
        _run(c)
        # meter replaced: helper set to a lower value by hand in HA
        CLOCK[0] += timedelta(minutes=5)
        ha.states[HELPER] = {"state": "510.300", "last_changed": CLOCK[0].isoformat()}
        CLOCK[0] += timedelta(minutes=5)
        a = _run(c)
        assert a["last"]["status"] == ACCEPTED and a["meter_reading"] == 510.406
        # correction on the admin page
        a = c.post("/admin/auto-reading/meter-reading?value=600,5").json()
        assert a["meter_reading"] == 600.5 and a["last"]["status"] == SET
        assert ha.states[DEFAULT_SENSOR]["state"] == "600.500"
        assert ha.services[-1][1]["value"] == 600.5
        assert c.post("/admin/auto-reading/meter-reading?value=abc").status_code == 400


def test_old_helper_value_is_no_correction_and_gets_aligned(tmp_path, ha):
    """An old value in the helper (e.g. of an earlier tool) does not reset the meter reading –
    the helper is brought to the confirmed reading instead, even if nothing changes."""
    with _client(tmp_path, ha) as c:
        ha.image = IMAGE["510.406"].read_bytes()
        _run(c)
        ha.states[HELPER] = {"state": "100.000", "last_changed": (T0 - timedelta(days=1)).isoformat()}
        CLOCK[0] += timedelta(minutes=5)
        a = _run(c)
        assert a["last"]["status"] == UNCHANGED and a["meter_reading"] == 510.406
        assert ha.states[HELPER]["state"] == "510.406"
        count = len(ha.services)
        CLOCK[0] += timedelta(minutes=5)
        _run(c)  # the helper is right now -> do not write again
        assert len(ha.services) == count


def test_helper_aligned_after_restart(tmp_path, ha):
    """As when switching over: a meter reading exists, the helper still holds an older value."""
    ha.image = IMAGE["510.406"].read_bytes()
    with _client(tmp_path, ha, input_number=None) as c:  # first only the sensor
        _run(c)
    ha.states[HELPER] = {"state": "510.390", "last_changed": (T0 - timedelta(hours=3)).isoformat()}
    CLOCK[0] += timedelta(minutes=5)
    with _client(tmp_path, ha) as c:  # helper added to the configuration, restart
        a = _run(c)
        assert a["last"]["status"] == UNCHANGED and a["last"]["sent"] == "ok"
    assert ha.states[HELPER]["state"] == "510.406"


def test_meter_reading_survives_a_restart(tmp_path, ha):
    with _client(tmp_path, ha, input_number=None) as c:
        ha.image = IMAGE["506.616"].read_bytes()
        _run(c)
    with _client(tmp_path, ha, input_number=None) as c:
        a = c.get("/admin/auto-reading").json()
        assert a["meter_reading"] == 506.616 and a["last"] is None
        assert c.get("/status").json()["meter_reading"] == 506.616
        CLOCK[0] += timedelta(minutes=5)
        ha.image = IMAGE["510.406"].read_bytes()
        assert _run(c)["last"]["status"] == REJECTED  # baseline from the file, not "first value"


def test_errors_are_reported_and_nothing_overwritten(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        ha.camera_status = 500
        a = _run(c)
        assert a["last"]["status"] == ERROR and "offline" in a["last"]["reason"]
        assert DEFAULT_SENSOR not in ha.states  # no meter reading yet
        ha.camera_status = 200
        ha.image = IMAGE["506.616"].read_bytes()
        ha.fail_states = True
        a = _run(c)
        assert a["last"]["status"] == ACCEPTED
        assert f"{DEFAULT_SENSOR}: HTTP 500" in a["last"]["sent"]


def test_missing_helper_is_reported_instead_of_ok(tmp_path, ha):
    """HA does not report a service call for a missing entity as an error – the add-on does."""
    del ha.states[HELPER]
    with _client(tmp_path, ha) as c:
        ha.image = IMAGE["506.616"].read_bytes()
        a = _run(c)
        assert a["last"]["status"] == ACCEPTED
        assert f"{HELPER} does not exist in Home Assistant" in a["last"]["sent"]
        assert a["input_number_missing"] is True
        assert ha.services == []  # not written blindly
        assert ha.states[DEFAULT_SENSOR]["state"] == "506.616"  # sensor anyway
        assert "does not exist in Home Assistant" in c.get("/admin").text  # hint on the admin page
        # helper created -> checked again and written on the next set
        ha.states[HELPER] = {"state": "0.0", "last_changed": T0.isoformat()}
        a = c.post("/admin/auto-reading/meter-reading?value=506.620").json()
        assert a["last"]["sent"] == "ok" and a["input_number_missing"] is False
        assert ha.services == [("input_number.set_value", {"entity_id": HELPER, "value": 506.62})]


def test_existing_sensor_is_overwritten(tmp_path, ha):
    """Intended: whoever enters an existing sensor continues it with the meter reading."""
    ha.states["sensor.water_meter"] = {"state": "123.000", "attributes": {"friendly_name": "Old"}}
    with _client(tmp_path, ha, sensor="sensor.water_meter") as c:
        ha.image = IMAGE["506.616"].read_bytes()
        _run(c)
    assert ha.states["sensor.water_meter"]["state"] == "506.616"


def test_without_camera_no_auto_reading(tmp_path, ha):
    with _client(tmp_path, ha, camera=None) as c:
        a = c.get("/admin/auto-reading").json()
        assert a["active"] is False
        assert c.post("/admin/auto-reading/run").status_code == 400
        assert "Auto-reading off" in c.get("/").text
    assert ha.requests == []


def test_without_targets_nothing_is_written(tmp_path, ha):
    with _client(tmp_path, ha, sensor=None, input_number=None) as c:
        ha.image = IMAGE["506.616"].read_bytes()
        assert _run(c)["last"]["sent"] == "ok"
    assert not [r for r in ha.requests if r.startswith("POST")]


def test_runs_in_the_background(tmp_path, ha, monkeypatch):
    monkeypatch.setattr(auto_reading, "FIRST_READING_AFTER_S", 0)
    ha.image = IMAGE["506.616"].read_bytes()
    started = time.monotonic()
    with _client(tmp_path, ha, interval_minutes=5) as c:
        assert c.get("/admin/auto-reading").json()["active"] is True
        for _ in range(100):
            if DEFAULT_SENSOR in ha.states:
                break
            time.sleep(0.05)
        assert ha.states[DEFAULT_SENSOR]["state"] == "506.616"
        assert "Auto-reading every 5 min" in c.get("/").text
    assert time.monotonic() - started < 10  # shutting down does not wait for the interval


def test_reset_model(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        assert c.get("/status").json()["training_images"] >= 10
        d = c.post("/admin/reset").json()
        assert d["training_images"] == 0 and d["missing_templates"] == list(range(10))
        assert c.post("/admin/reset", headers={"Origin": "http://evil.example"}).status_code == 403
    with _client(tmp_path, ha) as c:  # the bundled model does not come back
        assert c.get("/status").json()["training_images"] == 0


# ---- Choosing the camera on the admin page -----------------------------------------


def test_camera_list_and_preview(tmp_path, ha):
    ha.image = IMAGE["506.616"].read_bytes()
    with _client(tmp_path, ha, camera=None) as c:
        d = c.get("/admin/cameras").json()
        assert [k["entity_id"] for k in d["cameras"]] == ["camera.garden", "camera.water_meter"]  # by name
        assert d["cameras"][1]["name"] == "Water meter" and d["current"] is None and d["can_save"] is True
        image = c.get("/admin/cameras/camera.water_meter/image")
        assert image.status_code == 200 and image.content == ha.image
        assert c.get("/admin/cameras/sensor.secret/image").status_code == 400  # cameras only
        assert 'id="camera-choice"' in c.get("/admin").text
        assert 'href="admin">Admin</a> page' in c.get("/").text


def test_choosing_a_camera_saves_the_option_and_restarts(tmp_path, ha):
    ha.options["kamera"] = "camera.old"  # left over from version 1.x – must not be sent back
    with _client(tmp_path, ha, camera=None) as c:
        response = c.post("/admin/camera?entity_id=camera.water_meter")
        assert response.status_code == 200, response.text
        assert response.json() == {"camera": "camera.water_meter", "restart": True}
        # only the camera changed, all other options unchanged
        assert ha.options == {"interval_minutes": 5, "sensor": DEFAULT_SENSOR, "http": False,
                              "camera": "camera.water_meter"}
        for _ in range(60):  # the restart comes delayed, after the answer to the browser
            if ha.restarts:
                break
            time.sleep(0.05)
        assert ha.restarts == 1


def test_choosing_a_camera_errors(tmp_path, ha):
    with _client(tmp_path, ha, camera=None) as c:
        response = c.post("/admin/camera?entity_id=camera.missing")
        assert response.status_code == 400 and "does not exist in Home Assistant" in response.json()["detail"]
        ha.options_error = "Missing option 'something'"
        response = c.post("/admin/camera?entity_id=camera.water_meter")
        assert response.status_code == 502
        assert "at “Camera”: camera.water_meter" in response.json()["detail"]  # plan B to type in
        foreign = c.post("/admin/camera?entity_id=camera.water_meter", headers={"Origin": "http://evil.example"})
        assert foreign.status_code == 403
    assert ha.restarts == 0
    with _client(tmp_path, ha, camera=None, is_addon=False) as c:  # Docker: no Supervisor
        response = c.post("/admin/camera?entity_id=camera.water_meter")
        assert response.status_code == 400 and "CAMERA=camera.water_meter" in response.json()["detail"]
        assert c.get("/admin/cameras").json()["can_save"] is False


# ---- Language of log and sensor from Home Assistant ----------------------------------


def test_language_from_home_assistant(tmp_path, ha):
    """LANGUAGE=auto: sensor and log in the language of HA, the admin page in that of the browser."""
    ha.language = "de"
    ha.image = IMAGE["506.616"].read_bytes()
    with _client(tmp_path, ha, language="auto") as c:
        assert i18n.service_language() == "de" and i18n.source() == "home_assistant"
        _run(c)
        attributes = ha.states[DEFAULT_SENSOR]["attributes"]
        assert attributes["friendly_name"] == "Wasserzähler" and attributes["reason"] == "erster sicherer Wert"
        assert attributes["status"] == ACCEPTED  # code stays the same in every language
        # the same check on the admin page: depending on the browser
        de = c.get("/admin/auto-reading", headers={"Accept-Language": "de"}).json()["last"]
        en = c.get("/admin/auto-reading", headers={"Accept-Language": "en"}).json()["last"]
        assert de["reason"] == "erster sicherer Wert" and en["reason"] == "first certain value"


def test_language_english_and_unsupported(tmp_path, ha):
    with _client(tmp_path, ha, language="auto"):
        assert i18n.service_language() == "en"
    ha.language = "fr"  # not supported -> English
    with _client(tmp_path, ha, language="auto"):
        assert i18n.service_language() == "en"
    ha.config_status = 404  # HA answers but does not tell its language -> English, no new attempt
    with _client(tmp_path, ha, language="auto"):
        assert i18n.service_language() == "en" and not i18n.pending()


def test_language_is_caught_up_later(tmp_path, ha):
    """At start-up HA was not reachable yet: the next reading catches up on the language."""
    ha.config_status = 502
    ha.language = "de"
    ha.image = IMAGE["506.616"].read_bytes()
    with _client(tmp_path, ha, language="auto") as c:
        assert i18n.service_language() == "en" and i18n.pending()
        ha.config_status = 200
        _run(c)
        assert i18n.service_language() == "de" and not i18n.pending()
        assert ha.states[DEFAULT_SENSOR]["attributes"]["friendly_name"] == "Wasserzähler"


def test_fixed_language_does_not_ask_home_assistant(tmp_path, ha):
    with _client(tmp_path, ha, language="de", camera=None):
        assert i18n.service_language() == "de"
    assert "GET /core/api/config" not in ha.requests


# ---- Update from version 1.x ----------------------------------------------------------


def test_installation_of_version_1_keeps_its_sensor_and_meter_reading(tmp_path, ha):
    """The old default sensor carries the Energy dashboard history – it is continued."""
    (tmp_path / "zaehlerstand.json").write_text(json.dumps({"wert": 506.6, "zeit": T0.isoformat()}))
    ha.image = IMAGE["506.616"].read_bytes()
    with _client(tmp_path, ha, input_number=None) as c:
        assert c.get("/admin/auto-reading").json()["sensor"] == LEGACY_DEFAULT_SENSOR
        CLOCK[0] += timedelta(minutes=5)
        a = _run(c)
        assert a["last"]["status"] == ACCEPTED and "+0.016" in a["last"]["reason"]  # baseline taken over
    assert ha.states[LEGACY_DEFAULT_SENSOR]["state"] == "506.616" and DEFAULT_SENSOR not in ha.states
    with _client(tmp_path, ha, input_number=None, sensor="sensor.water_meter") as c:  # chosen deliberately
        assert c.get("/admin/auto-reading").json()["sensor"] == "sensor.water_meter"
