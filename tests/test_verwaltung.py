"""Verwaltung (/admin), Modell-Export/-Import, Erstausstattung des Add-ons und
"Kamera jetzt ablesen"."""

import base64
import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import kamera, modell
from app.konfig import Konfig, KonfigFehler
from app.main import create_app

BEISPIEL = Path(__file__).parent / "beispiel.jpg"
BEISPIEL_WERT = "506.388"
JPEG = {"Content-Type": "image/jpeg"}
INGRESS = ("172.30.32.2", 40000)


@pytest.fixture
def jpeg() -> bytes:
    return BEISPIEL.read_bytes()


def _client(tmp_path: Path, client=("testclient", 50000), **kwargs) -> TestClient:
    return TestClient(create_app(Konfig(daten_verzeichnis=tmp_path, **kwargs)), client=client)


@pytest.fixture
def client(tmp_path):
    with _client(tmp_path) as c:
        yield c


def _lernen(c, jpeg, wert=BEISPIEL_WERT):
    antwort = c.post(f"/lernen?wert={wert}", content=jpeg, headers=JPEG)
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _zip(dateien: dict[str, bytes]) -> bytes:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        for name, daten in dateien.items():
            z.writestr(name, daten)
    return puffer.getvalue()


# ---- Seite, Übersicht -------------------------------------------------------


def test_admin_seite_und_info(client, jpeg):
    seite = client.get("/admin")
    assert seite.status_code == 200 and "text/html" in seite.headers["content-type"]
    assert 'href="admin/export.zip"' in seite.text and "fetch(" in seite.text
    assert 'id="leer-hinweis" hidden' in seite.text and "[hidden] { display:none !important; }" in seite.text
    _lernen(client, jpeg)
    info = client.get("/admin/info").json()
    assert info["lernbilder"] == 1 and info["lerneffekt"] is True
    assert info["fehlende_vorlagen"] == [1, 2, 4, 7, 9]
    assert info["einstellungen"]["MIN_SCORE"] == 0.70 and len(info["einstellungen"]["ROIS"]) == 8
    assert info["kamera_bereit"] is False and info["addon"] is False and info["erstausstattung"] is None


def test_ablesungen_neueste_zuerst(client, jpeg):
    assert client.get("/admin/ablesungen").json() == []
    client.post("/ablesen", content=jpeg, headers=JPEG)
    _lernen(client, jpeg)
    client.post("/ablesen", content=jpeg, headers=JPEG)
    liste = client.get("/admin/ablesungen").json()
    assert [a["nr"] for a in liste] == [2, 1]
    assert liste[0]["sicher"] is True and liste[0]["wert"] == 506.388 and liste[1]["wert"] is None


def test_lernseite_verlinkt_verwaltung(client):
    assert 'href="admin"' in client.get("/").text


# ---- Lernbilder -------------------------------------------------------------


def test_lernbilder_liste_original_und_ausschnitt(client, jpeg):
    _lernen(client, jpeg)
    _lernen(client, jpeg, "506.389")
    liste = client.get("/admin/lernbilder").json()
    assert [lb["wert"] for lb in liste] == [506.389, 506.388]  # neueste zuerst
    name = liste[1]["name"]
    assert name.endswith("_506.388.jpg") and liste[1]["zeit"].startswith("20")

    original = client.get(f"/admin/lernbilder/{name}")
    assert original.status_code == 200 and original.content == jpeg
    ausschnitt = client.get(f"/admin/lernbilder/{name}?ausschnitt=1")
    bild = cv2.imdecode(np.frombuffer(ausschnitt.content, np.uint8), cv2.IMREAD_COLOR)
    # Zählwerk: ROIs x 130..467, y 144..196, plus 12 px Rand
    assert bild.shape[:2] == (196 - 144 + 24, 467 - 130 + 24)


@pytest.mark.parametrize("name", ["gibtsnicht.jpg", "..%2F..%2Fetc%2Fpasswd", "%2E%2E"])
def test_lernbild_unbekannt(client, jpeg, name):
    _lernen(client, jpeg)
    assert client.get(f"/admin/lernbilder/{name}").status_code == 404
    assert client.post(f"/admin/lernbilder/{name}/loeschen").status_code == 404


