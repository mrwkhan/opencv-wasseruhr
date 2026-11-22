from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.erkennung import zerlege_wert, zusammensetzen, ZiffernErgebnis
from app.konfig import Konfig, KonfigFehler
from app.main import create_app
from app.vorlagen import VorlagenSpeicher

BEISPIEL = Path(__file__).parent / "beispiel.jpg"
BEISPIEL_WERT = "506.388"
JPEG = {"Content-Type": "image/jpeg"}


@pytest.fixture
def jpeg() -> bytes:
    return BEISPIEL.read_bytes()


def _client(tmp_path: Path, **kwargs) -> TestClient:
    return TestClient(create_app(Konfig(daten_verzeichnis=tmp_path, **kwargs)))


@pytest.fixture
def client(tmp_path):
    with _client(tmp_path) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_ohne_vorlagen_unsicher(client, jpeg):
    antwort = client.post("/ablesen", content=jpeg, headers=JPEG)
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["wert"] is None
    assert daten["sicher"] is False
    assert daten["fehlende_vorlagen"] == list(range(10))
    assert [z["rolle"] for z in daten["ziffern"]] == list(range(1, 9))
    assert all(z["ziffer"] is None for z in daten["ziffern"])


def test_lernen_dann_ablesen_sicher(client, jpeg, tmp_path):
    antwort = client.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    assert antwort.status_code == 200, antwort.text
    gelernt = antwort.json()
    assert 5 <= gelernt["gespeichert"] <= 8
    pro_ziffer = gelernt["vorlagen_pro_ziffer"]
    assert set(pro_ziffer) == {str(z) for z in range(10)}
    for z in "03568":
        assert pro_ziffer[z] >= 1
    for z in "12479":
        assert pro_ziffer[z] == 0
    assert sum(pro_ziffer.values()) == gelernt["gespeichert"]

    # Dateiablage: /data/vorlagen/<ziffer>/<zeitstempel>_r<rolle>.png
    dateien = sorted(tmp_path.glob("vorlagen/*/*.png"))
    assert len(dateien) == gelernt["gespeichert"]
    for d in dateien:
        assert d.stem.rsplit("_r", 1)[1] in {str(r) for r in range(1, 9)}
        assert cv2.imread(str(d), cv2.IMREAD_GRAYSCALE).shape == (40, 24)
    assert {d.name for d in (tmp_path / "vorlagen" / "5").iterdir()} and all(
        d.name.endswith("_r3.png") for d in (tmp_path / "vorlagen" / "5").iterdir()
    )

    daten = client.post("/ablesen", content=jpeg, headers=JPEG).json()
    assert daten["sicher"] is True, daten
    assert daten["wert"] == 506.388
    assert [z["ziffer"] for z in daten["ziffern"]] == [0, 0, 5, 0, 6, 3, 8, 8]
    assert daten["fehlende_vorlagen"] == [1, 2, 4, 7, 9]
    for z in daten["ziffern"]:
        assert set(z) == {"rolle", "ziffer", "score", "zweitbeste", "score2"}
        assert z["score"] >= 0.70
        assert z["score"] - z["score2"] >= 0.08


def test_lernen_ignoriert_duplikate(client, jpeg):
    erstes = client.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG).json()
    zweites = client.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG).json()
    assert zweites["gespeichert"] == 0
    assert zweites["vorlagen_pro_ziffer"] == erstes["vorlagen_pro_ziffer"]


def test_status(client, jpeg):
    leer = client.get("/status").json()
    assert leer["vorlagen_pro_ziffer"] == {str(z): 0 for z in range(10)}
    client.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    status = client.get("/status").json()
    assert status["vorlagen_pro_ziffer"]["5"] == 1
    assert status["fehlende_vorlagen"] == [1, 2, 4, 7, 9]


def test_vorlagen_ueberleben_neustart(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
        vorher = c.get("/status").json()
    with _client(tmp_path) as c:
        assert c.get("/status").json() == vorher
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True


# ---- Lernbild-Archiv & Lerneffekt -------------------------------------------


def _vorlagen_dateien(tmp_path: Path) -> list[str]:
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.glob("vorlagen/*/*.png"))


