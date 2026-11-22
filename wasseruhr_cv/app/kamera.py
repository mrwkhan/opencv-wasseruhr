"""Kamerabild direkt aus Home Assistant holen (camera_proxy der REST-API).

Im Add-on läuft das über den Supervisor-Proxy http://supervisor/core/api mit dem
SUPERVISOR_TOKEN, außerhalb mit HA_URL (z. B. http://homeassistant.local:8123/api)
und einem langlebigen Zugriffstoken in HA_TOKEN.

Der Token hat in Home Assistant weitreichende Rechte. Deshalb: nur http(s),
keine Weiterleitungen (urllib würde den Authorization-Header sonst an das neue
Ziel mitschicken) und ein Größenlimit für die Antwort."""

from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urlsplit

TIMEOUT_S = 20
MAX_BYTES = 10 * 1024 * 1024


class KameraFehler(RuntimeError):
    pass


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise KameraFehler(f"Home Assistant leitet weiter (HTTP {code}) – aus Sicherheitsgründen nicht gefolgt")


_OEFFNER = urllib.request.build_opener(_KeineWeiterleitung)


def schnappschuss(ha_url: str, token: str, entity_id: str) -> bytes:
    url = f"{ha_url.rstrip('/')}/camera_proxy/{entity_id}"
    if urlsplit(url).scheme not in ("http", "https"):
        raise KameraFehler("HA_URL muss mit http:// oder https:// beginnen")
    anfrage = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with _OEFFNER.open(anfrage, timeout=TIMEOUT_S) as antwort:  # noqa: S310 – Schema oben geprüft
            daten = antwort.read(MAX_BYTES + 1)
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
    if len(daten) > MAX_BYTES:
        raise KameraFehler(f"{entity_id}: Bild größer als {MAX_BYTES // (1024 * 1024)} MB")
    return daten
