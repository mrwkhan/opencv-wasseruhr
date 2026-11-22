"""Sicherheit: CSRF-Schutz, Größenlimits, Dekompressionsbomben, Kamera-Abruf, Header."""

import io
import os
import struct
import subprocess
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import kamera, schutz, verwaltungsseite
from app.konfig import Konfig
from app.main import create_app

WURZEL = Path(__file__).parent.parent
BEISPIEL = Path(__file__).parent / "beispiel.jpg"
JPEG = {"Content-Type": "image/jpeg"}
FREMD = {"Origin": "http://boese.example"}


@pytest.fixture
def jpeg() -> bytes:
    return BEISPIEL.read_bytes()


def _client(tmp_path, client=("testclient", 50000), **kwargs) -> TestClient:
    return TestClient(create_app(Konfig(daten_verzeichnis=tmp_path, **kwargs)), client=client)


def _bombe(breite=30000, hoehe=30000) -> bytes:
    """Gültiges 16x16-JPEG, dessen Kopf eine riesige Größe behauptet."""
    daten = bytearray(cv2.imencode(".jpg", np.full((16, 16, 3), 128, np.uint8))[1].tobytes())
    i = daten.index(b"\xff\xc0")
    daten[i + 5 : i + 9] = struct.pack(">HH", hoehe, breite)
    return bytes(daten)


# ---- CSRF / Ursprungsprüfung ---------------------------------------------------


def test_fremde_webseite_kann_nichts_lernen(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post("/ablesen", content=jpeg, headers=JPEG)
        for pfad in ("/lernen?wert=999.999&ablesung=1", "/kamera-ablesen", "/admin/neu-aufbauen",
                     "/admin/import?modus=ersetzen"):
            antwort = c.post(pfad, headers=FREMD)
            assert antwort.status_code == 403, pfad
            assert "fremder Webseite" in antwort.json()["detail"]
        assert c.post("/lernen?wert=1.000", content=jpeg, headers={**JPEG, "Origin": "null"}).status_code == 403
        assert c.get("/admin/info").json()["lernbilder"] == 0


def test_eigene_seite_programme_und_ingress_bleiben_erlaubt(tmp_path, jpeg):
    with _client(tmp_path) as c:
        # Programme wie curl: kein Origin
        assert c.post("/lernen?wert=506.388", content=jpeg, headers=JPEG).status_code == 200
        # Lernseite im Browser: Origin == Host
        gleich = {**JPEG, "Origin": "http://testserver"}
        assert c.post("/lernen?wert=506.388", content=jpeg, headers=gleich).status_code == 200
        # Lesen ist für alle erlaubt
        assert c.get("/status", headers=FREMD).status_code == 200
    with _client(tmp_path, client=(schutz.INGRESS_IP, 40000)) as ingress:
        # HA hat den Benutzer schon angemeldet; der Origin ist dort die HA-Adresse
        assert ingress.post("/lernen?wert=506.388", content=jpeg, headers={**JPEG, **FREMD}).status_code == 200


# ---- Größenlimits & Dekompressionsbombe -------------------------------------------


def test_zu_grosser_body_wird_abgelehnt(tmp_path, jpeg, monkeypatch):
    monkeypatch.setattr(schutz, "MAX_BILD_BYTES", 1000)
    with _client(tmp_path) as c:
        assert len(jpeg) > 1000
        for pfad in ("/ablesen", "/lernen?wert=506.388"):
            antwort = c.post(pfad, content=jpeg, headers=JPEG)  # mit Content-Length
            assert antwort.status_code == 413, pfad
            gestueckelt = c.post(pfad, content=iter([jpeg[:600], jpeg[600:]]), headers=JPEG)  # chunked
            assert gestueckelt.status_code == 413, pfad
        assert c.get("/admin/info").json()["lernbilder"] == 0


def test_dekompressionsbombe_frischer_prozess():
    """OpenCV liest die Pixelgrenze beim Laden – daher ein eigener Prozess, ohne vorgegebene Umgebung."""
    env = {k: v for k, v in os.environ.items() if k != "OPENCV_IO_MAX_IMAGE_PIXELS"}
    skript = (
        "import resource, sys\n"
        "from app.erkennung import dekodiere_bild, BildFehler\n"
        "import cv2, numpy as np\n"
        "foto = cv2.imencode('.jpg', np.zeros((3000, 4000, 3), np.uint8))[1].tobytes()\n"
        "print('FOTO', dekodiere_bild(foto).shape)\n"  # 12-MP-Handyfoto muss durchgehen
        "try:\n"
        "    dekodiere_bild(sys.stdin.buffer.read()); print('DEKODIERT')\n"
        "except BildFehler as e:\n"
        "    print('ABGELEHNT', e)\n"
        "print('RSS', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)\n"
    )
    ergebnis = subprocess.run(
        [sys.executable, "-c", skript], input=_bombe(), capture_output=True, env=env,
        cwd=WURZEL / "wasseruhr_cv", timeout=60,
    )
    ausgabe = ergebnis.stdout.decode()
    assert "FOTO (3000, 4000, 3)" in ausgabe, ausgabe + ergebnis.stderr.decode()
    assert "ABGELEHNT" in ausgabe and "zu groß" in ausgabe, ausgabe + ergebnis.stderr.decode()
    rss = int(ausgabe.split("RSS")[1])
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # macOS: Bytes, Linux: KB
    assert rss_mb < 500, rss_mb  # statt 2,7 GB


# ---- Import kaputter ZIPs ------------------------------------------------------------


def _zip_mit(jpeg: bytes) -> bytearray:
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_STORED) as z:
        z.writestr("lernbilder/20260101T000000000000Z_506.388.jpg", jpeg)
    return bytearray(puffer.getvalue())


