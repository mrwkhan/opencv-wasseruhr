"""Admin page (/admin), model export/import, bundled model of the add-on and
"Read camera now"."""

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

from app import camera, model
from app.config import Config, ConfigError
from app.main import create_app

EXAMPLE = Path(__file__).parent / "example.jpg"
EXAMPLE_VALUE = "506.388"
JPEG = {"Content-Type": "image/jpeg"}
INGRESS = ("172.30.32.2", 40000)


@pytest.fixture
def jpeg() -> bytes:
    return EXAMPLE.read_bytes()


def _client(tmp_path: Path, client=("testclient", 50000), **kwargs) -> TestClient:
    return TestClient(create_app(Config(data_dir=tmp_path, **kwargs)), client=client)


@pytest.fixture
def client(tmp_path):
    with _client(tmp_path) as c:
        yield c


def _learn(c, jpeg, value=EXAMPLE_VALUE):
    response = c.post(f"/learn?value={value}", content=jpeg, headers=JPEG)
    assert response.status_code == 200, response.text
    return response.json()


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buffer.getvalue()


# ---- Page, overview ------------------------------------------------------------


def test_admin_page_and_info(client, jpeg):
    page = client.get("/admin")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert 'href="admin/export.zip"' in page.text and "fetch(" in page.text
    assert 'id="empty-hint" hidden' in page.text and "[hidden] { display:none !important; }" in page.text
    _learn(client, jpeg)
    info = client.get("/admin/info").json()
    assert info["training_images"] == 1 and info["learning"] is True
    assert info["missing_templates"] == [1, 2, 4, 7, 9]
    assert info["settings"]["MIN_SCORE"] == 0.70 and len(info["settings"]["ROIS"]) == 8
    assert info["camera_ready"] is False and info["addon"] is False and info["bundled_model"] is None


def test_readings_newest_first(client, jpeg):
    assert client.get("/admin/readings").json() == []
    client.post("/read", content=jpeg, headers=JPEG)
    _learn(client, jpeg)
    client.post("/read", content=jpeg, headers=JPEG)
    readings = client.get("/admin/readings").json()
    assert [r["number"] for r in readings] == [2, 1]
    assert readings[0]["certain"] is True and readings[0]["value"] == 506.388 and readings[1]["value"] is None


def test_training_page_links_the_admin_page(client):
    assert 'href="admin"' in client.get("/").text


# ---- Training images -------------------------------------------------------------


def test_images_list_original_and_counter_crop(client, jpeg):
    _learn(client, jpeg)
    _learn(client, jpeg, "506.389")
    images = client.get("/admin/images").json()
    assert [i["value"] for i in images] == [506.389, 506.388]  # newest first
    name = images[1]["name"]
    assert name.endswith("_506.388.jpg") and images[1]["time"].startswith("20")

    original = client.get(f"/admin/images/{name}")
    assert original.status_code == 200 and original.content == jpeg
    crop = client.get(f"/admin/images/{name}?counter=1")
    image = cv2.imdecode(np.frombuffer(crop.content, np.uint8), cv2.IMREAD_COLOR)
    # counter: ROIs x 130..467, y 144..196, plus a 12 px margin
    assert image.shape[:2] == (196 - 144 + 24, 467 - 130 + 24)


@pytest.mark.parametrize("name", ["missing.jpg", "..%2F..%2Fetc%2Fpasswd", "%2E%2E"])
def test_unknown_image(client, jpeg, name):
    _learn(client, jpeg)
    assert client.get(f"/admin/images/{name}").status_code == 404
    assert client.post(f"/admin/images/{name}/delete").status_code == 404


def test_deleting_an_image_rebuilds_the_templates(client, jpeg, tmp_path):
    _learn(client, jpeg)
    name = client.get("/admin/images").json()[0]["name"]
    response = client.post(f"/admin/images/{name}/delete").json()
    assert response["templates_rebuilt"] is True and response["training_images"] == 0
    assert response["missing_templates"] == list(range(10))
    assert not list(tmp_path.glob("templates/*/*.png"))
    assert client.post("/read", content=jpeg, headers=JPEG).json()["value"] is None


