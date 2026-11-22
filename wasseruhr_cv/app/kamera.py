"""Kamerabild direkt aus Home Assistant holen (camera_proxy der REST-API).

Im Add-on läuft das über den Supervisor-Proxy http://supervisor/core/api mit dem
SUPERVISOR_TOKEN, außerhalb mit HA_URL (z. B. http://homeassistant.local:8123/api)
und einem langlebigen Zugriffstoken in HA_TOKEN."""

from __future__ import annotations

import urllib.error
import urllib.request

TIMEOUT_S = 20


class KameraFehler(RuntimeError):
    pass


def schnappschuss(ha_url: str, token: str, entity_id: str) -> bytes:
    url = f"{ha_url.rstrip('/')}/camera_proxy/{entity_id}"
    anfrage = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            daten = antwort.read()
    except urllib.error.HTTPError as e:
        hinweis = {
            401: "kein Zugriff – Token ungültig",
            404: "Entität unbekannt",
            500: "Kamera liefert kein Bild (offline?)",
        }.get(e.code, e.reason)
        raise KameraFehler(f"{entity_id}: HTTP {e.code} ({hinweis})") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        grund = getattr(e, "reason", e)
        raise KameraFehler(f"Home Assistant nicht erreichbar ({grund})") from None
    if not daten:
        raise KameraFehler(f"{entity_id}: leeres Bild")
    return daten
