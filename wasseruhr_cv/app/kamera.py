"""Kamerabild direkt aus Home Assistant holen (camera_proxy der REST-API).
Sicherheitsregeln (nur http(s), keine Weiterleitungen, Größenlimit) in ha.py."""

from __future__ import annotations

from . import ha

MAX_BYTES = 10 * 1024 * 1024


class KameraFehler(RuntimeError):
    pass


_HINWEISE = {
    401: "kein Zugriff – Token ungültig",
    404: "Entität unbekannt",
    500: "Kamera liefert kein Bild (offline?)",
}


def schnappschuss(ha_url: str, token: str, entity_id: str) -> bytes:
    try:
        daten = ha.anfrage(ha_url, token, "GET", f"/camera_proxy/{entity_id}", max_bytes=MAX_BYTES)
    except ha.HAFehler as e:
        if e.code in _HINWEISE:
            raise KameraFehler(f"{entity_id}: HTTP {e.code} ({_HINWEISE[e.code]})") from None
        meldung = str(e).replace("Antwort größer", "Bild größer")
        raise KameraFehler(meldung if e.code is None or e.code in (301, 302, 303, 307, 308) else f"{entity_id}: {meldung}") from None
    if not daten:
        raise KameraFehler(f"{entity_id}: leeres Bild")
    return daten