def test_lernbild_loeschen_baut_vorlagen_neu(client, jpeg, tmp_path):
    _lernen(client, jpeg)
    name = client.get("/admin/lernbilder").json()[0]["name"]
    antwort = client.post(f"/admin/lernbilder/{name}/loeschen").json()
    assert antwort["vorlagen_neu_aufgebaut"] is True and antwort["lernbilder"] == 0
    assert antwort["fehlende_vorlagen"] == list(range(10))
    assert not list(tmp_path.glob("vorlagen/*/*.png"))
    assert client.post("/ablesen", content=jpeg, headers=JPEG).json()["wert"] is None


def test_lernbild_korrigieren(client, jpeg, tmp_path):
    _lernen(client, jpeg, "506.399")  # falsch gelernt: zwei 9en statt 8en
    assert client.get("/status").json()["vorlagen_pro_ziffer"]["9"] >= 1
    name = client.get("/admin/lernbilder").json()[0]["name"]
    zeitstempel = name.split("_")[0]

    antwort = client.post(f"/admin/lernbilder/{name}/wert?wert=506,388")
    assert antwort.status_code == 200, antwort.text
    d = antwort.json()
    assert d["name"] == f"{zeitstempel}_506.388.jpg" and d["vorlagen_neu_aufgebaut"] is True
    assert d["vorlagen_pro_ziffer"]["9"] == 0 and d["vorlagen_pro_ziffer"]["8"] >= 1
    assert [p.name for p in (tmp_path / "lernbilder").iterdir()] == [d["name"]]
    assert (tmp_path / "lernbilder" / d["name"]).read_bytes() == jpeg
    assert client.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True

    assert client.post(f"/admin/lernbilder/{d['name']}/wert?wert=abc").status_code == 400
    assert client.post(f"/admin/lernbilder/{d['name']}/wert?wert=100000").status_code == 400


def test_ohne_lerneffekt_bleiben_vorlagen_beim_loeschen(tmp_path, jpeg):
    with _client(tmp_path) as c:
        _lernen(c, jpeg)
    vorher = sorted(tmp_path.glob("vorlagen/*/*.png"))
    with _client(tmp_path, lerneffekt=False) as c:
        name = c.get("/admin/lernbilder").json()[0]["name"]
        d = c.post(f"/admin/lernbilder/{name}/loeschen").json()
        assert d["vorlagen_neu_aufgebaut"] is False and d["lernbilder"] == 0
        assert sorted(tmp_path.glob("vorlagen/*/*.png")) == vorher
        # ausdrücklicher Neuaufbau wirkt trotzdem
        assert c.post("/admin/neu-aufbauen").json()["fehlende_vorlagen"] == list(range(10))


# ---- Vorlagen ---------------------------------------------------------------


def test_vorlagen_als_base64(client, jpeg):
    _lernen(client, jpeg)
    daten = client.get("/admin/vorlagen").json()
    assert set(daten) == {str(z) for z in range(10)}
    assert len(daten["5"]) == 1 and daten["5"][0]["name"].endswith("_r3.png")
    png = base64.b64decode(daten["5"][0]["png"])
    assert cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE).shape == (40, 24)


def test_neu_aufbauen_entfernt_fremde_vorlagen(client, jpeg, tmp_path):
    _lernen(client, jpeg)
    fremd = tmp_path / "vorlagen" / "7" / "manuell.png"
    cv2.imwrite(str(fremd), np.random.default_rng(1).integers(0, 256, (40, 24), dtype=np.uint8))
    d = client.post("/admin/neu-aufbauen").json()
    assert d["vorlagen_neu_aufgebaut"] is True and d["vorlagen_pro_ziffer"]["7"] == 0
    assert not fremd.exists()


# ---- Export & Import --------------------------------------------------------


def test_export_import_ersetzen(tmp_path, jpeg):
    quelle, ziel = tmp_path / "quelle", tmp_path / "ziel"
    with _client(quelle) as c:
        _lernen(c, jpeg)
        status = c.get("/status").json()
        export = c.get("/admin/export.zip")
    assert export.headers["content-type"] == "application/zip"
    assert "attachment" in export.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(export.content)) as z:
        namen = z.namelist()
        info = json.loads(z.read("modell.json"))
    assert info["lernbilder"] == 1 and info["vorlagen"] == sum(status["vorlagen_pro_ziffer"].values())
    assert sum(n.startswith("lernbilder/") for n in namen) == 1
    assert sum(n.startswith("vorlagen/") for n in namen) == info["vorlagen"]

    with _client(ziel) as c:
        _lernen(c, jpeg, "123.456")  # wird ersetzt
        d = c.post("/admin/import?modus=ersetzen", content=export.content).json()
        assert d["lernbilder_neu"] == 1 and d["lernbilder"] == 1 and d["vorlagen_neu_aufgebaut"] is True
        assert c.get("/status").json() == status
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["wert"] == 506.388
    assert [p.name for p in (ziel / "lernbilder").iterdir()] == [p.name for p in (quelle / "lernbilder").iterdir()]


