"""Automatik: ablesen, prüfen und nach Home Assistant schreiben – gegen einen
nachgebauten Home Assistant (Kamera, Zustände, Dienste)."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import start
from app import automatik as automatik_modul
from app import sprache
from app.automatik import FEHLER, GESETZT, UEBERNOMMEN, UNVERAENDERT, VERWORFEN, Regeln, pruefen
from app.konfig import Konfig
from app.main import create_app
from app.sprache import ausgeben

MODELL = Path(__file__).parent.parent / "wasseruhr_cv" / "modell"
LERNBILD = {p.stem.split("_")[1]: p for p in (MODELL / "lernbilder").glob("*.png")}
REGELN = Regeln(max_m3_pro_stunde=3, toleranz_m3=0.002, alle_ziffern_gelernt=True, min_score=0.7, min_abstand=0.08)
T0 = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)


def _ergebnis(wert, sicher=True, fehlend=()):
    ziffern = [{"rolle": 1, "ziffer": 0, "score": 0.95 if sicher else 0.5, "zweitbeste": 8, "score2": 0.4}]
    return {"wert": wert, "sicher": sicher, "ziffern": ziffern, "fehlende_vorlagen": list(fehlend)}


# ---- Plausibilität ----------------------------------------------------------------


@pytest.mark.parametrize(
    "ergebnis, bisher, minuten, status, grund",
    [
        (_ergebnis(None), 506.0, 5, VERWORFEN, "keine Vorlagen"),
        (_ergebnis(506.1, sicher=False), 506.0, 5, VERWORFEN, "unsicher 506.100 – R1=0 (0.5"),
        (_ergebnis(506.1, fehlend=[2, 7]), 506.0, 5, VERWORFEN, "Ziffer 2, 7"),
        (_ergebnis(506.1), None, 0, UEBERNOMMEN, "erster"),
        (_ergebnis(506.0), 506.0, 5, UNVERAENDERT, ""),
        (_ergebnis(505.999), 506.0, 5, UNVERAENDERT, "Rückwärts"),
        (_ergebnis(505.9), 506.0, 5, VERWORFEN, "kleiner als der bisherige Stand 506.000"),
        (_ergebnis(506.3), 506.0, 5, VERWORFEN, "+0.300 m³ in 5 min ist unplausibel"),
        (_ergebnis(506.2), 506.0, 5, UEBERNOMMEN, "+0.200 m³"),  # 3 m³/h * 5 min = 0.25
        (_ergebnis(512.0), 506.0, 180, UEBERNOMMEN, "+6.000 m³"),  # 3 h ohne Ablesung
    ],
)
def test_pruefen(ergebnis, bisher, minuten, status, grund):
    s, g = pruefen(ergebnis, bisher, T0, T0 + timedelta(minutes=minuten), REGELN)
    assert s == status and grund in ausgeben(g, "de"), (s, g)


def test_pruefen_ohne_vollstaendige_vorlagen_erlaubt():
    regeln = Regeln(3, 0.002, alle_ziffern_gelernt=False, min_score=0.7, min_abstand=0.08)
    assert pruefen(_ergebnis(506.1, fehlend=[2]), None, None, T0, regeln)[0] == UEBERNOMMEN


# ---- Nachgebauter Home Assistant --------------------------------------------------


class FakeHA:
    def __init__(self):
        self.bild: bytes = b""
        self.kamera_status = 200
        # wie in einem HA, in dem der Helfer angelegt ist (frisch: 0)
        self.zustaende: dict[str, dict] = {
            "input_number.wasserzaehler": {"state": "0.0", "last_changed": "2026-01-01T00:00:00+00:00"},
        }
        self.dienste: list[tuple[str, dict]] = []
        self.anfragen: list[str] = []
        self.fehler_bei_states = False
        self.kameras = {"camera.wasseruhr": "Wasseruhr", "camera.garten": "Garten"}
        self.optionen = {"intervall_minuten": 5, "sensor": "sensor.wasseruhr_cv_zaehlerstand", "http": False}
        self.optionen_fehler = None
        self.neustarts = 0
        self.sprache = "de"  # Sprache in der Konfiguration von Home Assistant
        self.config_status = 200
        ha = self

        class H(BaseHTTPRequestHandler):
            def _antwort(self, code, body=b"", typ="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", typ)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                ha.anfragen.append(f"GET {self.path}")
                if self.headers.get("Authorization") != "Bearer geheim":
                    return self._antwort(401)
                if self.path in ("/core/api/camera_proxy/camera.wasseruhr", "/core/api/camera_proxy/camera.garten"):
                    return self._antwort(ha.kamera_status, ha.bild if ha.kamera_status == 200 else b"", "image/png")
                if self.path == "/core/api/states":
                    alle = [{"entity_id": e, **z} for e, z in ha.zustaende.items()]
                    alle += [{"entity_id": e, "state": "idle", "attributes": {"friendly_name": n}} for e, n in ha.kameras.items()]
                    return self._antwort(200, json.dumps(alle).encode())
                if self.path == "/core/api/config":
                    if ha.config_status != 200:
                        return self._antwort(ha.config_status)
                    return self._antwort(200, json.dumps({"language": ha.sprache, "version": "2026.11.0"}).encode())
                if self.path == "/addons/self/info":
                    return self._antwort(200, json.dumps({"result": "ok", "data": {"options": ha.optionen}}).encode())
                if self.path.startswith("/core/api/states/"):
                    z = ha.zustaende.get(self.path.rsplit("/", 1)[1])
                    return self._antwort(200, json.dumps(z).encode()) if z else self._antwort(404)
                self._antwort(404)

            def do_POST(self):
                ha.anfragen.append(f"POST {self.path}")
                if self.headers.get("Authorization") != "Bearer geheim":
                    return self._antwort(401)
                laenge = int(self.headers.get("Content-Length") or 0)
                daten = json.loads(self.rfile.read(laenge)) if laenge else {}
                if self.path == "/addons/self/options":
                    if ha.optionen_fehler:
                        return self._antwort(400, json.dumps({"result": "error", "message": ha.optionen_fehler}).encode())
                    ha.optionen = daten["options"]
                    return self._antwort(200, b'{"result": "ok", "data": {}}')
                if self.path == "/addons/self/restart":
                    ha.neustarts += 1
                    return self._antwort(200, b'{"result": "ok", "data": {}}')
                if self.path.startswith("/core/api/states/"):
                    if ha.fehler_bei_states:
                        return self._antwort(500)
                    ha.zustaende[self.path.rsplit("/", 1)[1]] = {**daten, "last_changed": _jetzt_iso()}
                    return self._antwort(200, b"{}")
                if self.path == "/core/api/services/input_number/set_value":
                    ha.dienste.append(("input_number.set_value", daten))
                    ha.zustaende[daten["entity_id"]] = {"state": str(daten["value"]), "last_changed": _jetzt_iso()}
                    return self._antwort(200, b"[]")
                self._antwort(404)

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.basis = f"http://127.0.0.1:{self.server.server_port}"
        self.url = f"{self.basis}/core/api"

    def schliessen(self):
        self.server.shutdown()
        self.server.server_close()


UHR = [T0]


def _jetzt_iso():
    return UHR[0].isoformat()


@pytest.fixture
def ha(monkeypatch):
    UHR[0] = T0
    monkeypatch.setattr(automatik_modul, "_jetzt", lambda: UHR[0])
    fake = FakeHA()
    yield fake
    fake.schliessen()


def _client(tmp_path, ha, **kwargs):
    konfig = dict(
        daten_verzeichnis=tmp_path, modell_verzeichnis=MODELL, kamera="camera.wasseruhr",
        ha_url=ha.url, ha_token="geheim", intervall_minuten=0,
        sensor="sensor.wasseruhr_cv_zaehlerstand", input_number="input_number.wasserzaehler",
        supervisor_url=ha.basis, ist_addon=True, sprache="de",
    )
    konfig.update(kwargs)
    return TestClient(create_app(Konfig(**konfig)))


def _jetzt(c):
    antwort = c.post("/admin/automatik/jetzt")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_ablauf_ablesen_pruefen_schreiben(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        # 1. erster sicherer Wert -> Sensor + Helfer
        ha.bild = LERNBILD["506.616"].read_bytes()
        a = _jetzt(c)
        assert a["letzter"]["status"] == UEBERNOMMEN and a["zaehlerstand"] == 506.616
        sensor = ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]
        assert sensor["state"] == "506.616"
        assert sensor["attributes"]["device_class"] == "water"
        assert sensor["attributes"]["state_class"] == "total_increasing"
        assert sensor["attributes"]["unit_of_measurement"] == "m³"
        # Attributnamen und Status sprachneutral, Texte in der Sprache des Dienstes (hier Deutsch)
        assert set(sensor["attributes"]) >= {"last_check", "status", "reason", "recognized", "source"}
        assert not {"letzte_pruefung", "grund", "erkannt", "quelle"} & set(sensor["attributes"])
        assert sensor["attributes"]["status"] == "accepted" and sensor["attributes"]["reason"] == "erster sicherer Wert"
        assert sensor["attributes"]["friendly_name"] == "Wasserzähler" and sensor["attributes"]["recognized"] == 506.616
        assert ha.dienste == [("input_number.set_value", {"entity_id": "input_number.wasserzaehler", "value": 506.616})]

        # 2. gleicher Wert 5 min später -> unverändert, Helfer nicht erneut gesetzt, Sensor aktualisiert
        UHR[0] += timedelta(minutes=5)
        assert _jetzt(c)["letzter"]["status"] == UNVERAENDERT
        assert len(ha.dienste) == 1
        assert ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["attributes"]["status"] == UNVERAENDERT

        # 3. Sprung um 3,8 m³ in 5 min -> unplausibel, Stand bleibt
        UHR[0] += timedelta(minutes=5)
        ha.bild = LERNBILD["510.406"].read_bytes()
        a = _jetzt(c)
        assert a["letzter"]["status"] == VERWORFEN and "unplausibel" in a["letzter"]["grund"]
        assert a["zaehlerstand"] == 506.616 and ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["state"] == "506.616"

        # 4. nach 2 Stunden ist der Anstieg plausibel
        UHR[0] += timedelta(hours=2)
        a = _jetzt(c)
        assert a["letzter"]["status"] == UEBERNOMMEN and a["zaehlerstand"] == 510.406
        assert ha.dienste[-1][1]["value"] == 510.406

        # Lernseite zeigt Stand und Automatik
        seite = c.get("/").text
        assert "Zählerstand 510.406 m³" in seite and "Automatik aus" in seite  # Intervall 0 im Test


def test_korrektur_ueber_helfer_und_von_hand(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        ha.bild = LERNBILD["510.406"].read_bytes()
        _jetzt(c)
        # Zählertausch: Helfer in HA von Hand auf einen kleineren Wert gesetzt
        UHR[0] += timedelta(minutes=5)
        ha.zustaende["input_number.wasserzaehler"] = {"state": "510.300", "last_changed": UHR[0].isoformat()}
        UHR[0] += timedelta(minutes=5)
        a = _jetzt(c)
        assert a["letzter"]["status"] == UEBERNOMMEN and a["zaehlerstand"] == 510.406
        # Korrektur in der Verwaltung
        a = c.post("/admin/automatik/zaehlerstand?wert=600,5").json()
        assert a["zaehlerstand"] == 600.5 and a["letzter"]["status"] == GESETZT
        assert ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["state"] == "600.500"
        assert ha.dienste[-1][1]["value"] == 600.5
        assert c.post("/admin/automatik/zaehlerstand?wert=abc").status_code == 400


def test_alter_helferwert_ist_keine_korrektur_und_wird_angeglichen(tmp_path, ha):
    """Ein alter Wert im Helfer (z. B. von einem früheren Werkzeug) setzt den Stand nicht zurück –
    der Helfer wird stattdessen auf den bestätigten Stand gebracht, auch wenn sich nichts ändert."""
    with _client(tmp_path, ha) as c:
        ha.bild = LERNBILD["510.406"].read_bytes()
        _jetzt(c)
        ha.zustaende["input_number.wasserzaehler"] = {"state": "100.000", "last_changed": (T0 - timedelta(days=1)).isoformat()}
        UHR[0] += timedelta(minutes=5)
        a = _jetzt(c)
        assert a["letzter"]["status"] == UNVERAENDERT and a["zaehlerstand"] == 510.406
        assert ha.zustaende["input_number.wasserzaehler"]["state"] == "510.406"
        anzahl = len(ha.dienste)
        UHR[0] += timedelta(minutes=5)
        _jetzt(c)  # Helfer stimmt jetzt -> nicht erneut schreiben
        assert len(ha.dienste) == anzahl


def test_helfer_nach_neustart_angeglichen(tmp_path, ha):
    """Wie bei der Umstellung: Stand liegt schon vor, Helfer steht noch auf einem älteren Wert."""
    ha.bild = LERNBILD["510.406"].read_bytes()
    with _client(tmp_path, ha, input_number=None) as c:  # erst nur Sensor
        _jetzt(c)
    ha.zustaende["input_number.wasserzaehler"] = {"state": "510.390", "last_changed": (T0 - timedelta(hours=3)).isoformat()}
    UHR[0] += timedelta(minutes=5)
    with _client(tmp_path, ha) as c:  # Helfer in der Konfiguration ergänzt, Neustart
        a = _jetzt(c)
        assert a["letzter"]["status"] == UNVERAENDERT and a["letzter"]["uebertragen"] == "ok"
    assert ha.zustaende["input_number.wasserzaehler"]["state"] == "510.406"


def test_stand_ueberlebt_neustart(tmp_path, ha):
    with _client(tmp_path, ha, input_number=None) as c:
        ha.bild = LERNBILD["506.616"].read_bytes()
        _jetzt(c)
    with _client(tmp_path, ha, input_number=None) as c:
        a = c.get("/admin/automatik").json()
        assert a["zaehlerstand"] == 506.616 and a["letzter"] is None
        assert c.get("/status").json()["zaehlerstand"] == 506.616
        UHR[0] += timedelta(minutes=5)
        ha.bild = LERNBILD["510.406"].read_bytes()
        assert _jetzt(c)["letzter"]["status"] == VERWORFEN  # Basis aus der Datei, nicht "erster Wert"


def test_fehler_werden_gemeldet_und_nichts_ueberschrieben(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        ha.kamera_status = 500
        a = _jetzt(c)
        assert a["letzter"]["status"] == FEHLER and "offline" in a["letzter"]["grund"]
        assert "sensor.wasseruhr_cv_zaehlerstand" not in ha.zustaende  # noch kein Stand
        ha.kamera_status = 200
        ha.bild = LERNBILD["506.616"].read_bytes()
        ha.fehler_bei_states = True
        a = _jetzt(c)
        assert a["letzter"]["status"] == UEBERNOMMEN
        assert "sensor.wasseruhr_cv_zaehlerstand: HTTP 500" in a["letzter"]["uebertragen"]


def test_fehlender_helfer_wird_gemeldet_statt_ok(tmp_path, ha):
    """HA meldet einen Dienstaufruf für eine fehlende Entität nicht als Fehler – das Add-on schon."""
    del ha.zustaende["input_number.wasserzaehler"]
    with _client(tmp_path, ha) as c:
        ha.bild = LERNBILD["506.616"].read_bytes()
        a = _jetzt(c)
        assert a["letzter"]["status"] == UEBERNOMMEN
        assert "input_number.wasserzaehler gibt es in Home Assistant nicht" in a["letzter"]["uebertragen"]
        assert a["input_number_fehlt"] is True
        assert ha.dienste == []  # nicht blind geschrieben
        assert ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["state"] == "506.616"  # Sensor trotzdem
        assert "gibt es in Home Assistant nicht" in c.get("/admin").text  # Hinweis in der Verwaltung
        # Helfer angelegt -> beim nächsten Setzen wird neu geprüft und geschrieben
        ha.zustaende["input_number.wasserzaehler"] = {"state": "0.0", "last_changed": T0.isoformat()}
        a = c.post("/admin/automatik/zaehlerstand?wert=506.620").json()
        assert a["letzter"]["uebertragen"] == "ok" and a["input_number_fehlt"] is False
        assert ha.dienste == [("input_number.set_value", {"entity_id": "input_number.wasserzaehler", "value": 506.62})]


def test_vorhandener_sensor_wird_ueberschrieben(tmp_path, ha):
    """Gewollt: Wer einen vorhandenen Sensor einträgt, führt ihn mit dem Zählerstand weiter."""
    ha.zustaende["sensor.wasserzaehler"] = {"state": "123.000", "attributes": {"friendly_name": "Alt"}}
    with _client(tmp_path, ha, sensor="sensor.wasserzaehler") as c:
        ha.bild = LERNBILD["506.616"].read_bytes()
        _jetzt(c)
    assert ha.zustaende["sensor.wasserzaehler"]["state"] == "506.616"


def test_ohne_kamera_keine_automatik(tmp_path, ha):
    with _client(tmp_path, ha, kamera=None) as c:
        a = c.get("/admin/automatik").json()
        assert a["aktiv"] is False
        assert c.post("/admin/automatik/jetzt").status_code == 400
        assert "Automatik aus" in c.get("/").text
    assert ha.anfragen == []


def test_ohne_ziele_wird_nichts_geschrieben(tmp_path, ha):
    with _client(tmp_path, ha, sensor=None, input_number=None) as c:
        ha.bild = LERNBILD["506.616"].read_bytes()
        assert _jetzt(c)["letzter"]["uebertragen"] == "ok"
    assert not [a for a in ha.anfragen if a.startswith("POST")]


def test_zeitgesteuert_im_hintergrund(tmp_path, ha, monkeypatch):
    monkeypatch.setattr(automatik_modul, "ERSTE_ABLESUNG_NACH_S", 0)
    ha.bild = LERNBILD["506.616"].read_bytes()
    start_zeit = time.monotonic()
    with _client(tmp_path, ha, intervall_minuten=5) as c:
        assert c.get("/admin/automatik").json()["aktiv"] is True
        for _ in range(100):
            if "sensor.wasseruhr_cv_zaehlerstand" in ha.zustaende:
                break
            time.sleep(0.05)
        assert ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["state"] == "506.616"
        assert "Automatik alle 5 min" in c.get("/").text
    assert time.monotonic() - start_zeit < 10  # Herunterfahren wartet nicht auf das Intervall


def test_geleerte_entitaet_im_addon_heisst_keine(monkeypatch):
    for v in ("SENSOR", "INPUT_NUMBER"):
        monkeypatch.delenv(v, raising=False)
    start.umgebung_setzen({"kamera": "camera.x"}, addon=True)  # sensor/input_number im Formular geleert
    k = Konfig.aus_umgebung()
    assert k.sensor is None and k.input_number is None
    monkeypatch.delenv("SENSOR"); monkeypatch.delenv("INPUT_NUMBER")
    assert Konfig.aus_umgebung().sensor == "sensor.wasseruhr_cv_zaehlerstand"  # Docker: Standard


def test_modell_zuruecksetzen(tmp_path, ha):
    with _client(tmp_path, ha) as c:
        assert c.get("/status").json()["lernbilder"] >= 10
        d = c.post("/admin/zuruecksetzen").json()
        assert d["lernbilder"] == 0 and d["fehlende_vorlagen"] == list(range(10))
        assert c.post("/admin/zuruecksetzen", headers={"Origin": "http://boese.example"}).status_code == 403
    with _client(tmp_path, ha) as c:  # mitgeliefertes Modell kommt nicht zurück
        assert c.get("/status").json()["lernbilder"] == 0


# ---- Kamera in der Verwaltung auswählen ---------------------------------------------


def test_kameraliste_und_vorschau(tmp_path, ha):
    ha.bild = LERNBILD["506.616"].read_bytes()
    with _client(tmp_path, ha, kamera=None) as c:
        d = c.get("/admin/kameras").json()
        assert [k["entity_id"] for k in d["kameras"]] == ["camera.garten", "camera.wasseruhr"]  # nach Name
        assert d["kameras"][1]["name"] == "Wasseruhr" and d["aktuell"] is None and d["speichern_moeglich"] is True
        bild = c.get("/admin/kameras/camera.wasseruhr/bild")
        assert bild.status_code == 200 and bild.content == ha.bild
        assert c.get("/admin/kameras/sensor.geheim/bild").status_code == 400  # nur Kameras
        assert 'id="kamera-wahl"' in c.get("/admin").text
        assert 'href="admin">Verwaltung</a> die Kamera auswählen' in c.get("/").text


def test_kamera_waehlen_speichert_option_und_startet_neu(tmp_path, ha):
    with _client(tmp_path, ha, kamera=None) as c:
        antwort = c.post("/admin/kamera?entity_id=camera.wasseruhr")
        assert antwort.status_code == 200, antwort.text
        assert antwort.json() == {"kamera": "camera.wasseruhr", "neustart": True}
        # nur die Kamera geändert, alle anderen Optionen unverändert
        assert ha.optionen == {"intervall_minuten": 5, "sensor": "sensor.wasseruhr_cv_zaehlerstand",
                               "http": False, "kamera": "camera.wasseruhr"}
        for _ in range(60):  # Neustart kommt verzögert, nach der Antwort an den Browser
            if ha.neustarts:
                break
            time.sleep(0.05)
        assert ha.neustarts == 1


def test_kamera_waehlen_fehlerfaelle(tmp_path, ha):
    with _client(tmp_path, ha, kamera=None) as c:
        antwort = c.post("/admin/kamera?entity_id=camera.gibtsnicht")
        assert antwort.status_code == 400 and "gibt es in Home Assistant nicht" in antwort.json()["detail"]
        ha.optionen_fehler = "Missing option 'irgendwas'"
        antwort = c.post("/admin/kamera?entity_id=camera.wasseruhr")
        assert antwort.status_code == 502
        assert "bei „Kamera“ eintragen: camera.wasseruhr" in antwort.json()["detail"]  # Plan B zum Abtippen
        assert c.post("/admin/kamera?entity_id=camera.wasseruhr", headers={"Origin": "http://boese.example"}).status_code == 403
    assert ha.neustarts == 0
    with _client(tmp_path, ha, kamera=None, ist_addon=False) as c:  # Docker: kein Supervisor
        antwort = c.post("/admin/kamera?entity_id=camera.wasseruhr")
        assert antwort.status_code == 400 and "KAMERA=camera.wasseruhr" in antwort.json()["detail"]
        assert c.get("/admin/kameras").json()["speichern_moeglich"] is False


# ---- Sprache von Protokoll und Sensor aus Home Assistant ----------------------------


def test_sprache_von_home_assistant(tmp_path, ha):
    """SPRACHE=auto: Sensor und Protokoll in der Sprache von HA, die Verwaltung in der des Browsers."""
    ha.sprache = "en"
    ha.bild = LERNBILD["506.616"].read_bytes()
    with _client(tmp_path, ha, sprache="auto") as c:
        assert sprache.dienst() == "en" and sprache.quelle() == "home_assistant"
        _jetzt(c)
        attribute = ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["attributes"]
        assert attribute["friendly_name"] == "Water meter" and attribute["reason"] == "first certain value"
        # dieselbe Prüfung in der Verwaltung: je nach Browser
        de = c.get("/admin/automatik", headers={"Accept-Language": "de"}).json()["letzter"]
        en = c.get("/admin/automatik", headers={"Accept-Language": "en"}).json()["letzter"]
        assert de["grund"] == "erster sicherer Wert" and en["grund"] == "first certain value"
        assert de["status"] == en["status"] == UEBERNOMMEN


def test_sprache_deutsch_und_unbekannt(tmp_path, ha):
    with _client(tmp_path, ha, sprache="auto"):
        assert sprache.dienst() == "de"
    ha.sprache = "fr"  # nicht unterstützt -> Englisch
    with _client(tmp_path, ha, sprache="auto"):
        assert sprache.dienst() == "en"
    ha.config_status = 404  # HA antwortet, verrät die Sprache aber nicht -> Englisch, kein neuer Versuch
    with _client(tmp_path, ha, sprache="auto"):
        assert sprache.dienst() == "en" and not sprache.offen()


def test_sprache_wird_nachgeholt(tmp_path, ha):
    """Beim Start war HA noch nicht erreichbar: die nächste Ablesung holt die Sprache nach."""
    ha.config_status = 502
    ha.bild = LERNBILD["506.616"].read_bytes()
    with _client(tmp_path, ha, sprache="auto") as c:
        assert sprache.dienst() == "en" and sprache.offen()
        ha.config_status = 200
        _jetzt(c)
        assert sprache.dienst() == "de" and not sprache.offen()
        assert ha.zustaende["sensor.wasseruhr_cv_zaehlerstand"]["attributes"]["friendly_name"] == "Wasserzähler"


def test_feste_sprache_fragt_home_assistant_nicht(tmp_path, ha):
    with _client(tmp_path, ha, sprache="en", kamera=None):
        assert sprache.dienst() == "en"
    assert "GET /core/api/config" not in ha.anfragen