def test_correcting_an_image(client, jpeg, tmp_path):
    _learn(client, jpeg, "506.399")  # learned wrongly: two 9s instead of 8s
    assert client.get("/status").json()["templates_per_digit"]["9"] >= 1
    name = client.get("/admin/images").json()[0]["name"]
    timestamp = name.split("_")[0]

    response = client.post(f"/admin/images/{name}/value?value=506,388")
    assert response.status_code == 200, response.text
    d = response.json()
    assert d["name"] == f"{timestamp}_506.388.jpg" and d["templates_rebuilt"] is True
    assert d["templates_per_digit"]["9"] == 0 and d["templates_per_digit"]["8"] >= 1
    assert [p.name for p in (tmp_path / "images").iterdir()] == [d["name"]]
    assert (tmp_path / "images" / d["name"]).read_bytes() == jpeg
    assert client.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True

    assert client.post(f"/admin/images/{d['name']}/value?value=abc").status_code == 400
    assert client.post(f"/admin/images/{d['name']}/value?value=100000").status_code == 400


def test_without_learning_templates_stay_on_delete(tmp_path, jpeg):
    with _client(tmp_path) as c:
        _learn(c, jpeg)
    before = sorted(tmp_path.glob("templates/*/*.png"))
    with _client(tmp_path, learning=False) as c:
        name = c.get("/admin/images").json()[0]["name"]
        d = c.post(f"/admin/images/{name}/delete").json()
        assert d["templates_rebuilt"] is False and d["training_images"] == 0
        assert sorted(tmp_path.glob("templates/*/*.png")) == before
        # an explicit rebuild still works
        assert c.post("/admin/rebuild").json()["missing_templates"] == list(range(10))


# ---- Templates -------------------------------------------------------------------


def test_templates_as_base64(client, jpeg):
    _learn(client, jpeg)
    data = client.get("/admin/templates").json()
    assert set(data) == {str(d) for d in range(10)}
    assert len(data["5"]) == 1 and data["5"][0]["name"].endswith("_r3.png")
    png = base64.b64decode(data["5"][0]["png"])
    assert cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE).shape == (40, 24)


def test_rebuild_removes_foreign_templates(client, jpeg, tmp_path):
    _learn(client, jpeg)
    foreign = tmp_path / "templates" / "7" / "manual.png"
    cv2.imwrite(str(foreign), np.random.default_rng(1).integers(0, 256, (40, 24), dtype=np.uint8))
    d = client.post("/admin/rebuild").json()
    assert d["templates_rebuilt"] is True and d["templates_per_digit"]["7"] == 0
    assert not foreign.exists()


# ---- Export & import -------------------------------------------------------------


def test_export_import_replace(tmp_path, jpeg):
    source, target = tmp_path / "source", tmp_path / "target"
    with _client(source) as c:
        _learn(c, jpeg)
        status = c.get("/status").json()
        export = c.get("/admin/export.zip")
    assert export.headers["content-type"] == "application/zip"
    assert 'attachment; filename="wasseruhr-cv-model-' in export.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(export.content)) as z:
        names = z.namelist()
        info = json.loads(z.read("model.json"))
    assert info["images"] == 1 and info["templates"] == sum(status["templates_per_digit"].values())
    assert sum(n.startswith("images/") for n in names) == 1
    assert sum(n.startswith("templates/") for n in names) == info["templates"]

    with _client(target) as c:
        _learn(c, jpeg, "123.456")  # gets replaced
        d = c.post("/admin/import?mode=replace", content=export.content).json()
        assert d["new_images"] == 1 and d["training_images"] == 1 and d["templates_rebuilt"] is True
        assert c.get("/status").json() == status
        assert c.post("/read", content=jpeg, headers=JPEG).json()["value"] == 506.388
    assert [p.name for p in (target / "images").iterdir()] == [p.name for p in (source / "images").iterdir()]


