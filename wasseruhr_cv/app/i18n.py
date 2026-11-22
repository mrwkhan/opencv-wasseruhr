"""Internationalisation: English and German for pages, messages, log and sensor.

Every text lives under the same key in app/texts/en.json and app/texts/de.json.
Placeholders are written {name} and are replaced the same way in Python and in
the browser. A Text is only rendered when it is output, so the same message can
appear in the log in the service language and in the browser in the user's
language.

Which language applies:
- Web pages and API messages, per request: the switch on the page
  (?lang=en|de, remembered in a cookie) → option LANGUAGE → the browser's
  Accept-Language → the service language.
- Log and sensor (service language): option LANGUAGE; with "auto" the language
  of Home Assistant, without Home Assistant English.

Keys starting with "ui." are also handed to the page scripts. Keys ending in
"_html" are inserted into HTML without escaping.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

LANGUAGES = ("en", "de")
DEFAULT = "en"  # when nothing else is known
AUTO = "auto"
QUERY = "lang"
COOKIE = "wasseruhr_lang"
COOKIE_SECONDS = 365 * 24 * 3600
LEGACY_QUERY, LEGACY_COOKIE = "sprache", "wasseruhr_sprache"  # version 1.5
BROWSER_PREFIX = "ui."

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
TEXTS: dict[str, dict[str, str]] = {
    language: json.loads((Path(__file__).with_name("texts") / f"{language}.json").read_text(encoding="utf-8"))
    for language in LANGUAGES
}

# Service language (log, sensor). source: option | home_assistant | default
_state = SimpleNamespace(fixed=None, service=DEFAULT, known=False, source="default", asked=False)


def configure(choice: str) -> None:
    """Apply the option LANGUAGE: 'en'/'de' fixed, anything else automatic."""
    fixed = choice in LANGUAGES
    _state.fixed = choice if fixed else None
    _state.service = choice if fixed else DEFAULT
    _state.known = fixed
    _state.source = "option" if fixed else "default"
    _state.asked = False


def service_language() -> str:
    """Language of the log and the sensor."""
    return _state.service


def source() -> str:
    return _state.source


def pending() -> bool:
    """True with LANGUAGE=auto as long as the language of Home Assistant is unknown."""
    return not _state.known


def asked(remember: bool = False) -> bool:
    """Has Home Assistant been asked for its language since configure()?
    (At start-up ask only once, even if it cannot be reached.)"""
    if remember:
        _state.asked = True
    return _state.asked


def from_home_assistant(code: str | None) -> str:
    """Take over the language of Home Assistant's configuration (only with auto)."""
    if _state.fixed is None:
        _state.service = from_code(code) or DEFAULT
        _state.known, _state.source = True, "home_assistant"
    return _state.service


def from_code(code: str | None) -> str | None:
    """'de-DE', 'de_AT.UTF-8', 'EN' -> 'de'/'en'; unsupported -> None."""
    if not code:
        return None
    base = re.split(r"[-_.]", code.strip(), maxsplit=1)[0].lower()
    return base if base in LANGUAGES else None


def from_accept_language(header: str | None) -> str | None:
    """First supported language of e.g. 'fr-FR,fr;q=0.9,en;q=0.8' (by weight q)."""
    if not header:
        return None
    candidates = []
    for position, part in enumerate(header.split(",")):
        code, *parameters = (p.strip() for p in part.split(";"))
        weight = 1.0
        for parameter in parameters:
            name, _, value = parameter.partition("=")
            if name.strip() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        if weight > 0:
            candidates.append((-weight, position, code))
    for _, _, code in sorted(candidates):
        if found := from_code(code):
            return found
    return None


def for_request(request) -> str:
    """Language of the answer to a request (page, image, error message)."""
    for choice in (
        request.query_params.get(QUERY), request.query_params.get(LEGACY_QUERY),
        request.cookies.get(COOKIE), request.cookies.get(LEGACY_COOKIE),
    ):
        if choice in LANGUAGES:
            return choice
    config = getattr(request.app.state, "config", None)
    if getattr(config, "language", None) in LANGUAGES:
        return config.language
    return from_accept_language(request.headers.get("accept-language")) or service_language()


# ---- Texts ---------------------------------------------------------------------


def translate(key: str, language: str | None = None, /, **values) -> str:
    """Text in the language (default: service language) with its placeholders filled in."""
    language = language if language in LANGUAGES else service_language()
    text = TEXTS[language].get(key)
    if text is None:
        text = TEXTS[DEFAULT].get(key, key)
    if not values:
        return text
    return _PLACEHOLDER.sub(
        lambda m: _as_text(values[m.group(1)], language) if m.group(1) in values else m.group(0), text
    )


class Text:
    """Translatable text: key and values, rendered in a language only on output.

    Used as the message of exceptions, log records and HTTP errors; str() gives
    the service language, in_language() a specific one."""

    __slots__ = ("key", "values")

    def __init__(self, key: str, /, **values):
        self.key = key
        self.values = values

    def in_language(self, language: str | None = None) -> str:
        return translate(self.key, language, **self.values)

    def __str__(self) -> str:
        return self.in_language()

    def __repr__(self) -> str:
        return f"Text({self.key!r}, {self.values!r})"


T = Text


def message(error: BaseException) -> Text | str:
    """Message of an exception – translatable if it was raised with a Text."""
    if error.args and isinstance(error.args[0], Text):
        return error.args[0]
    return str(error)


def _as_text(value, language: str) -> str:
    if isinstance(value, Text):
        return value.in_language(language)
    if isinstance(value, BaseException):
        return _as_text(message(value), language)
    if isinstance(value, (list, tuple)):
        return "; ".join(_as_text(v, language) for v in value)
    return str(value)


def render(value, language: str | None = None):
    """Text, exception or a list of them -> str in the language; anything else unchanged."""
    if isinstance(value, (Text, BaseException, list, tuple)):
        return _as_text(value, language if language in LANGUAGES else service_language())
    return value


def for_browser(language: str) -> str:
    """The "ui." texts as JSON for the script of a page (safe inside <script>)."""
    texts = {k[len(BROWSER_PREFIX):]: v for k, v in TEXTS[language].items() if k.startswith(BROWSER_PREFIX)}
    return json.dumps(texts, ensure_ascii=False).replace("</", "<\\/")


# ---- Wiring into the app -------------------------------------------------------------


def setup(app) -> None:
    """HTTP errors in the language of the request; remember ?lang= in a cookie."""
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException

    @app.exception_handler(HTTPException)
    async def _translate_error(request, error: HTTPException):
        if isinstance(error.detail, (Text, list, tuple)):
            error = HTTPException(error.status_code, render(error.detail, for_request(request)), error.headers)
        return await http_exception_handler(request, error)

    @app.middleware("http")
    async def _remember_language(request, call_next):
        response = await call_next(request)
        choice = request.query_params.get(QUERY) or request.query_params.get(LEGACY_QUERY)
        if choice in LANGUAGES and request.cookies.get(COOKIE) != choice:
            # Without Path: valid for the page's path, behind the ingress only for this add-on
            response.set_cookie(COOKIE, choice, max_age=COOKIE_SECONDS, path=None, httponly=True, samesite="lax")
        return response