def test_import_ersetzen_ohne_lerneffekt_uebernimmt_vorlagen_1zu1(tmp_path, jpeg):
    with _client(tmp_path / "quelle") as c:
        _lernen(c, jpeg)
        export = c.get("/admin/export.zip").content
    with _client(tmp_path / "ziel", lerneffekt=False) as c:
        d = c.post("/admin/import?modus=ersetzen", content=export).json()
        assert d["vorlagen_neu_aufgebaut"] is False
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True
    quelle = sorted(p.relative_to(tmp_path / "quelle") for p in (tmp_path / "quelle").glob("vorlagen/*/*.png"))
    ziel = sorted(p.relative_to(tmp_path / "ziel") for p in (tmp_path / "ziel").glob("vorlagen/*/*.png"))
    assert quelle == ziel


def test_import_ergaenzen_nach_zeitstempel(client, jpeg, tmp_path):
    _lernen(client, jpeg)
    name = client.get("/admin/lernbilder").json()[0]["name"]
    zeitstempel = name.split("_")[0]
    korrigiert = client.post(f"/admin/lernbilder/{name}/wert?wert=506.389").json()["name"]
    paket = _zip({
        f"lernbilder/{name}": jpeg,                                   # gleicher Zeitstempel, alter Wert
        "lernbilder/20260101T000000000000Z_506.388.jpg": jpeg,        # neu
        "lernbilder/._20260101T000000000000Z_506.388.jpg": b"apple",  # macOS-Beiwerk
        "__MACOSX/lernbilder/x.jpg": b"apple",
        "vorlagen/5/irgendwas.png": cv2.imencode(".png", np.zeros((40, 24), np.uint8))[1].tobytes(),
        "liesmich.txt": b"x",
    })
    d = client.post("/admin/import?modus=ergaenzen", content=paket).json()
    assert d["lernbilder_neu"] == 1 and d["lernbilder"] == 2 and d["uebersprungen"] == 1
    namen = sorted(p.name for p in (tmp_path / "lernbilder").iterdir())
    assert namen == ["20260101T000000000000Z_506.388.jpg", korrigiert]  # Korrektur bleibt
    assert korrigiert.startswith(zeitstempel)
    # danach gelernte Bilder bekommen trotzdem einen neueren Zeitstempel
    _lernen(client, jpeg)
    assert sorted(p.name for p in (tmp_path / "lernbilder").iterdir())[-1] > korrigiert


def test_import_zip_des_data_ordners(client, jpeg):
    paket = _zip({"data/lernbilder/20261109T192122393524Z_506.388.jpg": jpeg})
    d = client.post("/admin/import", content=paket).json()
    assert d["modus"] == "ergaenzen" and d["lernbilder_neu"] == 1
    assert client.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True


@pytest.mark.parametrize(
    "inhalt, meldung",
    [
        (b"", "Leerer"),
        (b"kein zip", "Keine gültige ZIP"),
        (_zip({"liesmich.txt": b"x"}), "keine Lernbilder"),
        (_zip({"lernbilder/../../boese_1.000.jpg": b"\xff\xd8x"}), "keine Lernbilder"),
        (_zip({"lernbilder/20260101T000000000000Z_506.388.jpg": b"kein bild"}), "keine Lernbilder"),
    ],
)
def test_import_ungueltig(client, jpeg, tmp_path, inhalt, meldung):
    _lernen(client, jpeg)
    antwort = client.post("/admin/import?modus=ersetzen", content=inhalt)
    assert antwort.status_code == 400 and meldung in antwort.json()["detail"]
    assert client.get("/admin/info").json()["lernbilder"] == 1  # nichts verändert
    assert not (tmp_path.parent / "boese_1.000.jpg").exists()


def test_import_falscher_modus(client):
    assert client.post("/admin/import?modus=alles", content=b"x").status_code == 422


# ---- Erstausstattung (Home-Assistant-Add-on) --------------------------------


@pytest.fixture
def mitgeliefert(tmp_path, jpeg) -> Path:
    """Ein fertiges Modell wie im Add-on unter /opt/wasseruhr/modell."""
    with _client(tmp_path / "training") as c:
        _lernen(c, jpeg)
    return tmp_path / "training"


