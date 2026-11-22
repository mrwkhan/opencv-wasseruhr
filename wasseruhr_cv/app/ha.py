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

TIMEOUT_S = 20
MAX_ANTWORT_BYTES = 1024 * 1024


class HAFehler(RuntimeError):
    def __init__(self, meldung: str, code: int | None = None):
        super().__init__(meldung)
        self.code = code


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HAFehler(f"Home Assistant leitet weiter (HTTP {code}) – aus Sicherheitsgründen nicht gefolgt", code)


_OEFFNER = urllib.request.build_opener(_KeineWeiterleitung)


def anfrage(
    basis: str, token: str, methode: str, pfad: str, daten: dict | None = None,
    max_bytes: int = MAX_ANTWORT_BYTES,
) -> bytes:
    url = basis.rstrip("/") + pfad
    if urlsplit(url).scheme not in ("http", "https"):
        raise HAFehler("HA_URL muss mit http:// oder https:// beginnen")
    kopf = {"Authorization": f"Bearer {token}"}
    body = None
    if daten is not None:
        body = json.dumps(daten).encode()
        kopf["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=kopf, method=methode)
    try:
        with _OEFFNER.open(req, timeout=TIMEOUT_S) as antwort:  # noqa: S310 – Schema oben geprüft
            inhalt = antwort.read(max_bytes + 1)
    except HAFehler:
        raise
    except urllib.error.HTTPError as e:
        raise HAFehler(f"HTTP {e.code} ({e.reason})", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HAFehler(f"Home Assistant nicht erreichbar ({getattr(e, 'reason', e)})") from None
    if len(inhalt) > max_bytes:
        raise HAFehler(f"Antwort größer als {max_bytes // (1024 * 1024)} MB")
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
