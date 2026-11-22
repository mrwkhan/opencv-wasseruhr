"""Access to the Home Assistant REST API.

In the add-on this goes through the Supervisor proxy http://supervisor/core/api
with the SUPERVISOR_TOKEN, outside with HA_URL (e.g.
http://homeassistant.local:8123/api) and a long-lived access token in HA_TOKEN.

The token has far-reaching rights in Home Assistant. Therefore: http(s) only,
no redirects (urllib would otherwise send the Authorization header to the new
destination) and size limits for responses."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

from . import i18n
from .i18n import T

TIMEOUT_S = 20
LANGUAGE_TIMEOUT_S = 5  # do not wait long for Home Assistant at start-up
MAX_RESPONSE_BYTES = 1024 * 1024


class HAError(RuntimeError):
    def __init__(self, message, code: int | None = None):
        super().__init__(message)
        self.code = code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HAError(T("ha.redirect", code=code), code)


_OPENER = urllib.request.build_opener(_NoRedirect)


def request(
    base: str, token: str, method: str, path: str, data: dict | None = None,
    max_bytes: int = MAX_RESPONSE_BYTES, timeout: float = TIMEOUT_S,
) -> bytes:
    url = base.rstrip("/") + path
    if urlsplit(url).scheme not in ("http", "https"):
        raise HAError(T("ha.scheme"))
    headers = {"Authorization": f"Bearer {token}"}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as response:  # noqa: S310 – scheme checked above
            content = response.read(max_bytes + 1)
    except HAError:
        raise
    except urllib.error.HTTPError as e:
        raise HAError(f"HTTP {e.code} ({e.reason})", e.code) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise HAError(T("ha.unreachable", reason=getattr(e, "reason", e))) from None
    if len(content) > max_bytes:
        raise HAError(T("ha.too_large", mb=max_bytes // (1024 * 1024)))
    return content


def _entity(entity_id: str) -> str:
    return quote(entity_id, safe="._")


def state(base: str, token: str, entity_id: str) -> dict | None:
    """Current state of an entity, None if it does not exist."""
    try:
        return json.loads(request(base, token, "GET", f"/states/{_entity(entity_id)}"))
    except HAError as e:
        if e.code == 404:
            return None
        raise


def set_state(base: str, token: str, entity_id: str, value: str, attributes: dict) -> None:
    request(base, token, "POST", f"/states/{_entity(entity_id)}", {"state": value, "attributes": attributes})


def call_service(base: str, token: str, domain: str, service: str, data: dict) -> None:
    request(base, token, "POST", f"/services/{_entity(domain)}/{_entity(service)}", data)


def cameras(base: str, token: str) -> list[dict]:
    """All camera entities: [{entity_id, name, state}], sorted by name."""
    states = json.loads(request(base, token, "GET", "/states", max_bytes=50 * 1024 * 1024))
    found = [
        {"entity_id": s["entity_id"], "name": (s.get("attributes") or {}).get("friendly_name") or s["entity_id"],
         "state": s.get("state")}
        for s in states if str(s.get("entity_id", "")).startswith("camera.")
    ]
    return sorted(found, key=lambda c: c["name"].lower())


def adopt_language(base: str, token: str) -> bool:
    """With LANGUAGE=auto take over the language of Home Assistant (GET /config).
    True if it was determined now. If Home Assistant cannot be reached (yet),
    English stays and the next call tries again."""
    if not i18n.pending():
        return False
    i18n.asked(remember=True)
    try:
        data = json.loads(request(base, token, "GET", "/config", timeout=LANGUAGE_TIMEOUT_S))
    except HAError as e:
        if e.code is None or e.code >= 500:
            return False
        data = {}  # Home Assistant answers but does not tell its language
    except ValueError:
        data = {}
    i18n.from_home_assistant(data.get("language") if isinstance(data, dict) else None)
    return True


# ---- Supervisor API (add-on only): read/set own options, restart -----------------

def _supervisor(base: str, token: str, method: str, path: str, data: dict | None = None) -> dict:
    answer = json.loads(request(base, token, method, path, data) or b"{}")
    if answer.get("result") not in (None, "ok"):
        raise HAError(f"Supervisor: {answer.get('message') or answer}")
    return answer.get("data") or {}


def addon_options(base: str, token: str) -> dict:
    return _supervisor(base, token, "GET", "/addons/self/info").get("options") or {}


def set_addon_options(base: str, token: str, options: dict) -> None:
    _supervisor(base, token, "POST", "/addons/self/options", {"options": options})


def restart_addon(base: str, token: str) -> None:
    _supervisor(base, token, "POST", "/addons/self/restart")