def test_erstausstattung_uebernimmt_modell_einmalig(tmp_path, jpeg, mitgeliefert):
    daten = tmp_path / "addon_data"
    with _client(daten, modell_verzeichnis=mitgeliefert) as c:
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True
        info = c.get("/admin/info").json()["erstausstattung"]
        assert info["uebernommen"] is True and info["lernbilder"] == 1 and info["vorlagen"] >= 5
        # Nachtrainieren im Add-on: Korrektur löscht das einzige Lernbild
        name = c.get("/admin/lernbilder").json()[0]["name"]
        c.post(f"/admin/lernbilder/{name}/loeschen")
    # Neustart (z. B. Add-on-Update): das mitgelieferte Modell kommt NICHT zurück
    with _client(daten, modell_verzeichnis=mitgeliefert) as c:
        assert c.get("/admin/info").json()["lernbilder"] == 0
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["wert"] is None


def test_erstausstattung_nicht_ueber_vorhandene_daten(tmp_path, jpeg, mitgeliefert):
    daten = tmp_path / "addon_data"
    with _client(daten) as c:
        _lernen(c, jpeg, "506.399")
    with _client(daten, modell_verzeichnis=mitgeliefert) as c:
        info = c.get("/admin/info").json()
        assert info["erstausstattung"]["uebernommen"] is False
        assert [lb["wert"] for lb in c.get("/admin/lernbilder").json()] == [506.399]


def test_erstausstattung_ohne_lerneffekt_laedt_vorlagen(tmp_path, jpeg, mitgeliefert):
    with _client(tmp_path / "addon_data", modell_verzeichnis=mitgeliefert, lerneffekt=False) as c:
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True


def test_erstausstattung_ignoriert_macos_beiwerk(tmp_path, jpeg, mitgeliefert):
    (mitgeliefert / "lernbilder" / "._20260101T000000000000Z_1.000.jpg").write_bytes(b"apple")
    (mitgeliefert / "vorlagen" / "5" / "._x.png").write_bytes(b"apple")
    (mitgeliefert / ".DS_Store").write_bytes(b"apple")
    daten = tmp_path / "addon_data"
    with _client(daten, modell_verzeichnis=mitgeliefert) as c:
        assert c.get("/admin/info").json()["lernbilder"] == 1
    assert not list(daten.rglob("._*"))


def test_erstausstattung_ohne_modell_versucht_es_spaeter_wieder(tmp_path, jpeg, mitgeliefert):
    daten = tmp_path / "addon_data"
    leer = tmp_path / "leer"
    leer.mkdir()
    (leer / ".gitkeep").touch()  # so liegt der Ordner im Repository
    for quelle in (tmp_path / "fehlt", leer):
        with _client(daten, modell_verzeichnis=quelle) as c:
            assert c.get("/admin/info").json()["erstausstattung"] is None
    assert not (daten / modell.MARKER).exists()
    with _client(daten, modell_verzeichnis=mitgeliefert) as c:
        assert c.get("/admin/info").json()["erstausstattung"]["uebernommen"] is True


# ---- Zugriff nur über Ingress -----------------------------------------------


def test_admin_nur_ueber_ingress(tmp_path, jpeg):
    with _client(tmp_path, admin_nur_ingress=True) as heimnetz:
        assert heimnetz.get("/admin").status_code == 403
        assert heimnetz.get("/admin/export.zip").status_code == 403
        assert heimnetz.post("/admin/import?modus=ersetzen", content=b"x").status_code == 403
        assert "Seitenleiste" in heimnetz.get("/admin/info").json()["detail"]
        # API und Lernseite bleiben im Heimnetz erreichbar, nur ohne Verwaltungs-Reiter
        assert heimnetz.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG).status_code == 200
        assert heimnetz.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True
        assert 'href="admin"' not in heimnetz.get("/").text
    with _client(tmp_path, client=INGRESS, admin_nur_ingress=True) as ingress:
        assert ingress.get("/admin").status_code == 200
        assert ingress.get("/admin/info").json()["lernbilder"] == 1
        assert 'href="admin"' in ingress.get("/").text


# ---- Kamera jetzt ablesen ---------------------------------------------------