def test_lernen_archiviert_jedes_bild(client, jpeg, tmp_path):
    client.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    client.post("/lernen?wert=506,388", content=jpeg, headers=JPEG)  # Duplikat, trotzdem archiviert
    archiv = sorted((tmp_path / "lernbilder").iterdir())
    assert len(archiv) == 2
    for datei in archiv:
        assert datei.name.endswith("_506.388.jpg")
        assert datei.read_bytes() == jpeg  # byte-genau
    assert client.get("/status").json()["lernbilder"] == 2


def test_ungueltige_bilder_werden_nicht_archiviert(client, tmp_path):
    client.post(f"/lernen?wert={BEISPIEL_WERT}", content=b"kein bild", headers=JPEG)
    client.post("/lernen?wert=abc", content=b"kein bild", headers=JPEG)
    assert not (tmp_path / "lernbilder").exists() or not any((tmp_path / "lernbilder").iterdir())


def test_ohne_lerneffekt_nur_archivieren(tmp_path, jpeg):
    with _client(tmp_path, lerneffekt=False) as c:
        antwort = c.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG).json()
        assert antwort["gespeichert"] == 0
        assert antwort["vorlagen_pro_ziffer"] == {str(z): 0 for z in range(10)}
        status = c.get("/status").json()
        assert status["lerneffekt"] is False and status["lernbilder"] == 1
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["wert"] is None
    assert _vorlagen_dateien(tmp_path) == []

    # Neustart MIT Lerneffekt lernt die gesammelten Bilder nach
    with _client(tmp_path) as c:
        daten = c.post("/ablesen", content=jpeg, headers=JPEG).json()
        assert daten["sicher"] is True and daten["wert"] == 506.388


def test_ohne_lerneffekt_vorlagen_eingefroren(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    vorher = _vorlagen_dateien(tmp_path)
    fremd = tmp_path / "vorlagen" / "7" / "manuell.png"
    fremd.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(fremd), np.random.default_rng(1).integers(0, 256, (40, 24), dtype=np.uint8))

    with _client(tmp_path, lerneffekt=False) as c:
        assert c.get("/status").json()["vorlagen_pro_ziffer"]["7"] == 1  # nichts neu aufgebaut
        c.post("/lernen?wert=506.393", content=jpeg, headers=JPEG)
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True
    assert _vorlagen_dateien(tmp_path) == sorted(vorher + ["vorlagen/7/manuell.png"])


def test_neustart_mit_lerneffekt_baut_vorlagen_identisch_neu_auf(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    live = _vorlagen_dateien(tmp_path)
    # Datei, die nicht aus dem Archiv stammt, verschwindet beim Neuaufbau
    (tmp_path / "vorlagen" / "7").mkdir(exist_ok=True)
    rauschen = np.random.default_rng(1).integers(0, 256, (40, 24), dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "vorlagen" / "7" / "manuell.png"), rauschen)
    with _client(tmp_path) as c:
        assert c.get("/status").json()["vorlagen_pro_ziffer"]["7"] == 0
    assert _vorlagen_dateien(tmp_path) == live


def test_neuaufbau_nutzt_aktuelle_rois(tmp_path, jpeg):
    with _client(tmp_path) as c:
        c.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    alt = cv2.imread(str(next((tmp_path / "vorlagen" / "5").iterdir())), cv2.IMREAD_GRAYSCALE)
    verschoben = tuple((x1, y1 + 4, x2, y2 + 4) for x1, y1, x2, y2 in Konfig().rois)
    with _client(tmp_path, rois=verschoben) as c:
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True
    neu = cv2.imread(str(next((tmp_path / "vorlagen" / "5").iterdir())), cv2.IMREAD_GRAYSCALE)
    assert not np.array_equal(alt, neu)


def test_neuaufbau_ueberspringt_kaputte_lernbilder(tmp_path, jpeg):
    archiv = tmp_path / "lernbilder"
    archiv.mkdir()
    (archiv / "20260101T000000000000Z_506.388.jpg").write_bytes(b"kaputt")
    (archiv / "falscher_name.jpg").write_bytes(jpeg)
    (archiv / "20260101T000000000001Z_506.388.jpg").write_bytes(jpeg)
    with _client(tmp_path) as c:
        assert c.post("/ablesen", content=jpeg, headers=JPEG).json()["sicher"] is True


