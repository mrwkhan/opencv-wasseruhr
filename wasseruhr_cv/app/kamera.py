"""Kamerabild direkt aus Home Assistant holen (camera_proxy der REST-API).
Sicherheitsregeln (nur http(s), keine Weiterleitungen, Größenlimit) in ha.py."""

from __future__ import annotations

from . import ha
from .sprache import T, Text, meldung

MAX_BYTES = 10 * 1024 * 1024


class KameraFehler(RuntimeError):
    pass


_HINWEISE = {401: "kamera.401", 404: "kamera.404", 500: "kamera.500"}
WEITERLEITUNG = (301, 302, 303, 307, 308)


def schnappschuss(ha_url: str, token: str, entity_id: str) -> bytes:
    try:
        daten = ha.anfrage(ha_url, token, "GET", f"/camera_proxy/{entity_id}", max_bytes=MAX_BYTES)
    except ha.HAFehler as e:
        if e.code in _HINWEISE:
            raise KameraFehler(T("kamera.http", entity=entity_id, code=e.code, hinweis=T(_HINWEISE[e.code]))) from None
        text = meldung(e)
        if isinstance(text, Text) and text.schluessel == "ha.zu_gross":
            text = T("kamera.zu_gross", **text.werte)
        if e.code is not None and e.code not in WEITERLEITUNG:
            text = T("kamera.mit_entity", entity=entity_id, text=text)
        raise KameraFehler(text) from None
    if not daten:
        raise KameraFehler(T("kamera.leer", entity=entity_id))
    return daten
