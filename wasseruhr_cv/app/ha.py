"""Zugriff auf die REST-API von Home Assistant.

Im Add-on läuft das über den Supervisor-Proxy http://supervisor/core/api mit dem
SUPERVISOR_TOKEN, außerhalb mit HA_URL (z. B. http://homeassistant.local:8123/api)
und einem langlebigen Zugriffstoken in HA_TOKEN.

Der Token hat in Home Assistant weitreichende Rechte. Deshalb: nur http(s),
keine Weiterleitungen (urllib würde den Authorization-Header sonst an das neue
Ziel mitschicken) und Größenlimits für Antworten."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from . import sprache
from .sprache import T

TIMEOUT_S = 20
SPRACHE_TIMEOUT_S = 5  # beim Start nicht lange auf Home Assistant warten
MAX_ANTWORT_BYTES = 1024 * 1024


class HAFehler(RuntimeError):
    def __init__(self, meldung: str, code: int | None = None):
        super().__init__(meldung)
        self.code = code


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HAFehler(T("ha.weiterleitung", code=code), code)


_OEFFNER = urllib.request.build_opener(_KeineWeiterleitung)


def anfrage(
    basis: str, token: str, methode: str, pfad: str, daten: dict | None = None,
    max_bytes: int = MAX_ANTWORT_BYTES, timeout: float = TIMEOUT_S,
) -> bytes:
    url = basis.rstrip("/") + pfad
    if urlsplit(url).scheme not in ("http", "https"):
        raise HAFehler(T("ha.schema"))
    kopf = {"Authorization": f"Bearer {token}"}
    body = None
    if daten is not None:
        body = json.dumps(daten).encode()
        kopf["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=kopf, method=methode)
    try:
        with _OEFFNER.open(req, timeout=timeout) as antwort:  # noqa: S310 – Schema oben geprüft
            inhalt = antwort.read(max_bytes + 1)
    except HAFehler:
        raise
    except urllib.error.HTTPError as e:
        raise HAFehler(f"HTTP {e.code} ({e.reason})", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HAFehler(T("ha.nicht_erreichbar", grund=getattr(e, "reason", e))) from None
    if len(inhalt) > max_bytes:
        raise HAFehler(T("ha.zu_gross", mb=max_bytes // (1024 * 1024)))
    return inhalt


def _entitaet(entity_id: str) -> str:
    return quote(entity_id, safe="._")


def zustand(basis: str, token: str, entity_id: str) -> dict | None:
    """Aktueller Zustand einer Entität, None wenn es sie nicht gibt."""
    try:
        return json.loads(anfrage(basis, token, "GET", f"/states/{_entitaet(entity_id)}"))
    except HAFehler as e:
        if e.code == 404:
            return None
        raise


def zustand_setzen(basis: str, token: str, entity_id: str, state: str, attribute: dict) -> None:
    anfrage(basis, token, "POST", f"/states/{_entitaet(entity_id)}", {"state": state, "attributes": attribute})


def dienst(basis: str, token: str, domain: str, service: str, daten: dict) -> None:
    anfrage(basis, token, "POST", f"/services/{_entitaet(domain)}/{_entitaet(service)}", daten)


def kameras(basis: str, token: str) -> list[dict]:
    """Alle Kamera-Entitäten: [{entity_id, name, state}], nach Name sortiert."""
    alle = json.loads(anfrage(basis, token, "GET", "/states", max_bytes=50 * 1024 * 1024))
    liste = [
        {"entity_id": z["entity_id"], "name": (z.get("attributes") or {}).get("friendly_name") or z["entity_id"],
         "state": z.get("state")}
        for z in alle if str(z.get("entity_id", "")).startswith("camera.")
    ]
    return sorted(liste, key=lambda k: k["name"].lower())


def sprache_uebernehmen(basis: str, token: str) -> bool:
    """Bei SPRACHE=auto die Sprache von Home Assistant übernehmen (GET /config).
    True, wenn sie dabei feststand. Ist Home Assistant (noch) nicht erreichbar,
    bleibt es beim Englischen, und der nächste Aufruf versucht es erneut."""
    if not sprache.offen():
        return False
    sprache.versucht(merken=True)
    try:
        daten = json.loads(anfrage(basis, token, "GET", "/config", timeout=SPRACHE_TIMEOUT_S))
    except HAFehler as e:
        if e.code is None or e.code >= 500:
            return False
        daten = {}  # HA antwortet, verrät die Sprache aber nicht
    except ValueError:
        daten = {}
    sprache.von_home_assistant(daten.get("language") if isinstance(daten, dict) else None)
    return True


# ---- Supervisor-API (nur im Add-on): eigene Optionen lesen/setzen, neu starten -----

def _supervisor(basis: str, token: str, methode: str, pfad: str, daten: dict | None = None) -> dict:
    antwort = json.loads(anfrage(basis, token, methode, pfad, daten) or b"{}")
    if antwort.get("result") not in (None, "ok"):
        raise HAFehler(f"Supervisor: {antwort.get('message') or antwort}")
    return antwort.get("data") or {}


def addon_optionen(basis: str, token: str) -> dict:
    return _supervisor(basis, token, "GET", "/addons/self/info").get("options") or {}


def addon_optionen_setzen(basis: str, token: str, optionen: dict) -> None:
    _supervisor(basis, token, "POST", "/addons/self/options", {"options": optionen})


def addon_neu_starten(basis: str, token: str) -> None:
    _supervisor(basis, token, "POST", "/addons/self/restart")