def test_kamera_ablesen(tmp_path, jpeg, monkeypatch):
    aufrufe = []

    def schnappschuss(url, token, entity):
        aufrufe.append((url, token, entity))
        return jpeg

    monkeypatch.setattr(kamera, "schnappschuss", schnappschuss)
    with _client(tmp_path, kamera="camera.wasseruhr", ha_token="geheim") as c:
        assert 'id="kamera"' in c.get("/").text
        _lernen(c, jpeg)
        d = c.post("/kamera-ablesen").json()
        assert d["nr"] == 1 and d["sicher"] is True and d["wert"] == 506.388
        assert c.get("/debug.png?nr=1").status_code == 200
        assert c.get("/admin/info").json()["kamera_bereit"] is True
    assert aufrufe == [("http://supervisor/core/api", "geheim", "camera.wasseruhr")]


def test_kamera_ablesen_fehler(tmp_path, monkeypatch):
    with _client(tmp_path) as c:
        assert c.post("/kamera-ablesen").status_code == 400
        assert 'id="kamera"' not in c.get("/").text
    with _client(tmp_path, kamera="camera.wasseruhr") as c:  # ohne Token
        assert "Kein Zugang" in c.post("/kamera-ablesen").json()["detail"]

    def offline(*_):
        raise kamera.KameraFehler("camera.wasseruhr: HTTP 500 (Kamera liefert kein Bild (offline?))")

    monkeypatch.setattr(kamera, "schnappschuss", offline)
    with _client(tmp_path, kamera="camera.wasseruhr", ha_token="t") as c:
        antwort = c.post("/kamera-ablesen")
        assert antwort.status_code == 502 and "offline" in antwort.json()["detail"]


class _FakeHA(BaseHTTPRequestHandler):
    bild = b""

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer geheim":
            self.send_response(401)
            self.end_headers()
            return
        if self.path != "/core/api/camera_proxy/camera.wasseruhr":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.end_headers()
        self.wfile.write(self.bild)

    def log_message(self, *_):
        pass


def test_schnappschuss_gegen_http_server(jpeg):
    _FakeHA.bild = jpeg
    server = HTTPServer(("127.0.0.1", 0), _FakeHA)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    basis = f"http://127.0.0.1:{server.server_port}/core/api"
    try:
        assert kamera.schnappschuss(basis, "geheim", "camera.wasseruhr") == jpeg
        with pytest.raises(kamera.KameraFehler, match="401"):
            kamera.schnappschuss(basis, "falsch", "camera.wasseruhr")
        with pytest.raises(kamera.KameraFehler, match="404"):
            kamera.schnappschuss(basis, "geheim", "camera.andere")
    finally:
        server.shutdown()
        server.server_close()  # sonst nimmt der Socket noch Verbindungen an -> Timeout
    with pytest.raises(kamera.KameraFehler, match="nicht erreichbar"):
        kamera.schnappschuss(basis, "geheim", "camera.wasseruhr")


# ---- Konfiguration ----------------------------------------------------------


def test_konfig_addon_variablen():
    k = Konfig.aus_umgebung({})
    assert k.kamera is None and k.ha_token is None and not k.admin_nur_ingress and not k.ist_addon
    assert k.modell_verzeichnis is None
    k = Konfig.aus_umgebung({
        "SUPERVISOR_TOKEN": "abc", "KAMERA": "camera.wasseruhrkamera_ov3660_camera",
        "ADMIN_NUR_INGRESS": "an", "MODELL_DIR": "/opt/wasseruhr/modell",
    })
    assert k.ist_addon and k.ha_token == "abc" and k.admin_nur_ingress
    assert k.kamera == "camera.wasseruhrkamera_ov3660_camera"
    assert k.modell_verzeichnis == Path("/opt/wasseruhr/modell")
    assert "abc" not in repr(k)  # Token taucht nie in Logs auf
    assert Konfig.aus_umgebung({"HA_TOKEN": "x", "SUPERVISOR_TOKEN": "y"}).ha_token == "x"
    with pytest.raises(KonfigFehler):
        Konfig.aus_umgebung({"KAMERA": "wasseruhr"})


def test_modell_verzeichnis_lesen_toleriert_praefix(tmp_path, jpeg):
    (tmp_path / "data" / "lernbilder").mkdir(parents=True)
    (tmp_path / "data" / "lernbilder" / "20260101T000000000000Z_506.388.jpg").write_bytes(jpeg)
    inhalt = modell.verzeichnis_lesen(tmp_path)
    assert list(inhalt.lernbilder) == ["20260101T000000000000Z_506.388.jpg"]