def test_import_replace_without_learning_takes_templates_1_to_1(tmp_path, jpeg):
    with _client(tmp_path / "source") as c:
        _learn(c, jpeg)
        export = c.get("/admin/export.zip").content
    with _client(tmp_path / "target", learning=False) as c:
        d = c.post("/admin/import?mode=replace", content=export).json()
        assert d["templates_rebuilt"] is False
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True
    source = sorted(p.relative_to(tmp_path / "source") for p in (tmp_path / "source").glob("templates/*/*.png"))
    target = sorted(p.relative_to(tmp_path / "target") for p in (tmp_path / "target").glob("templates/*/*.png"))
    assert source == target


def test_import_merge_by_timestamp(client, jpeg, tmp_path):
    _learn(client, jpeg)
    name = client.get("/admin/images").json()[0]["name"]
    timestamp = name.split("_")[0]
    corrected = client.post(f"/admin/images/{name}/value?value=506.389").json()["name"]
    package = _zip({
        f"images/{name}": jpeg,                                    # same timestamp, old value
        "images/20260101T000000000000Z_506.388.jpg": jpeg,         # new
        "images/._20260101T000000000000Z_506.388.jpg": b"apple",   # macOS extras
        "__MACOSX/images/x.jpg": b"apple",
        "templates/5/whatever.png": cv2.imencode(".png", np.zeros((40, 24), np.uint8))[1].tobytes(),
        "readme.txt": b"x",
    })
    d = client.post("/admin/import?mode=merge", content=package).json()
    assert d["new_images"] == 1 and d["training_images"] == 2 and d["skipped"] == 1
    names = sorted(p.name for p in (tmp_path / "images").iterdir())
    assert names == ["20260101T000000000000Z_506.388.jpg", corrected]  # the correction stays
    assert corrected.startswith(timestamp)
    # images learned afterwards still get a newer timestamp
    _learn(client, jpeg)
    assert sorted(p.name for p in (tmp_path / "images").iterdir())[-1] > corrected


def test_import_zip_of_the_data_folder(client, jpeg):
    package = _zip({"data/images/20261109T192122393524Z_506.388.jpg": jpeg})
    d = client.post("/admin/import", content=package).json()
    assert d["mode"] == "merge" and d["new_images"] == 1
    assert client.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True


def test_import_export_of_version_1(client, jpeg):
    """Exports of version 1.x use German folder names and modes."""
    package = _zip({
        "modell.json": b"{}",
        "lernbilder/20261109T192122393524Z_506.388.jpg": jpeg,
        "vorlagen/5/20261109T192122393524Z_r3.png": cv2.imencode(".png", np.full((40, 24), 99, np.uint8))[1].tobytes(),
    })
    d = client.post("/admin/import?mode=ersetzen", content=package).json()
    assert d["mode"] == "replace" and d["new_images"] == 1 and d["skipped"] == 0
    assert client.post("/admin/import?mode=ergaenzen", content=package).json()["mode"] == "merge"


@pytest.mark.parametrize(
    "content, message",
    [
        (b"", "Empty"),
        (b"no zip", "Not a valid ZIP"),
        (_zip({"readme.txt": b"x"}), "no training images"),
        (_zip({"images/../../evil_1.000.jpg": b"\xff\xd8x"}), "no training images"),
        (_zip({"images/20260101T000000000000Z_506.388.jpg": b"no image"}), "no training images"),
    ],
)
def test_import_invalid(client, jpeg, tmp_path, content, message):
    _learn(client, jpeg)
    response = client.post("/admin/import?mode=replace", content=content)
    assert response.status_code == 400 and message in response.json()["detail"]
    assert client.get("/admin/info").json()["training_images"] == 1  # nothing changed
    assert not (tmp_path.parent / "evil_1.000.jpg").exists()


