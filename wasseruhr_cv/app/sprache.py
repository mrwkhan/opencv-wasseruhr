"""Zweisprachigkeit (Deutsch/Englisch) für Oberfläche, Meldungen, Protokoll und Sensor.

Alle Texte stehen unter demselben Schlüssel in app/texte/de.json und en.json.
Platzhalter heißen {name} und werden in Python und im Browser gleich ersetzt.
Ein Text wird erst bei der Ausgabe in eine Sprache gebracht (Klasse Text). So
erscheint dieselbe Meldung im Protokoll in der Sprache des Dienstes und im
Browser in der Sprache des Benutzers.

Welche Sprache gilt:
- Webseiten und API-Meldungen, je Anfrage: Umschalter auf der Seite
  (?sprache=de|en, als Cookie gemerkt) → Option SPRACHE → Accept-Language des
  Browsers → Sprache des Dienstes.
- Protokoll und Sensor (Sprache des Dienstes): Option SPRACHE, bei "auto" die
  Sprache von Home Assistant, ohne Home Assistant Englisch.

Schlüssel mit dem Präfix "ui." gehen zusätzlich an das Skript der Webseiten,
Schlüssel mit der Endung "_html" werden ohne Escaping ins HTML übernommen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

SPRACHEN = ("de", "en")
STANDARD = "en"  # wenn sonst nichts feststeht
AUTO = "auto"
COOKIE = "wasseruhr_sprache"
COOKIE_SEKUNDEN = 365 * 24 * 3600
BROWSER_PRAEFIX = "ui."

_PLATZHALTER = re.compile(r"\{(\w+)\}")
TEXTE: dict[str, dict[str, str]] = {
    s: json.loads((Path(__file__).with_name("texte") / f"{s}.json").read_text(encoding="utf-8"))
    for s in SPRACHEN
}

# Sprache des Dienstes (Protokoll, Sensor). quelle: option | home_assistant | standard
_zustand = SimpleNamespace(fest=None, dienst=STANDARD, ermittelt=False, quelle="standard", versucht=False)


def einstellen(wahl: str) -> None:
    """Option SPRACHE übernehmen: 'de'/'en' fest, sonst automatisch."""
    fest = wahl in SPRACHEN
    _zustand.fest = wahl if fest else None
    _zustand.dienst = wahl if fest else STANDARD
    _zustand.ermittelt = fest
    _zustand.quelle = "option" if fest else "standard"
    _zustand.versucht = False


def versucht(merken: bool = False) -> bool:
    """Wurde Home Assistant seit dem Einstellen schon nach der Sprache gefragt?
    (Beim Start nur einmal fragen, auch wenn es nicht erreichbar ist.)"""
    if merken:
        _zustand.versucht = True
    return _zustand.versucht


def dienst() -> str:
    """Sprache von Protokoll und Sensor."""
    return _zustand.dienst


def quelle() -> str:
    return _zustand.quelle


def offen() -> bool:
    """True bei SPRACHE=auto, solange die Sprache von Home Assistant noch fehlt."""
    return not _zustand.ermittelt


def von_home_assistant(code: str | None) -> str:
    """Sprache aus der Konfiguration von Home Assistant übernehmen (nur bei auto)."""
    if _zustand.fest is None:
        _zustand.dienst = aus_code(code) or STANDARD
        _zustand.ermittelt, _zustand.quelle = True, "home_assistant"
    return _zustand.dienst


def aus_code(code: str | None) -> str | None:
    """'de-DE', 'de_AT', 'DE' -> 'de'; nicht unterstützt -> None."""
    if not code:
        return None
    basis = re.split(r"[-_]", code.strip(), maxsplit=1)[0].lower()
    return basis if basis in SPRACHEN else None


def aus_accept_language(kopf: str | None) -> str | None:
    """Erste unterstützte Sprache aus z. B. 'fr-FR,fr;q=0.9,en;q=0.8' (nach Gewicht q)."""
    if not kopf:
        return None
    kandidaten = []
    for i, teil in enumerate(kopf.split(",")):
        code, *parameter = (p.strip() for p in teil.split(";"))
        gewicht = 1.0
        for p in parameter:
            name, _, wert = p.partition("=")
            if name.strip() == "q":
                try:
                    gewicht = float(wert)
                except ValueError:
                    gewicht = 0.0
        if gewicht > 0:
            kandidaten.append((-gewicht, i, code))
    for _, _, code in sorted(kandidaten):
        if gefunden := aus_code(code):
            return gefunden
    return None


def aus_anfrage(request) -> str:
    """Sprache für die Antwort auf eine Anfrage (Seite, Bild, Fehlermeldung)."""
    for wahl in (request.query_params.get("sprache"), request.cookies.get(COOKIE)):
        if wahl in SPRACHEN:
            return wahl
    konfig = getattr(request.app.state, "konfig", None)
    if getattr(konfig, "sprache", None) in SPRACHEN:
        return konfig.sprache
    return aus_accept_language(request.headers.get("accept-language")) or dienst()


# ---- Texte ---------------------------------------------------------------------


def uebersetzen(schluessel: str, sprache: str | None = None, /, **werte) -> str:
    """Text in der Sprache (Standard: Sprache des Dienstes), Platzhalter ersetzt."""
    sprache = sprache if sprache in SPRACHEN else dienst()
    text = TEXTE[sprache].get(schluessel)
    if text is None:
        text = TEXTE[STANDARD].get(schluessel, schluessel)
    if not werte:
        return text
    return _PLATZHALTER.sub(
        lambda m: _als_text(werte[m.group(1)], sprache) if m.group(1) in werte else m.group(0), text
    )


class Text:
    """Übersetzbarer Text: Schlüssel und Werte, erst bei der Ausgabe in einer Sprache.

    Geht als Meldung in Ausnahmen, Protokoll und HTTP-Fehler; str() liefert die
    Sprache des Dienstes, in_sprache() eine bestimmte."""

    __slots__ = ("schluessel", "werte")

    def __init__(self, schluessel: str, /, **werte):
        self.schluessel = schluessel
        self.werte = werte

    def in_sprache(self, sprache: str | None = None) -> str:
        return uebersetzen(self.schluessel, sprache, **self.werte)

    def __str__(self) -> str:
        return self.in_sprache()

    def __repr__(self) -> str:
        return f"Text({self.schluessel!r}, {self.werte!r})"


T = Text


def meldung(fehler: BaseException) -> Text | str:
    """Meldung einer Ausnahme – übersetzbar, wenn sie mit einem Text erzeugt wurde."""
    if fehler.args and isinstance(fehler.args[0], Text):
        return fehler.args[0]
    return str(fehler)


def _als_text(wert, sprache: str) -> str:
    if isinstance(wert, Text):
        return wert.in_sprache(sprache)
    if isinstance(wert, BaseException):
        return _als_text(meldung(wert), sprache)
    if isinstance(wert, (list, tuple)):
        return "; ".join(_als_text(w, sprache) for w in wert)
    return str(wert)


def ausgeben(wert, sprache: str | None = None):
    """Text, Ausnahme oder Liste davon -> str in der Sprache; alles andere unverändert."""
    if isinstance(wert, (Text, BaseException, list, tuple)):
        return _als_text(wert, sprache if sprache in SPRACHEN else dienst())
    return wert


def fuer_browser(sprache: str) -> str:
    """Die "ui."-Texte als JSON für das Skript einer Seite (sicher in <script>)."""
    daten = {k[len(BROWSER_PRAEFIX):]: v for k, v in TEXTE[sprache].items() if k.startswith(BROWSER_PRAEFIX)}
    return json.dumps(daten, ensure_ascii=False).replace("</", "<\\/")


# ---- Anbindung an die App ----------------------------------------------------------


def einrichten(app) -> None:
    """HTTP-Fehler in der Sprache der Anfrage; ?sprache= als Cookie merken."""
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException

    @app.exception_handler(HTTPException)
    async def _fehler_uebersetzen(request, fehler: HTTPException):
        if isinstance(fehler.detail, (Text, list, tuple)):
            fehler = HTTPException(fehler.status_code, ausgeben(fehler.detail, aus_anfrage(request)), fehler.headers)
        return await http_exception_handler(request, fehler)

    @app.middleware("http")
    async def _sprache_merken(request, call_next):
        antwort = await call_next(request)
        wahl = request.query_params.get("sprache")
        if wahl in SPRACHEN and request.cookies.get(COOKIE) != wahl:
            # Ohne Path: gilt für den Pfad der Seite, hinter dem Ingress also nur für dieses Add-on
            antwort.set_cookie(COOKIE, wahl, max_age=COOKIE_SEKUNDEN, path=None, httponly=True, samesite="lax")
        return antwort
