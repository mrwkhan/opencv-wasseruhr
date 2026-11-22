"""Fetch the camera image straight from Home Assistant (camera_proxy of the REST
API). Security rules (http(s) only, no redirects, size limit) live in ha.py."""

from __future__ import annotations

from . import ha
from .i18n import T, Text, message

MAX_BYTES = 10 * 1024 * 1024
REDIRECTS = (301, 302, 303, 307, 308)
_HINTS = {401: "camera.401", 404: "camera.404", 500: "camera.500"}


class CameraError(RuntimeError):
    pass


def snapshot(ha_url: str, token: str, entity_id: str) -> bytes:
    try:
        data = ha.request(ha_url, token, "GET", f"/camera_proxy/{entity_id}", max_bytes=MAX_BYTES)
    except ha.HAError as e:
        if e.code in _HINTS:
            raise CameraError(T("camera.http", entity=entity_id, code=e.code, hint=T(_HINTS[e.code]))) from None
        text = message(e)
        if isinstance(text, Text) and text.key == "ha.too_large":
            text = T("camera.too_large", **text.values)
        if e.code is not None and e.code not in REDIRECTS:
            text = T("camera.with_entity", entity=entity_id, text=text)
        raise CameraError(text) from None
    if not data:
        raise CameraError(T("camera.empty", entity=entity_id))
    return data
