"""Security: CSRF protection, size limits, decompression bombs, camera fetch, headers."""

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

from app import admin_page, camera, security
from app.config import Config
from app.main import create_app

ROOT = Path(__file__).parent.parent
EXAMPLE = Path(__file__).parent / "example.jpg"
JPEG = {"Content-Type": "image/jpeg"}
FOREIGN = {"Origin": "http://evil.example"}


@pytest.fixture
def jpeg() -> bytes:
    return EXAMPLE.read_bytes()


def _client(tmp_path, client=("testclient", 50000), **kwargs) -> TestClient:
    return TestClient(create_app(Config(data_dir=tmp_path, **kwargs)), client=client)


def _bomb(width=30000, height=30000) -> bytes:
    """Valid 16x16 JPEG whose header claims a huge size."""
    data = bytearray(cv2.imencode(".jpg", np.full((16, 16, 3), 128, np.uint8))[1].tobytes())
    i = data.index(b"\xff\xc0")
    data[i + 5 : i + 9] = struct.pack(">HH", height, width)
    return bytes(data)


# ---- CSRF / origin check -----------------------------------------------------------


def test_foreign_website_cannot_teach_anything(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post("/read", content=jpeg, headers=JPEG)
        for path in ("/learn?value=999.999&reading=1", "/lernen?wert=999.999&ablesung=1", "/read-camera",
                     "/admin/rebuild", "/admin/import?mode=replace"):
            response = c.post(path, headers=FOREIGN)
            assert response.status_code == 403, path
            assert "foreign website" in response.json()["detail"]
        assert c.post("/learn?value=1.000", content=jpeg, headers={**JPEG, "Origin": "null"}).status_code == 403
        assert c.get("/admin/info").json()["training_images"] == 0


def test_own_page_programs_and_ingress_stay_allowed(tmp_path, jpeg):
    with _client(tmp_path) as c:
        # Programs like curl: no Origin
        assert c.post("/learn?value=506.388", content=jpeg, headers=JPEG).status_code == 200
        # Training page in the browser: Origin == Host
        same = {**JPEG, "Origin": "http://testserver"}
        assert c.post("/learn?value=506.388", content=jpeg, headers=same).status_code == 200
        # Reading is allowed for everyone
        assert c.get("/status", headers=FOREIGN).status_code == 200
    with _client(tmp_path, client=(security.INGRESS_IP, 40000)) as ingress:
        # HA has logged the user in already; the Origin there is the HA address
        assert ingress.post("/learn?value=506.388", content=jpeg, headers={**JPEG, **FOREIGN}).status_code == 200


# ---- Size limits & decompression bomb ----------------------------------------------


def test_too_large_body_is_rejected(tmp_path, jpeg, monkeypatch):
    monkeypatch.setattr(security, "MAX_IMAGE_BYTES", 1000)
    with _client(tmp_path) as c:
        assert len(jpeg) > 1000
        for path in ("/read", "/learn?value=506.388"):
            response = c.post(path, content=jpeg, headers=JPEG)  # with Content-Length
            assert response.status_code == 413 and "larger than" in response.json()["detail"], path
            chunked = c.post(path, content=iter([jpeg[:600], jpeg[600:]]), headers=JPEG)
            assert chunked.status_code == 413, path
        assert c.get("/admin/info").json()["training_images"] == 0


def test_decompression_bomb_fresh_process():
    """OpenCV reads the pixel limit when it is loaded – hence a process of its own, without a preset environment."""
    env = {k: v for k, v in os.environ.items() if k != "OPENCV_IO_MAX_IMAGE_PIXELS"}
    script = (
        "import resource, sys\n"
        "from app.recognition import decode_image, ImageError\n"
        "import cv2, numpy as np\n"
        "photo = cv2.imencode('.jpg', np.zeros((3000, 4000, 3), np.uint8))[1].tobytes()\n"
        "print('PHOTO', decode_image(photo).shape)\n"  # a 12 MP phone photo must pass
        "try:\n"
        "    decode_image(sys.stdin.buffer.read()); print('DECODED')\n"
        "except ImageError as e:\n"
        "    print('REJECTED', e)\n"
        "print('RSS', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], input=_bomb(), capture_output=True, env=env,
        cwd=ROOT / "wasseruhr_cv", timeout=60,
    )
    output = result.stdout.decode()
    assert "PHOTO (3000, 4000, 3)" in output, output + result.stderr.decode()
    assert "REJECTED" in output and "too large" in output, output + result.stderr.decode()
    rss = int(output.split("RSS")[1])
    rss_mb = rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024  # macOS: bytes, Linux: KB
    assert rss_mb < 500, rss_mb  # instead of 2.7 GB


# ---- Importing broken ZIPs -------------------------------------------------------------


def _zip_with(jpeg: bytes) -> bytearray:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        z.writestr("images/20260101T000000000000Z_506.388.jpg", jpeg)
    return bytearray(buffer.getvalue())


def test_damaged_and_encrypted_zip(tmp_path, jpeg):
    damaged = _zip_with(jpeg)
    damaged[200] ^= 0xFF  # checksum no longer matches
    encrypted = _zip_with(jpeg)
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        encrypted[encrypted.index(signature) + offset] |= 0x01
    with _client(tmp_path) as c:
        for content, expected in ((damaged, "damaged"), (encrypted, "encrypted")):
            response = c.post("/admin/import?mode=replace", content=bytes(content))
            assert response.status_code == 400 and expected in response.json()["detail"]


# ---- Camera: no redirect, http(s) only, size limit -------------------------------------


class _Target(BaseHTTPRequestHandler):
    """Foreign server: must never see the token."""
    seen: list = []

    def do_GET(self):
        _Target.seen.append(self.headers.get("Authorization"))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"\xff\xd8 stolen")

    def log_message(self, *_):
        pass


def _server(handler):
    s = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def test_camera_follows_no_redirect():
    target = _server(_Target)

    class Redirector(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/steal")
            self.end_headers()

        def log_message(self, *_):
            pass

    redirector = _server(Redirector)
    try:
        with pytest.raises(camera.CameraError, match="redirects"):
            camera.snapshot(f"http://127.0.0.1:{redirector.server_port}/api", "secret", "camera.x")
        assert _Target.seen == []  # the token never reached the foreign target
    finally:
        for s in (target, redirector):
            s.shutdown()
            s.server_close()


def test_camera_http_only_and_size_limit(monkeypatch):
    with pytest.raises(camera.CameraError, match="http"):
        camera.snapshot("file:///etc", "secret", "camera.x")
    target = _server(_Target)
    monkeypatch.setattr(camera, "MAX_BYTES", 5)
    try:
        with pytest.raises(camera.CameraError, match="larger"):
            camera.snapshot(f"http://127.0.0.1:{target.server_port}/api", "t", "camera.x")
    finally:
        target.shutdown()
        target.server_close()


# ---- Headers & input check in the browser ---------------------------------------------


def test_security_headers(tmp_path):
    with _client(tmp_path) as c:
        for path in ("/health", "/", "/admin"):
            h = c.get(path).headers
            assert h["x-content-type-options"] == "nosniff", path
            assert h["content-security-policy"] == "frame-ancestors 'self'", path
        assert c.post("/learn?value=1", headers=FOREIGN).headers["x-content-type-options"] == "nosniff"


def test_browser_allows_more_than_five_integer_digits(tmp_path):
    with _client(tmp_path) as c:
        c.post("/read", content=EXAMPLE.read_bytes(), headers=JPEG)
        assert r"\d{1,9}" in c.get("/").text
    assert r"\d{1,9}" in admin_page.page("en")
