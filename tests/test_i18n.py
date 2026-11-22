"""English and German: text catalogues, language per request, pages without
leftovers of the other language, translated error messages. The language of log
and sensor (from Home Assistant) is tested in test_auto_reading.py."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import i18n
from app.config import LEGACY_ENV, Config, ConfigError
from app.i18n import TEXTS, T, from_accept_language
from app.main import create_app
from app.migration import LEGACY_OPTIONS

EXAMPLE = Path(__file__).parent / "example.jpg"
JPEG = {"Content-Type": "image/jpeg"}
EN = {"Accept-Language": "en-US,en;q=0.9"}
DE = {"Accept-Language": "de-DE,de;q=0.9,en;q=0.8"}
GERMAN_CHARACTERS = re.compile(r"[äöüÄÖÜß„]")
# German identifiers of version 1.x – they must not show up in any text any more. Options are
# lowercase (German nouns are capitalised), paths and folders carry a slash; "ablesen" or
# "lernen" alone are ordinary German verbs.
LEGACY_NAMES = re.compile(
    r"\b(?:" + "|".join([*LEGACY_ENV.values(), *LEGACY_OPTIONS]) + r")\b"
    r"|/(?:ablesen|lernen|kamera-ablesen)\b|\b(?:lernbilder|vorlagen)/|zaehlerstand|[?&](?:wert|nr|sprache)="
)


def _client(tmp_path, **kwargs) -> TestClient:
    return TestClient(create_app(Config(data_dir=tmp_path, **kwargs)))


# ---- Catalogues -------------------------------------------------------------------


def test_catalogues_have_the_same_keys_and_placeholders():
    en, de = TEXTS["en"], TEXTS["de"]
    assert list(en) == list(de)  # same order: comparable line by line
    for key in en:
        assert re.fullmatch(r"[a-z0-9_.]+", key), key  # keys are English identifiers
        assert en[key].strip() and de[key].strip(), key
        placeholders = [set(re.findall(r"\{(\w+)\}", t[key])) for t in (en, de)]
        assert placeholders[0] == placeholders[1], key
        # HTML only in keys ending in _html – all others are escaped when inserted
        tags = [set(re.findall(r"</?(?:a|b|i|em|strong|br|span|code)\b", t[key])) for t in (en, de)]
        assert tags[0] == tags[1], key
        assert bool(tags[0]) == key.endswith("_html"), key


def test_english_catalogue_is_english():
    german = {k: v for k, v in TEXTS["en"].items() if GERMAN_CHARACTERS.search(v)}
    assert german == {}, german


def test_no_old_german_identifiers_in_any_text():
    for language in i18n.LANGUAGES:
        found = {k: v for k, v in TEXTS[language].items() if LEGACY_NAMES.search(v)}
        assert found == {}, (language, found)


def test_debug_image_title_ascii_only():
    """OpenCV's Hershey fonts cannot draw umlauts."""
    for language in i18n.LANGUAGES:
        assert i18n.translate("debug.title", language, value="506.388", verdict=T("ui.uncertain")).isascii()


@pytest.mark.parametrize(
    "header, expected",
    [
        ("en-US,en;q=0.9", "en"),
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("fr-FR,fr;q=0.9,en;q=0.8,de;q=0.7", "en"),
        ("fr-FR,de;q=0.5,en;q=0.9", "en"),  # by weight, not by order
        ("de_AT", "de"),
        ("en;q=0,de;q=0.1", "de"),  # q=0 means: not wanted
        ("*", None),
        ("", None),
        (None, None),
        ("fr", None),
    ],
)
def test_accept_language(header, expected):
    assert from_accept_language(header) == expected


def test_text_is_translated_only_on_output():
    text = T("api.image_missing", name="x.jpg")
    assert text.in_language("en") == "Training image x.jpg does not exist"
    assert text.in_language("de") == "Lernbild x.jpg gibt es nicht"
    error = ValueError(T("value.too_long", value=1e9, n=8))
    assert "does not fit" in i18n.render(error, "en") and "passt nicht" in i18n.render(error, "de")
    assert i18n.translate("does.not.exist", "en") == "does.not.exist"  # unknown: the key instead of a crash


# ---- Web pages -------------------------------------------------------------------


def test_training_page_english_without_german_leftovers(tmp_path):
    with _client(tmp_path) as c:
        empty = c.get("/", headers=EN).text
        assert '<html lang="en">' in empty and "No image read yet." in empty
        c.post("/read", content=EXAMPLE.read_bytes(), headers=JPEG)
        page = c.get("/", headers=EN).text
        assert "Learn from this image" in page and '"format": "Please enter in the format 506.388."' in page
        assert ">Training</a>" in page and ">Admin</a>" in page
        for html in (empty, page):
            assert not GERMAN_CHARACTERS.search(html), GERMAN_CHARACTERS.findall(html)
            assert not LEGACY_NAMES.search(html), LEGACY_NAMES.findall(html)
        assert c.get("/debug.png?reading=1", headers=EN).status_code == 200


def test_admin_page_english_without_german_leftovers(tmp_path):
    with _client(tmp_path) as c:
        page = c.get("/admin", headers=EN).text
    assert '<html lang="en">' in page and "<title>Wasseruhr-CV · Admin</title>" in page
    assert "Back up &amp; transfer" in page and '"status.accepted": "accepted"' in page
    assert not GERMAN_CHARACTERS.search(page), GERMAN_CHARACTERS.findall(page)
    assert not LEGACY_NAMES.search(page), LEGACY_NAMES.findall(page)


