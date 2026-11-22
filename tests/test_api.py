"""HTTP API: read, learn, status, debug image, training page – and the paths of version 1.x."""

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Config, ConfigError
from app.main import create_app
from app.recognition import DigitResult, combine, split_value
from app.templates import TemplateStore

EXAMPLE = Path(__file__).parent / "example.jpg"
EXAMPLE_VALUE = "506.388"
OTHER = Path(__file__).parent / "other.jpg"  # reading 506.614
JPEG = {"Content-Type": "image/jpeg"}


@pytest.fixture
def jpeg() -> bytes:
    return EXAMPLE.read_bytes()


def _client(tmp_path: Path, **kwargs) -> TestClient:
    return TestClient(create_app(Config(data_dir=tmp_path, **kwargs)))


@pytest.fixture
def client(tmp_path):
    with _client(tmp_path) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_without_templates_uncertain(client, jpeg):
    response = client.post("/read", content=jpeg, headers=JPEG)
    assert response.status_code == 200
    data = response.json()
    assert data["value"] is None
    assert data["certain"] is False
    assert data["missing_templates"] == list(range(10))
    assert [d["wheel"] for d in data["digits"]] == list(range(1, 9))
    assert all(d["digit"] is None for d in data["digits"])


def test_learn_then_read_certain(client, jpeg, tmp_path):
    response = client.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    assert response.status_code == 200, response.text
    learned = response.json()
    assert 5 <= learned["saved"] <= 8
    per_digit = learned["templates_per_digit"]
    assert set(per_digit) == {str(d) for d in range(10)}
    for d in "03568":
        assert per_digit[d] >= 1
    for d in "12479":
        assert per_digit[d] == 0
    assert sum(per_digit.values()) == learned["saved"]

    # Files: /data/templates/<digit>/<timestamp>_r<wheel>.png
    files = sorted(tmp_path.glob("templates/*/*.png"))
    assert len(files) == learned["saved"]
    for f in files:
        assert f.stem.rsplit("_r", 1)[1] in {str(w) for w in range(1, 9)}
        assert cv2.imread(str(f), cv2.IMREAD_GRAYSCALE).shape == (40, 24)
    assert all(f.name.endswith("_r3.png") for f in (tmp_path / "templates" / "5").iterdir())

    data = client.post("/read", content=jpeg, headers=JPEG).json()
    assert data["certain"] is True, data
    assert data["value"] == 506.388
    assert [d["digit"] for d in data["digits"]] == [0, 0, 5, 0, 6, 3, 8, 8]
    assert data["missing_templates"] == [1, 2, 4, 7, 9]
    for d in data["digits"]:
        assert set(d) == {"wheel", "digit", "score", "second", "second_score"}
        assert d["score"] >= 0.70
        assert d["score"] - d["second_score"] >= 0.08


def test_learn_ignores_duplicates(client, jpeg):
    first = client.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG).json()
    second = client.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG).json()
    assert second["saved"] == 0
    assert second["templates_per_digit"] == first["templates_per_digit"]


def test_status(client, jpeg):
    empty = client.get("/status").json()
    assert empty["templates_per_digit"] == {str(d): 0 for d in range(10)}
    client.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    status = client.get("/status").json()
    assert set(status) == {"templates_per_digit", "missing_templates", "learning", "training_images", "meter_reading"}
    assert status["templates_per_digit"]["5"] == 1
    assert status["missing_templates"] == [1, 2, 4, 7, 9]


def test_templates_survive_a_restart(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
        before = c.get("/status").json()
    with _client(tmp_path) as c:
        assert c.get("/status").json() == before
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True


# ---- Paths of version 1.x ------------------------------------------------------------


def test_german_paths_of_version_1_keep_working(client, jpeg):
    learned = client.post(f"/lernen?wert={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    assert learned.status_code == 200 and set(learned.json()) == {"gespeichert", "vorlagen_pro_ziffer"}
    read = client.post("/ablesen", content=jpeg, headers=JPEG).json()
    assert read["wert"] == 506.388 and read["sicher"] is True and read["fehlende_vorlagen"] == [1, 2, 4, 7, 9]
    assert set(read["ziffern"][0]) == {"rolle", "ziffer", "score", "zweitbeste", "score2"}
    assert client.post("/lernen?wert=506.388&ablesung=1").status_code == 200  # learn from the history (#1)
    assert client.get("/debug.png?nr=2").status_code == 200
    assert client.post("/kamera-ablesen").status_code == 400  # no camera configured
    assert "/ablesen" not in client.get("/openapi.json").text  # not documented any more


# ---- Archive & learning ----------------------------------------------------------------


def _template_files(tmp_path: Path) -> list[str]:
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.glob("templates/*/*.png"))


def test_learn_archives_every_image(client, jpeg, tmp_path):
    client.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    client.post("/learn?value=506,388", content=jpeg, headers=JPEG)  # duplicate, archived anyway
    archive = sorted((tmp_path / "images").iterdir())
    assert len(archive) == 2
    for file in archive:
        assert file.name.endswith("_506.388.jpg")
        assert file.read_bytes() == jpeg  # byte for byte
    assert client.get("/status").json()["training_images"] == 2


def test_invalid_images_are_not_archived(client, tmp_path):
    client.post(f"/learn?value={EXAMPLE_VALUE}", content=b"not an image", headers=JPEG)
    client.post("/learn?value=abc", content=b"not an image", headers=JPEG)
    assert not (tmp_path / "images").exists() or not any((tmp_path / "images").iterdir())


def test_without_learning_only_archive(tmp_path, jpeg):
    with _client(tmp_path, learning=False) as c:
        response = c.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG).json()
        assert response["saved"] == 0
        assert response["templates_per_digit"] == {str(d): 0 for d in range(10)}
        status = c.get("/status").json()
        assert status["learning"] is False and status["training_images"] == 1
        assert c.post("/read", content=jpeg, headers=JPEG).json()["value"] is None
    assert _template_files(tmp_path) == []

    # A restart WITH learning learns the collected images
    with _client(tmp_path) as c:
        data = c.post("/read", content=jpeg, headers=JPEG).json()
        assert data["certain"] is True and data["value"] == 506.388


