"""Protection of the unauthenticated HTTP service.

- Origin check (CSRF): a browser always sends an Origin header with POST. If it
  comes from a foreign site, the request is rejected – otherwise any website
  visited in the local network could teach the service wrong values. Programs
  without an Origin (curl, scripts, automations) and requests via the HA
  ingress stay allowed.
- Size limit for request bodies, so nobody can fill the memory.
- Security headers for all responses.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .i18n import T, for_request, translate

INGRESS_IP = "172.30.32.2"  # sender of all ingress requests of the HA Supervisor
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # camera images are typically 20–200 KB
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    # Embedding only on the own page – the HA ingress frame has the same origin
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Referrer-Policy": "same-origin",
}


def is_ingress(request: Request) -> bool:
    return request.client is not None and request.client.host == INGRESS_IP


def foreign_origin(request: Request) -> bool:
    """True if a browser makes the request on behalf of a foreign website."""
    if request.method not in UNSAFE_METHODS or is_ingress(request):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return False  # not a browser: curl, scripts, Home Assistant
    try:
        host = urlsplit(origin).netloc.lower()
    except ValueError:
        return True
    return origin == "null" or not host or host != request.headers.get("host", "").lower()


def setup(app: FastAPI) -> None:
    @app.middleware("http")
    async def protect(request: Request, call_next):
        if foreign_origin(request):
            response = JSONResponse({"detail": translate("api.foreign_website", for_request(request))}, status_code=403)
        else:
            response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


async def read_body(request: Request, max_bytes: int) -> bytes:
    """Reads the request body, but stops as soon as it exceeds max_bytes."""
    too_large = HTTPException(status_code=413, detail=T("api.body_too_large", mb=max_bytes // (1024 * 1024)))
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > max_bytes:
                raise too_large
        except ValueError:
            raise HTTPException(status_code=400, detail=T("api.content_length")) from None
    parts, size = [], 0
    async for part in request.stream():
        size += len(part)
        if size > max_bytes:
            raise too_large
        parts.append(part)
    return b"".join(parts)
