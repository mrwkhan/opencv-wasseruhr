"""Access: main port always, HTTP and HTTPS for the local network switchable
separately – as a real process (start.py), including a clean stop via SIGTERM."""

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
CLEARED = ("HTTP", "HTTPS", "PORT", "HTTP_PORT", "HTTPS_PORT", "CAMERA", "KAMERA", "SUPERVISOR_TOKEN", "HA_TOKEN",
           "LANGUAGE", "SPRACHE")


def _free_ports(n):
    sockets = [socket.socket() for _ in range(n)]
    for s in sockets:
        s.bind(("127.0.0.1", 0))
    ports = [s.getsockname()[1] for s in sockets]
    for s in sockets:
        s.close()
    return ports


def _get(url, timeout=1.0) -> tuple[int, bytes, bytes | None]:
    """(status, content, DER certificate with HTTPS)."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    handler = urllib.request.HTTPSHandler(context=context)
    with urllib.request.build_opener(handler).open(url, timeout=timeout) as r:
        certificate = r.fp.raw._sock.getpeercert(binary_form=True) if url.startswith("https") else None
        return r.status, r.read(), certificate


def _wait(url, seconds=30):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            return _get(url)
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise AssertionError(f"{url} does not answer")


@pytest.fixture
def service(tmp_path):
    processes = []

    def start(**env):
        environment = {k: v for k, v in os.environ.items() if k not in CLEARED}
        environment.update(DATA_DIR=str(tmp_path / "data"), SSL_DIR=str(tmp_path / "ssl"),
                           ADDON_OPTIONS=str(tmp_path / "does-not-exist.json"), INTERVAL_MINUTES="0", **env)
        p = subprocess.Popen([sys.executable, str(WASSERUHR / "start.py")], env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        processes.append(p)
        return p

    yield start
    for p in processes:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_http_and_https_in_addition_and_clean_stop(service, tmp_path):
    main, http, https = _free_ports(3)
    p = service(PORT=str(main), HTTP="true", HTTP_PORT=str(http), HTTPS="true", HTTPS_PORT=str(https), LANGUAGE="de")
    assert _wait(f"http://127.0.0.1:{main}/health")[1] == b'{"ok":true}'
    assert _wait(f"http://127.0.0.1:{http}/health")[1] == b'{"ok":true}'
    status, content, certificate = _wait(f"https://127.0.0.1:{https}/health")
    assert status == 200 and content == b'{"ok":true}' and certificate
    # without an own certificate: a self-signed one in the data directory
    assert (tmp_path / "data" / "tls" / "self-signed.crt").is_file()
    # all listeners share one app (same state)
    assert _get(f"http://127.0.0.1:{http}/status")[1] == _get(f"https://127.0.0.1:{https}/status")[1]

    p.send_signal(signal.SIGTERM)
    output = p.communicate(timeout=15)[0].decode()
    assert p.returncode == 0, output
    # LANGUAGE=de: the log is German
    assert "Erreichbar: Ingress/intern" in output and "HTTP :" in output and "selbstsigniertes Zertifikat" in output
    assert "Application shutdown complete" in output


def test_own_certificate_is_used(service, tmp_path):
    ssl_dir = tmp_path / "ssl"
    ssl_dir.mkdir()
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=own",
         "-keyout", str(ssl_dir / "privkey.pem"), "-out", str(ssl_dir / "fullchain.pem")],
        check=True, capture_output=True,
    )
    pem = (ssl_dir / "fullchain.pem").read_text()
    expected = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
    main, https = _free_ports(2)
    p = service(PORT=str(main), HTTPS="true", HTTPS_PORT=str(https))
    certificate = _wait(f"https://127.0.0.1:{https}/health")[2]
    assert hashlib.sha256(certificate).hexdigest() == expected
    assert not (tmp_path / "data" / "tls").exists()
    p.send_signal(signal.SIGTERM)
    output = p.communicate(timeout=15)[0].decode()
    assert "Listening: Ingress/internal" in output and "certificate" in output  # default language: English


def test_switched_off_means_no_listener(service):
    main, http, https = _free_ports(3)
    p = service(PORT=str(main), HTTP="false", HTTP_PORT=str(http), HTTPS="false", HTTPS_PORT=str(https))
    _wait(f"http://127.0.0.1:{main}/health")
    for port in (http, https):
        with pytest.raises((urllib.error.URLError, ConnectionError, OSError)):
            _get(f"http://127.0.0.1:{port}/health")
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=15) == 0


def test_same_ports_are_rejected(service):
    p = service(PORT="18200", HTTP="true", HTTP_PORT="18200")
    output = p.communicate(timeout=30)[0].decode()
    # Language not known yet (auto, no Home Assistant): start-up error in English and German
    assert p.returncode != 0 and "Ports must" in output and "Ports müssen" in output