def test_without_learning_templates_are_frozen(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    before = _template_files(tmp_path)
    foreign = tmp_path / "templates" / "7" / "manual.png"
    foreign.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(foreign), np.random.default_rng(1).integers(0, 256, (40, 24), dtype=np.uint8))

    with _client(tmp_path, learning=False) as c:
        assert c.get("/status").json()["templates_per_digit"]["7"] == 1  # nothing rebuilt
        c.post("/learn?value=506.393", content=jpeg, headers=JPEG)
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True
    assert _template_files(tmp_path) == sorted(before + ["templates/7/manual.png"])


def test_restart_with_learning_rebuilds_templates_identically(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    live = _template_files(tmp_path)
    # A file that does not come from the archive disappears on rebuild
    (tmp_path / "templates" / "7").mkdir(exist_ok=True)
    noise = np.random.default_rng(1).integers(0, 256, (40, 24), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "templates" / "7" / "manual.png"), noise)
    with _client(tmp_path) as c:
        assert c.get("/status").json()["templates_per_digit"]["7"] == 0
    assert _template_files(tmp_path) == live


def test_rebuild_uses_current_rois(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    old = cv2.imread(str(next((tmp_path / "templates" / "5").iterdir())), cv2.IMREAD_GRAYSCALE)
    shifted = tuple((x1, y1 + 4, x2, y2 + 4) for x1, y1, x2, y2 in Config().rois)
    with _client(tmp_path, rois=shifted) as c:
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True
    new = cv2.imread(str(next((tmp_path / "templates" / "5").iterdir())), cv2.IMREAD_GRAYSCALE)
    assert not np.array_equal(old, new)


def test_rebuild_skips_broken_training_images(tmp_path, jpeg):
    archive = tmp_path / "images"
    archive.mkdir()
    (archive / "20260101T000000000000Z_506.388.jpg").write_bytes(b"broken")
    (archive / "wrong_name.jpg").write_bytes(jpeg)
    (archive / "20260101T000000000001Z_506.388.jpg").write_bytes(jpeg)
    with _client(tmp_path) as c:
        assert c.post("/read", content=jpeg, headers=JPEG).json()["certain"] is True


@pytest.mark.parametrize("value", ["abc", "-1", "100000", "nan", ""])
def test_learn_invalid_value(client, jpeg, value):
    assert client.post(f"/learn?value={value}", content=jpeg, headers=JPEG).status_code == 400


def test_learn_without_value(client, jpeg):
    assert client.post("/learn", content=jpeg, headers=JPEG).status_code == 422


@pytest.mark.parametrize("path", ["/read", f"/learn?value={EXAMPLE_VALUE}"])
def test_not_a_jpeg(client, path):
    assert client.post(path, content=b"", headers=JPEG).status_code == 400
    assert client.post(path, content=b"not an image", headers=JPEG).status_code == 400


def test_roi_outside_the_image(tmp_path, jpeg):
    rois = ((0, 0, 20, 20),) * 7 + ((600, 400, 700, 500),)
    with _client(tmp_path, rois=rois) as c:
        response = c.post("/read", content=jpeg, headers=JPEG)
    assert response.status_code == 400
    assert "wheel 8" in response.json()["detail"]


def test_debug_png(client, jpeg):
    assert client.get("/debug.png").status_code == 404
    client.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    client.post("/read", content=jpeg, headers=JPEG)
    response = client.get("/debug.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    original = cv2.imread(str(EXAMPLE))
    assert image.shape[1] >= original.shape[1]
    assert image.shape[0] > original.shape[0] + 120  # digit strip below the image


# ---- Training page & learning from the history -----------------------------------------


def test_training_page_without_reading(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "No image read yet" in response.text


def test_training_page_shows_latest_reading(client, jpeg):
    client.post("/read", content=jpeg, headers=JPEG)
    page = client.get("/").text
    assert 'src="debug.png?reading=1"' in page
    assert 'data-reading="1"' in page
    assert "Digits without template: 0, 1, 2" in page


def test_learn_from_reading_without_body(client, jpeg, tmp_path):
    client.post("/read", content=jpeg, headers=JPEG)  # reading #1
    response = client.post(f"/learn?value={EXAMPLE_VALUE}&reading=1")
    assert response.status_code == 200, response.text
    assert response.json()["saved"] >= 5
    assert next((tmp_path / "images").iterdir()).read_bytes() == jpeg
    # the same image was read again right away (#2) and is now certain
    assert client.get("/debug.png?reading=2").status_code == 200
    page = client.get("/?reading=2").text
    assert '<span class="ok">certain</span>' in page and '<span class="bad">' not in page


def test_learn_takes_exactly_the_shown_image(client, jpeg, tmp_path):
    client.post("/read", content=jpeg, headers=JPEG)                # #1: 506.388
    client.post("/read", content=OTHER.read_bytes(), headers=JPEG)  # #2: newer call
    assert "A newer reading exists" in client.get("/?reading=1").text
    client.post(f"/learn?value={EXAMPLE_VALUE}&reading=1")
    assert next((tmp_path / "images").iterdir()).read_bytes() == jpeg


def test_learn_from_unknown_reading(client):
    assert client.post(f"/learn?value={EXAMPLE_VALUE}&reading=99").status_code == 404
    assert client.get("/debug.png?reading=99").status_code == 404


# ---- Units -----------------------------------------------------------------------------


def test_split_value():
    assert split_value(506.388, 8, 3) == [0, 0, 5, 0, 6, 3, 8, 8]
    assert split_value(0, 8, 3) == [0] * 8
    assert split_value(99999.999, 8, 3) == [9] * 8
    with pytest.raises(ValueError):
        split_value(100000, 8, 3)


def test_combine():
    results = [DigitResult(i + 1, d, 1.0, None, None) for i, d in enumerate([0, 0, 5, 0, 6, 3, 8, 8])]
    assert combine(results, 3) == 506.388
    results[2].digit = None
    assert combine(results, 3) is None


def test_max_templates_per_digit(tmp_path):
    store = TemplateStore(tmp_path, max_per_digit=3)
    rng = np.random.default_rng(0)
    for i in range(5):
        image = rng.integers(0, 256, (40, 24), dtype=np.uint8)  # random -> never a duplicate
        assert store.learn(f"20260101T000000{i:06d}Z", [7], [image]) == 1
    files = sorted((tmp_path / "7").glob("*.png"))
    assert len(files) == 3
    assert store.count_per_digit()["7"] == 3
    # The template learned last must stay
    assert np.array_equal(cv2.imread(str(files[-1]), cv2.IMREAD_GRAYSCALE), image)


def test_templates_without_contrast_are_neither_learned_nor_loaded(tmp_path, jpeg):
    # A black camera image must not create templates ...
    black = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))[1].tobytes()
    with _client(tmp_path) as c:
        assert c.post(f"/learn?value={EXAMPLE_VALUE}", content=black, headers=JPEG).json()["saved"] == 0
    # ... and a constant template put there by hand is ignored when loading
    folder = tmp_path / "templates" / "7"
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "manual.png"), np.zeros((40, 24), np.uint8))
    with _client(tmp_path, learning=False) as c:
        c.post(f"/learn?value={EXAMPLE_VALUE}", content=jpeg, headers=JPEG)
    with _client(tmp_path) as c:  # rebuild: black image skipped, example learned
        data = c.post("/read", content=jpeg, headers=JPEG).json()
        assert data["certain"] is True and 7 in data["missing_templates"]


def test_config_from_environment():
    c = Config.from_env({})
    assert len(c.rois) == 8 and c.min_score == 0.70 and c.min_margin == 0.08
    assert c.max_templates_per_digit == 30 and c.learning is True and c.language == "auto"
    assert Config.from_env({"LEARNING": "false"}).learning is False
    assert Config.from_env({"LEARNING": "0"}).learning is False
    assert Config.from_env({"LEARNING": "On"}).learning is True
    with pytest.raises(ConfigError):
        Config.from_env({"LEARNING": "maybe"})
    c = Config.from_env({"ROIS": "[[1,2,30,40],[1,2,30,40],[1,2,30,40],[1,2,30,40]]", "MIN_SCORE": "0,8"})
    assert c.rois[0] == (1, 2, 30, 40) and c.min_score == 0.8
    for broken in ("no json", "[[1,2,3]]", "[[5,5,1,1]]", "[[1,2,30,40],[1,2,30,40],[5,5,1,1],[1,2,30,40]]"):
        with pytest.raises(ConfigError):
            Config.from_env({"ROIS": broken})