def test_import_wrong_mode(client):
    assert client.post("/admin/import?mode=everything", content=b"x").status_code == 422


# ---- Bundled model (Home Assistant add-on) --------------------------------------------


@pytest.fixture
def bundled(tmp_path, jpeg) -> Path:
    """A finished model like in the add-on under /opt/wasseruhr/model."""
    with _client(tmp_path / "training") as c:
        _learn(c, jpeg)
    return tmp_path / "training"


def test_bundled_model_is_installed_once(tmp_path, jpeg, bundled):
    data = tmp_path / "addon_data"
    with _client(data, model_dir=bundled) as c:
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True
        info = c.get("/admin/info").json()["bundled_model"]
        assert info["installed"] is True and info["images"] == 1 and info["templates"] >= 5
        # training in the add-on: a correction deletes the only training image
        name = c.get("/admin/images").json()[0]["name"]
        c.post(f"/admin/images/{name}/delete")
    # restart (e.g. add-on update): the bundled model does NOT come back
    with _client(data, model_dir=bundled) as c:
        assert c.get("/admin/info").json()["training_images"] == 0
        assert c.post("/read", content=jpeg, headers=JPEG).json()["value"] is None


def test_bundled_model_not_over_existing_data(tmp_path, jpeg, bundled):
    data = tmp_path / "addon_data"
    with _client(data) as c:
        _learn(c, jpeg, "506.399")
    with _client(data, model_dir=bundled) as c:
        assert c.get("/admin/info").json()["bundled_model"]["installed"] is False
        assert [i["value"] for i in c.get("/admin/images").json()] == [506.399]


def test_bundled_model_without_learning_loads_templates(tmp_path, jpeg, bundled):
    with _client(tmp_path / "addon_data", model_dir=bundled, learning=False) as c:
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True


def test_bundled_model_ignores_macos_extras(tmp_path, jpeg, bundled):
    (bundled / "images" / "._20260101T000000000000Z_1.000.jpg").write_bytes(b"apple")
    (bundled / "templates" / "5" / "._x.png").write_bytes(b"apple")
    (bundled / ".DS_Store").write_bytes(b"apple")
    data = tmp_path / "addon_data"
    with _client(data, model_dir=bundled) as c:
        assert c.get("/admin/info").json()["training_images"] == 1
    assert not list(data.rglob("._*"))


def test_without_bundled_model_it_tries_again_later(tmp_path, jpeg, bundled):
    data = tmp_path / "addon_data"
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".gitkeep").touch()
    for source in (tmp_path / "missing", empty):
        with _client(data, model_dir=source) as c:
            assert c.get("/admin/info").json()["bundled_model"] is None
    assert not (data / model.MARKER).exists()
    with _client(data, model_dir=bundled) as c:
        assert c.get("/admin/info").json()["bundled_model"]["installed"] is True


# ---- Access only via the ingress -------------------------------------------------


def test_admin_only_via_ingress(tmp_path, jpeg):
    with _client(tmp_path, admin_ingress_only=True) as network:
        assert network.get("/admin").status_code == 403
        assert network.get("/admin/export.zip").status_code == 403
        assert network.post("/admin/import?mode=replace", content=b"x").status_code == 403
        assert "sidebar" in network.get("/admin/info").json()["detail"]
        # API and training page stay reachable in the local network, only without the admin tab
        assert network.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG).status_code == 200
        assert network.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True
        assert 'href="admin"' not in network.get("/").text
    with _client(tmp_path, client=INGRESS, admin_ingress_only=True) as ingress:
        assert ingress.get("/admin").status_code == 200
        assert ingress.get("/admin/info").json()["training_images"] == 1
        assert 'href="admin"' in ingress.get("/").text


# ---- Read camera now -------------------------------------------------------------