def test_german_via_accept_language(tmp_path):
    with _client(tmp_path) as c:
        assert "Noch kein Bild abgelesen." in c.get("/", headers=DE).text
        page = c.get("/admin", headers=DE).text
        assert "Sichern &amp; übertragen" in page and '"status.accepted": "übernommen"' in page
        assert not LEGACY_NAMES.search(page), LEGACY_NAMES.findall(page)


def test_without_accept_language_the_service_language_applies(tmp_path):
    with _client(tmp_path) as c:  # auto, without Home Assistant: English
        assert '<html lang="en">' in c.get("/").text
    with _client(tmp_path, language="de") as c:
        assert '<html lang="de">' in c.get("/").text


def test_switch_remembers_the_choice(tmp_path):
    with _client(tmp_path) as c:
        response = c.get("/?lang=en", headers=DE)
        assert '<html lang="en">' in response.text
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{i18n.COOKIE}=en;") and "HttpOnly" in cookie
        assert "Path=" not in cookie  # behind the ingress only for this add-on
        # afterwards without a parameter: the cookie beats the browser language and the option
        assert '<html lang="en">' in c.get("/admin", headers=DE).text
        assert c.post("/learn?value=abc", content=b"x", headers={**JPEG, **DE}).json()["detail"].startswith("Invalid")
        c.get("/?lang=de")
        assert '<html lang="de">' in c.get("/", headers=EN).text


def test_switch_of_version_1_5_still_works(tmp_path):
    with _client(tmp_path) as c:
        assert '<html lang="de">' in c.get("/?sprache=de", headers=EN).text
        c.cookies.clear()
        c.cookies.set(i18n.LEGACY_COOKIE, "de")
        assert '<html lang="de">' in c.get("/", headers=EN).text


def test_switch_keeps_the_reading(tmp_path):
    with _client(tmp_path) as c:
        c.post("/read", content=EXAMPLE.read_bytes(), headers=JPEG)
        page = c.get("/?reading=1", headers=EN).text
    assert 'href="?reading=1&lang=de"' in page and 'href="?reading=1&lang=en"' in page
    assert 'aria-current="true">EN<' in page


def test_option_language_beats_the_browser(tmp_path):
    with _client(tmp_path, language="de") as c:
        assert '<html lang="de">' in c.get("/", headers=EN).text
        assert '<html lang="en">' in c.get("/?lang=en", headers=EN).text  # a deliberate choice still wins


# ---- API messages --------------------------------------------------------------------


def test_error_messages_in_the_language_of_the_request(tmp_path):
    with _client(tmp_path, admin_ingress_only=True) as c:
        for header, expected in ((EN, "Invalid value 'abc'"), (DE, "Ungültiger Wert 'abc'")):
            assert c.post("/learn?value=abc", content=b"x", headers={**JPEG, **header}).json()["detail"].startswith(expected)
        assert c.post("/read", content=b"no image", headers={**JPEG, **EN}).json()["detail"] == (
            "Body is not a readable image – raw JPEG expected"
        )
        foreign = c.post("/learn?value=1", headers={**DE, "Origin": "http://evil.example"})
        assert foreign.status_code == 403 and foreign.json()["detail"] == "Anfrage von fremder Webseite abgelehnt"
        admin = c.get("/admin/info", headers=EN)
        assert admin.status_code == 403 and "only available through Home Assistant" in admin.json()["detail"]
        assert c.get("/debug.png?reading=7", headers=EN).json()["detail"] == "Reading #7 is no longer in memory"
        # FastAPI's own checks (422) stay unchanged
        assert c.post("/learn", content=b"x", headers={**JPEG, **EN}).status_code == 422


def test_roi_error_german(tmp_path):
    rois = ((0, 0, 20, 20),) * 7 + ((600, 400, 700, 500),)
    with _client(tmp_path, rois=rois) as c:
        detail = c.post("/read", content=EXAMPLE.read_bytes(), headers={**JPEG, **DE}).json()["detail"]
    assert detail == "ROI der Rolle 8 [600, 400, 700, 500] liegt außerhalb des Bildes (640x480) – ROIS anpassen"


# ---- Configuration ------------------------------------------------------------------


def test_config_language():
    assert Config.from_env({}).language == "auto"
    assert Config.from_env({"LANGUAGE": " EN "}).language == "en"
    assert Config.from_env({"LANGUAGE": "de_DE.UTF-8"}).language == "de"
    assert Config.from_env({"LANGUAGE": "en_US:en"}).language == "en"  # gettext notation
    assert Config.from_env({"LANGUAGE": "C.UTF-8"}).language == "auto"
    with pytest.raises(ConfigError) as error:
        Config.from_env({"LANGUAGE": "fr"})
    assert i18n.render(error.value, "en") == "LANGUAGE='fr': expected auto, en or de"
    assert i18n.render(error.value, "de") == "LANGUAGE='fr': erwartet auto, en oder de"


def test_config_switch_values():
    c = Config.from_env({"LEARNING": "false", "HTTP": "on", "SENSOR": "off", "INPUT_NUMBER": "none"})
    assert c.learning is False and c.http is True and c.sensor is None and c.input_number is None
    with pytest.raises(ConfigError) as error:
        Config.from_env({"SHIFT": "11"})
    assert i18n.render(error.value, "en") == "SHIFT must be between 0 and 10"