@pytest.mark.parametrize("wert", ["abc", "-1", "100000", "nan", ""])
def test_lernen_ungueltiger_wert(client, jpeg, wert):
    assert client.post(f"/lernen?wert={wert}", content=jpeg, headers=JPEG).status_code == 400


def test_lernen_ohne_wert(client, jpeg):
    assert client.post("/lernen", content=jpeg, headers=JPEG).status_code == 422


@pytest.mark.parametrize("pfad", ["/ablesen", f"/lernen?wert={BEISPIEL_WERT}"])
def test_kein_jpeg(client, pfad):
    assert client.post(pfad, content=b"", headers=JPEG).status_code == 400
    assert client.post(pfad, content=b"kein bild", headers=JPEG).status_code == 400


def test_roi_ausserhalb_des_bildes(tmp_path, jpeg):
    rois = ((0, 0, 20, 20),) * 7 + ((600, 400, 700, 500),)
    with _client(tmp_path, rois=rois) as c:
        antwort = c.post("/ablesen", content=jpeg, headers=JPEG)
    assert antwort.status_code == 400
    assert "Rolle 8" in antwort.json()["detail"]


def test_debug_png(client, jpeg):
    assert client.get("/debug.png?letztes=1").status_code == 404
    client.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    client.post("/ablesen", content=jpeg, headers=JPEG)
    antwort = client.get("/debug.png?letztes=1")
    assert antwort.status_code == 200
    assert antwort.headers["content-type"] == "image/png"
    bild = cv2.imdecode(np.frombuffer(antwort.content, np.uint8), cv2.IMREAD_COLOR)
    original = cv2.imread(str(BEISPIEL))
    assert bild.shape[1] >= original.shape[1]
    assert bild.shape[0] > original.shape[0] + 120  # Ziffern-Streifen unter dem Bild


# ---- Lernseite & Lernen aus dem Verlauf -------------------------------------

ANDERES_BILD = Path(__file__).parent / "anderes.jpg"  # Stand 506.614


def test_lernseite_ohne_ablesung(client):
    antwort = client.get("/")
    assert antwort.status_code == 200
    assert "text/html" in antwort.headers["content-type"]
    assert "Noch kein Bild" in antwort.text


def test_lernseite_zeigt_letzte_ablesung(client, jpeg):
    client.post("/ablesen", content=jpeg, headers=JPEG)
    seite = client.get("/").text
    assert 'src="debug.png?nr=1"' in seite
    assert 'data-nr="1"' in seite
    assert "Ziffern ohne Vorlage: 0, 1, 2" in seite


def test_lernen_aus_ablesung_ohne_body(client, jpeg, tmp_path):
    client.post("/ablesen", content=jpeg, headers=JPEG)  # Ablesung #1
    antwort = client.post(f"/lernen?wert={BEISPIEL_WERT}&ablesung=1")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["gespeichert"] >= 5
    assert next((tmp_path / "lernbilder").iterdir()).read_bytes() == jpeg
    # gleiches Bild wurde direkt neu abgelesen (#2) und ist jetzt sicher
    assert client.get("/debug.png?nr=2").status_code == 200
    assert "sicher</span>" in client.get("/?nr=2").text and "unsicher" not in client.get("/?nr=2").text


def test_lernen_nimmt_genau_das_gezeigte_bild(client, jpeg, tmp_path):
    client.post("/ablesen", content=jpeg, headers=JPEG)                      # #1: 506.388
    client.post("/ablesen", content=ANDERES_BILD.read_bytes(), headers=JPEG)  # #2: neuer Abruf
    assert "neuere Ablesung" in client.get("/?nr=1").text
    client.post(f"/lernen?wert={BEISPIEL_WERT}&ablesung=1")
    assert next((tmp_path / "lernbilder").iterdir()).read_bytes() == jpeg


def test_lernen_aus_unbekannter_ablesung(client):
    assert client.post(f"/lernen?wert={BEISPIEL_WERT}&ablesung=99").status_code == 404
    assert client.get("/debug.png?nr=99").status_code == 404


