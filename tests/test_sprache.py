"""Zweisprachigkeit: Textkataloge, Sprachwahl je Anfrage, englische Oberfläche,
übersetzte Fehlermeldungen. Die Sprache von Protokoll und Sensor (aus Home
Assistant) prüft test_automatik.py."""

import io
import re
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import sprache
from app.konfig import Konfig, KonfigFehler
from app.main import create_app
from app.sprache import TEXTE, T, aus_accept_language

BEISPIEL = Path(__file__).parent / "beispiel.jpg"
JPEG = {"Content-Type": "image/jpeg"}
EN = {"Accept-Language": "en-US,en;q=0.9"}
DE = {"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
DEUTSCHE_ZEICHEN = re.compile(r"[äöüÄÖÜß„]")


def _client(tmp_path, **kwargs) -> TestClient:
    return TestClient(create_app(Konfig(daten_verzeichnis=tmp_path, **kwargs)))


# ---- Kataloge -------------------------------------------------------------------


def test_kataloge_haben_dieselben_schluessel_und_platzhalter():
    de, en = TEXTE["de"], TEXTE["en"]
    assert list(de) == list(en)  # gleiche Reihenfolge: Zeile für Zeile vergleichbar
    for schluessel in de:
        assert de[schluessel].strip() and en[schluessel].strip(), schluessel
        platzhalter = [set(re.findall(r"\{(\w+)\}", t[schluessel])) for t in (de, en)]
        assert platzhalter[0] == platzhalter[1], schluessel
        # HTML nur in Schlüsseln auf _html – alle anderen werden beim Einsetzen escaped
        tags = [set(re.findall(r"</?(?:a|b|i|em|strong|br|span|code)\b", t[schluessel])) for t in (de, en)]
        assert tags[0] == tags[1], schluessel
        assert bool(tags[0]) == schluessel.endswith("_html"), schluessel


def test_englischer_katalog_ist_englisch():
    deutsch = {k: v for k, v in TEXTE["en"].items() if DEUTSCHE_ZEICHEN.search(v)}
    assert deutsch == {}, deutsch


def test_debugbild_titel_nur_ascii():
    """Die Hershey-Schriften von OpenCV können keine Umlaute."""
    for s in sprache.SPRACHEN:
        assert sprache.uebersetzen("debug.titel", s, wert="506.388", urteil=T("ui.unsicher")).isascii()


@pytest.mark.parametrize(
    "kopf, erwartet",
    [
        ("en-US,en;q=0.9", "en"),
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("fr-FR,fr;q=0.9,en;q=0.8,de;q=0.7", "en"),
        ("fr-FR,de;q=0.5,en;q=0.9", "en"),  # nach Gewicht, nicht nach Reihenfolge
        ("de_AT", "de"),
        ("en;q=0,de;q=0.1", "de"),  # q=0 heißt: nicht gewünscht
        ("*", None),
        ("", None),
        (None, None),
        ("fr", None),
    ],
)
def test_accept_language(kopf, erwartet):
    assert aus_accept_language(kopf) == erwartet


def test_text_wird_erst_bei_der_ausgabe_uebersetzt():
    text = T("api.lernbild_fehlt", name="x.jpg")
    assert text.in_sprache("de") == "Lernbild x.jpg gibt es nicht"
    assert text.in_sprache("en") == "Training image x.jpg does not exist"
    fehler = ValueError(T("wert.zu_lang", wert=1e9, n=8))
    assert "passt nicht" in sprache.ausgeben(fehler, "de") and "does not fit" in sprache.ausgeben(fehler, "en")
    assert sprache.uebersetzen("gibt.es.nicht", "en") == "gibt.es.nicht"  # unbekannt: Schlüssel statt Absturz


# ---- Webseiten ------------------------------------------------------------------


def test_lernseite_englisch_ohne_deutsche_reste(tmp_path):
    with _client(tmp_path) as c:
        leer = c.get("/", headers=EN).text
        assert '<html lang="en">' in leer and "No image read yet." in leer
        c.post("/ablesen", content=BEISPIEL.read_bytes(), headers=JPEG)
        seite = c.get("/", headers=EN).text
        assert "Learn from this image" in seite and '"format": "Please enter in the format 506.388."' in seite
        assert ">Training</a>" in seite and ">Admin</a>" in seite
        for html in (leer, seite):
            assert not DEUTSCHE_ZEICHEN.search(html), DEUTSCHE_ZEICHEN.findall(html)
        assert c.get("/debug.png?nr=1", headers=EN).status_code == 200


def test_verwaltung_englisch_ohne_deutsche_reste(tmp_path):
    with _client(tmp_path) as c:
        seite = c.get("/admin", headers=EN).text
    assert '<html lang="en">' in seite and "<title>Wasseruhr-CV · Admin</title>" in seite
    assert "Back up &amp; transfer" in seite and '"status.accepted": "accepted"' in seite
    assert not DEUTSCHE_ZEICHEN.search(seite), DEUTSCHE_ZEICHEN.findall(seite)


def test_deutsch_ueber_accept_language(tmp_path):
    with _client(tmp_path) as c:
        assert "Noch kein Bild abgelesen." in c.get("/", headers=DE).text
        assert "Sichern &amp; übertragen" in c.get("/admin", headers=DE).text


def test_ohne_accept_language_gilt_die_sprache_des_dienstes(tmp_path):
    with _client(tmp_path) as c:  # auto, ohne Home Assistant: Englisch
        assert '<html lang="en">' in c.get("/").text
    with _client(tmp_path, sprache="de") as c:
        assert '<html lang="de">' in c.get("/").text


def test_umschalter_merkt_sich_die_wahl(tmp_path):
    with _client(tmp_path) as c:
        antwort = c.get("/?sprache=en", headers=DE)
        assert '<html lang="en">' in antwort.text
        cookie = antwort.headers["set-cookie"]
        assert cookie.startswith(f"{sprache.COOKIE}=en;") and "HttpOnly" in cookie
        assert "Path=" not in cookie  # hinter dem Ingress nur für dieses Add-on
        # danach ohne Parameter: Cookie schlägt Browser-Sprache und Option
        assert '<html lang="en">' in c.get("/admin", headers=DE).text
        assert c.post("/lernen?wert=abc", content=b"x", headers={**JPEG, **DE}).json()["detail"].startswith("Invalid")
        c.get("/?sprache=de")
        assert '<html lang="de">' in c.get("/", headers=EN).text


def test_umschalter_behaelt_die_ablesung(tmp_path):
    with _client(tmp_path) as c:
        c.post("/ablesen", content=BEISPIEL.read_bytes(), headers=JPEG)
        seite = c.get("/?nr=1", headers=EN).text
    assert 'href="?nr=1&sprache=de"' in seite and 'href="?nr=1&sprache=en"' in seite
    assert 'aria-current="true">EN<' in seite


def test_option_sprache_schlaegt_browser(tmp_path):
    with _client(tmp_path, sprache="de") as c:
        assert '<html lang="de">' in c.get("/", headers=EN).text
        assert '<html lang="en">' in c.get("/?sprache=en", headers=EN).text  # bewusste Wahl gilt trotzdem


# ---- Meldungen der API --------------------------------------------------------------


def test_fehlermeldungen_in_der_sprache_der_anfrage(tmp_path):
    with _client(tmp_path, admin_nur_ingress=True) as c:
        for kopf, erwartet in ((EN, "Invalid wert='abc'"), (DE, "Ungültiger wert='abc'")):
            assert c.post("/lernen?wert=abc", content=b"x", headers={**JPEG, **kopf}).json()["detail"].startswith(erwartet)
        assert c.post("/ablesen", content=b"kein bild", headers={**JPEG, **EN}).json()["detail"] == (
            "Body is not a readable image – raw JPEG expected"
        )
        fremd = c.post("/lernen?wert=1", headers={**EN, "Origin": "http://boese.example"})
        assert fremd.status_code == 403 and fremd.json()["detail"] == "Request from a foreign website rejected"
        admin = c.get("/admin/info", headers=EN)
        assert admin.status_code == 403 and "only available through Home Assistant" in admin.json()["detail"]
        assert c.get("/debug.png?nr=7", headers=EN).json()["detail"] == "Reading #7 is no longer in memory"
        # FastAPI-eigene Prüfungen (422) bleiben unverändert
        assert c.post("/lernen", content=b"x", headers={**JPEG, **EN}).status_code == 422


def test_roi_fehler_englisch(tmp_path):
    rois = ((0, 0, 20, 20),) * 7 + ((600, 400, 700, 500),)
    with _client(tmp_path, rois=rois) as c:
        detail = c.post("/ablesen", content=BEISPIEL.read_bytes(), headers={**JPEG, **EN}).json()["detail"]
    assert detail == "ROI of wheel 8 [600, 400, 700, 500] is outside the image (640x480) – adjust ROIS"


def test_import_englische_modi_und_meldungen(tmp_path):
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("lernbilder/20260101T000000000000Z_506.388.jpg", BEISPIEL.read_bytes())
    with _client(tmp_path) as c:
        d = c.post("/admin/import?modus=replace", content=puffer.getvalue()).json()
        assert d["modus"] == "ersetzen" and d["lernbilder_neu"] == 1
        assert c.post("/admin/import?modus=merge", content=puffer.getvalue()).json()["modus"] == "ergaenzen"
        leer = c.post("/admin/import?modus=merge", content=b"", headers=EN).json()["detail"]
        assert leer == "Empty request body – ZIP file expected"
        assert 'filename="wasseruhr-model-' in c.get("/admin/export.zip", headers=EN).headers["content-disposition"]


# ---- Konfiguration ------------------------------------------------------------------


def test_konfig_sprache():
    assert Konfig.aus_umgebung({}).sprache == "auto"
    assert Konfig.aus_umgebung({"SPRACHE": " EN "}).sprache == "en"
    assert Konfig.aus_umgebung({"SPRACHE": "de"}).sprache == "de"
    with pytest.raises(KonfigFehler) as fehler:
        Konfig.aus_umgebung({"SPRACHE": "fr"})
    assert sprache.ausgeben(fehler.value, "en") == "SPRACHE='fr': expected auto, de or en"
    assert sprache.ausgeben(fehler.value, "de") == "SPRACHE='fr': erwartet auto, de oder en"


def test_konfig_englische_werte():
    k = Konfig.aus_umgebung({"LERNEFFEKT": "off", "HTTP": "on", "SENSOR": "off", "INPUT_NUMBER": "none"})
    assert k.lerneffekt is False and k.http is True and k.sensor is None and k.input_number is None
    with pytest.raises(KonfigFehler) as fehler:
        Konfig.aus_umgebung({"VERSCHIEBUNG": "11"})
    assert sprache.ausgeben(fehler.value, "en") == "VERSCHIEBUNG must be between 0 and 10"