def test_beschaedigtes_und_verschluesseltes_zip(tmp_path, jpeg):
    kaputt = _zip_mit(jpeg)
    kaputt[200] ^= 0xFF  # Prüfsumme stimmt nicht mehr
    verschluesselt = _zip_mit(jpeg)
    for signatur, versatz in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        verschluesselt[verschluesselt.index(signatur) + versatz] |= 0x01
    with _client(tmp_path) as c:
        for inhalt, meldung in ((kaputt, "beschädigt"), (verschluesselt, "encrypted")):
            antwort = c.post("/admin/import?modus=ersetzen", content=bytes(inhalt))
            assert antwort.status_code == 400 and meldung in antwort.json()["detail"]


# ---- Kamera: keine Weiterleitung, nur http(s), Größenlimit -----------------------------


class _Ziel(BaseHTTPRequestHandler):
    """Fremder Server: darf den Token nie zu sehen bekommen."""
    gesehen: list = []

    def do_GET(self):
        _Ziel.gesehen.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"\xff\xd8 gestohlen")

    def log_message(self, *_):
        pass


def _server(handler):
    s = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_kamera_folgt_keiner_weiterleitung():
    ziel = _server(_Ziel)

    class Umleiter(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{ziel.server_port}/klau")
            self.end_headers()

        def log_message(self, *_):
            pass

    umleiter = _server(Umleiter)
    try:
        with pytest.raises(kamera.KameraFehler, match="leitet weiter"):
            kamera.schnappschuss(f"http://127.0.0.1:{umleiter.server_port}/api", "geheim", "camera.x")
        assert _Ziel.gesehen == []  # Token nie beim fremden Ziel angekommen
    finally:
        for s in (ziel, umleiter):
            s.shutdown()
            s.server_close()


def test_kamera_nur_http_und_groessenlimit(monkeypatch):
    with pytest.raises(kamera.KameraFehler, match="http"):
        kamera.schnappschuss("file:///etc", "geheim", "camera.x")
    ziel = _server(_Ziel)
    monkeypatch.setattr(kamera, "MAX_BYTES", 5)
    try:
        with pytest.raises(kamera.KameraFehler, match="größer"):
            kamera.schnappschuss(f"http://127.0.0.1:{ziel.server_port}/api", "t", "camera.x")
    finally:
        ziel.shutdown()
        ziel.server_close()


# ---- Header & Eingabeprüfung im Browser -------------------------------------------


def test_sicherheits_header(tmp_path):
    with _client(tmp_path) as c:
        for pfad in ("/health", "/", "/admin"):
            h = c.get(pfad).headers
            assert h["x-content-type-options"] == "nosniff", pfad
            assert h["content-security-policy"] == "frame-ancestors 'self'", pfad
        assert c.post("/lernen?wert=1", headers=FREMD).headers["x-content-type-options"] == "nosniff"


def test_browser_erlaubt_mehr_als_fuenf_vorkommastellen(tmp_path):
    with _client(tmp_path) as c:
        c.post("/ablesen", content=BEISPIEL.read_bytes(), headers=JPEG)
        assert r"\d{1,9}" in c.get("/").text
    assert r"\d{1,9}" in verwaltungsseite.SEITE