# ---- Einheitstests ----------------------------------------------------------


def test_zerlege_wert():
    assert zerlege_wert(506.388, 8, 3) == [0, 0, 5, 0, 6, 3, 8, 8]
    assert zerlege_wert(0, 8, 3) == [0] * 8
    assert zerlege_wert(99999.999, 8, 3) == [9] * 8
    with pytest.raises(ValueError):
        zerlege_wert(100000, 8, 3)


def test_zusammensetzen():
    erg = [ZiffernErgebnis(i + 1, z, 1.0, None, None) for i, z in enumerate([0, 0, 5, 0, 6, 3, 8, 8])]
    assert zusammensetzen(erg, 3) == 506.388
    erg[2].ziffer = None
    assert zusammensetzen(erg, 3) is None


def test_max_vorlagen_pro_ziffer(tmp_path):
    speicher = VorlagenSpeicher(tmp_path, max_pro_ziffer=3)
    rng = np.random.default_rng(0)
    for i in range(5):
        bild = rng.integers(0, 256, (40, 24), dtype=np.uint8)  # zufällig -> nie Duplikat
        assert speicher.lernen(f"20260101T000000{i:06d}Z", [7], [bild]) == 1
    dateien = sorted((tmp_path / "7").glob("*.png"))
    assert len(dateien) == 3
    assert speicher.anzahl_pro_ziffer()["7"] == 3
    # Die zuletzt gelernte Vorlage muss erhalten bleiben
    gespeichert = cv2.imread(str(dateien[-1]), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(gespeichert, bild)


def test_kontrastlose_vorlagen_werden_weder_gelernt_noch_geladen(tmp_path, jpeg):
    # Ein schwarzes Kamerabild darf keine Vorlagen erzeugen ...
    schwarz = cv2.imencode(".jpg", np.zeros((480, 640, 3), np.uint8))[1].tobytes()
    with _client(tmp_path) as c:
        antwort = c.post(f"/lernen?wert={BEISPIEL_WERT}", content=schwarz, headers=JPEG).json()
        assert antwort["gespeichert"] == 0
    # ... und eine von Hand abgelegte konstante Vorlage wird beim Laden ignoriert
    ordner = tmp_path / "vorlagen" / "7"
    ordner.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ordner / "manuell.png"), np.zeros((40, 24), np.uint8))
    with _client(tmp_path, lerneffekt=False) as c:
        c.post(f"/lernen?wert={BEISPIEL_WERT}", content=jpeg, headers=JPEG)
    with _client(tmp_path) as c:  # Neuaufbau: schwarzes Bild übersprungen, Beispiel gelernt
        daten = c.post("/ablesen", content=jpeg, headers=JPEG).json()
        assert daten["sicher"] is True and 7 in daten["fehlende_vorlagen"]


def test_konfig_aus_umgebung():
    k = Konfig.aus_umgebung({})
    assert len(k.rois) == 8 and k.min_score == 0.70 and k.min_abstand == 0.08
    assert k.max_vorlagen_pro_ziffer == 30
    assert k.lerneffekt is True
    assert Konfig.aus_umgebung({"LERNEFFEKT": "aus"}).lerneffekt is False
    assert Konfig.aus_umgebung({"LERNEFFEKT": "0"}).lerneffekt is False
    assert Konfig.aus_umgebung({"LERNEFFEKT": "An"}).lerneffekt is True
    with pytest.raises(KonfigFehler):
        Konfig.aus_umgebung({"LERNEFFEKT": "vielleicht"})
    k = Konfig.aus_umgebung({"ROIS": "[[1,2,30,40],[1,2,30,40],[1,2,30,40],[1,2,30,40]]", "MIN_SCORE": "0,8"})
    assert k.rois[0] == (1, 2, 30, 40) and k.min_score == 0.8
    for kaputt in ("kein json", "[[1,2,3]]", "[[5,5,1,1]]", "[[1,2,30,40],[1,2,30,40],[5,5,1,1],[1,2,30,40]]"):
        with pytest.raises(KonfigFehler):
            Konfig.aus_umgebung({"ROIS": kaputt})
