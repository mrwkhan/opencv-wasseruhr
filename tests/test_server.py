"""Erreichbarkeit: Hauptport immer, HTTP und HTTPS fürs Heimnetz einzeln schaltbar –
als echter Prozess (start.py), inklusive sauberem Beenden per SIGTERM."""

import hashlib
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

WASSERUHR = Path(__file__).parent.parent / "wasseruhr_cv"


def _freie_ports(n):
    socks = [socket.socket() for _ in range(n)]
    for s in socks:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def _holen(url, timeout=1.0) -> tuple[int, bytes, bytes | None]:
    """(Status, Inhalt, DER-Zertifikat bei HTTPS)."""
    kontext = ssl.create_default_context()
    kontext.check_hostname = False
    kontext.verify_mode = ssl.CERT_NONE
    handler = urllib.request.HTTPSHandler(context=kontext)
    with urllib.request.build_opener(handler).open(url, timeout=timeout) as r:
        zert = r.fp.raw._sock.getpeercert(binary_form=True) if url.startswith("https") else None
        return r.status, r.read(), zert


def _warten(url, sekunden=30):
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        try:
            return _holen(url)
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise AssertionError(f"{url} antwortet nicht")


@pytest.fixture
def dienst(tmp_path):
    prozesse = []

    def starten(**env):
        umgebung = {
            k: v for k, v in os.environ.items()
            if k not in ("HTTP", "HTTPS", "PORT", "HTTP_PORT", "HTTPS_PORT", "KAMERA", "SUPERVISOR_TOKEN", "HA_TOKEN")
        }
        umgebung.update(DATA_DIR=str(tmp_path / "data"), SSL_VERZEICHNIS=str(tmp_path / "ssl"),
                        ADDON_OPTIONEN=str(tmp_path / "gibt-es-nicht.json"), INTERVALL_MINUTEN="0", **env)
        p = subprocess.Popen([sys.executable, str(WASSERUHR / "start.py")], env=umgebung,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        prozesse.append(p)
        return p

    yield starten
    for p in prozesse:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_http_und_https_zusaetzlich_und_sauber_beenden(dienst, tmp_path):
    haupt, http, https = _freie_ports(3)
    p = dienst(PORT=str(haupt), HTTP="an", HTTP_PORT=str(http), HTTPS="an", HTTPS_PORT=str(https))
    assert _warten(f"http://127.0.0.1:{haupt}/health")[1] == b'{"ok":true}'
    assert _warten(f"http://127.0.0.1:{http}/health")[1] == b'{"ok":true}'
    status, inhalt, zert = _warten(f"https://127.0.0.1:{https}/health")
    assert status == 200 and inhalt == b'{"ok":true}' and zert
    # ohne eigenes Zertifikat: selbstsigniertes im Datenverzeichnis
    assert (tmp_path / "data" / "tls" / "selbstsigniert.crt").is_file()
    # alle Listener teilen eine App (gleicher Zustand)
    assert _holen(f"http://127.0.0.1:{http}/status")[1] == _holen(f"https://127.0.0.1:{https}/status")[1]

    p.send_signal(signal.SIGTERM)
    ausgabe = p.communicate(timeout=15)[0].decode()
    assert p.returncode == 0, ausgabe
    assert "Erreichbar: Ingress/intern" in ausgabe and "HTTP :" in ausgabe and "selbstsigniertes Zertifikat" in ausgabe
    assert "Application shutdown complete" in ausgabe


def test_eigenes_zertifikat_wird_genutzt(dienst, tmp_path):
    ssl_dir = tmp_path / "ssl"
    ssl_dir.mkdir()
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=eigen",
         "-keyout", str(ssl_dir / "privkey.pem"), "-out", str(ssl_dir / "fullchain.pem")],
        check=True, capture_output=True,
    )
    pem = (ssl_dir / "fullchain.pem").read_text()
    erwartet = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    haupt, https = _freie_ports(2)
    p = dienst(PORT=str(haupt), HTTPS="an", HTTPS_PORT=str(https))
    zert = _warten(f"https://127.0.0.1:{https}/health")[2]
    assert hashlib.sha256(zert).hexdigest() == erwartet
    assert not (tmp_path / "data" / "tls").exists()
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=15)


def test_ausgeschaltet_heisst_kein_listener(dienst):
    haupt, http, https = _freie_ports(3)
    p = dienst(PORT=str(haupt), HTTP="aus", HTTP_PORT=str(http), HTTPS="aus", HTTPS_PORT=str(https))
    _warten(f"http://127.0.0.1:{haupt}/health")
    for port in (http, https):
        with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
            _holen(f"http://127.0.0.1:{port}/health")
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=15) == 0


def test_gleiche_ports_werden_abgelehnt(dienst):
    p = dienst(PORT="18200", HTTP="an", HTTP_PORT="18200")
    ausgabe = p.communicate(timeout=30)[0].decode()
    assert p.returncode != 0 and "Ports müssen" in ausgabe