def test_read_camera(tmp_path, jpeg, monkeypatch):
    calls = []

    def snapshot(url, token, entity):
        calls.append((url, token, entity))
        return jpeg

    monkeypatch.setattr(camera, "snapshot", snapshot)
    with _client(tmp_path, camera="camera.water_meter", ha_token="secret", language="en") as c:
        assert 'id="camera"' in c.get("/").text
        _learn(c, jpeg)
        d = c.post("/read-camera").json()
        assert d["reading"] == 1 and d["certain"] is True and d["value"] == 506.388
        assert c.get("/debug.png?reading=1").status_code == 200
        assert c.get("/admin/info").json()["camera_ready"] is True
        legacy = c.post("/kamera-ablesen").json()  # version 1.x
        assert legacy["nr"] == 2 and legacy["wert"] == 506.388
    assert calls[0] == ("http://supervisor/core/api", "secret", "camera.water_meter")


def test_read_camera_errors(tmp_path, monkeypatch):
    with _client(tmp_path) as c:
        assert c.post("/read-camera").status_code == 400
        assert 'id="camera"' not in c.get("/").text
    with _client(tmp_path, camera="camera.water_meter") as c:  # without a token
        assert "No access" in c.post("/read-camera").json()["detail"]

    def offline(*_):
        raise camera.CameraError("camera.water_meter: HTTP 500 (camera returns no image (offline?))")

    monkeypatch.setattr(camera, "snapshot", offline)
    with _client(tmp_path, camera="camera.water_meter", ha_token="t", language="en") as c:
        response = c.post("/read-camera")
        assert response.status_code == 502 and "offline" in response.json()["detail"]


class _FakeHA(BaseHTTPRequestHandler):
    image = b""

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer secret":
            self.send_response(401)
            self.end_headers()
            return
        if self.path != "/core/api/camera_proxy/camera.water_meter":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.end_headers()
        self.wfile.write(self.image)

    def log_message(self, *_):
        pass


def test_snapshot_against_an_http_server(jpeg):
    _FakeHA.image = jpeg
    server = HTTPServer(("127.0.0.1", 0), _FakeHA)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/core/api"
    try:
        assert camera.snapshot(base, "secret", "camera.water_meter") == jpeg
        with pytest.raises(camera.CameraError, match="401"):
            camera.snapshot(base, "wrong", "camera.water_meter")
        with pytest.raises(camera.CameraError, match="404"):
            camera.snapshot(base, "secret", "camera.other")
    finally:
        server.shutdown()
        server.server_close()  # otherwise the socket still accepts connections -> timeout
    with pytest.raises(camera.CameraError, match="not reachable"):
        camera.snapshot(base, "secret", "camera.water_meter")


# ---- Configuration -----------------------------------------------------------------


def test_config_addon_variables():
    c = Config.from_env({})
    assert c.camera is None and c.ha_token is None and not c.admin_ingress_only and not c.is_addon
    assert c.model_dir is None
    c = Config.from_env({
        "SUPERVISOR_TOKEN": "abc", "CAMERA": "camera.wasseruhrkamera_ov3660_camera",
        "ADMIN_INGRESS_ONLY": "true", "MODEL_DIR": "/opt/wasseruhr/model",
    })
    assert c.is_addon and c.ha_token == "abc" and c.admin_ingress_only
    assert c.camera == "camera.wasseruhrkamera_ov3660_camera"
    assert c.model_dir == Path("/opt/wasseruhr/model")
    assert "abc" not in repr(c)  # the token never shows up in logs
    assert Config.from_env({"HA_TOKEN": "x", "SUPERVISOR_TOKEN": "y"}).ha_token == "x"
    with pytest.raises(ConfigError):
        Config.from_env({"CAMERA": "water_meter"})


def test_reading_a_model_directory_tolerates_a_prefix(tmp_path, jpeg):
    (tmp_path / "data" / "images").mkdir(parents=True)
    (tmp_path / "data" / "images" / "20260101T000000000000Z_506.388.jpg").write_bytes(jpeg)
    assert list(model.read_directory(tmp_path).images) == ["20260101T000000000000Z_506.388.jpg"]
