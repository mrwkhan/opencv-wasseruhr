"""Schutz des unauthentifizierten HTTP-Dienstes.

- Ursprungsprüfung (CSRF): Ein Browser schickt bei POST immer einen Origin-Header.
  Stammt er von einer fremden Seite, wird abgelehnt – sonst könnte jede Webseite,
  die man im Heimnetz besucht, dem Dienst falsche Werte beibringen. Programme ohne
  Origin (curl, Skripte, Automationen) und Anfragen über den HA-Ingress bleiben erlaubt.
- Größenlimit für Request-Bodies, damit niemand den Speicher füllen kann.
- Sicherheits-Header für alle Antworten.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

INGRESS_IP = "172.30.32.2"  # Absender aller Ingress-Anfragen des HA-Supervisors
MAX_BILD_BYTES = 10 * 1024 * 1024  # Kamerabilder sind typischerweise 20–200 KB
UNSICHERE_METHODEN = {"POST", "PUT", "PATCH", "DELETE"}
SICHERHEITS_HEADER = {
    "X-Content-Type-Options": "nosniff",
    # Einbetten nur auf der eigenen Seite – der HA-Ingress-Rahmen ist dieselbe Herkunft
    "Content-Security-Policy": "frame-ancestors 'self'",
    "Referrer-Policy": "same-origin",
}


def ist_ingress(request: Request) -> bool:
    return request.client is not None and request.client.host == INGRESS_IP


def fremder_ursprung(request: Request) -> bool:
    """True, wenn ein Browser die Anfrage im Auftrag einer fremden Seite stellt."""
    if request.method not in UNSICHERE_METHODEN or ist_ingress(request):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return False  # kein Browser: curl, Skripte, Home Assistant
    try:
        herkunft = urlsplit(origin).netloc.lower()
    except ValueError:
        return True
    return origin == "null" or not herkunft or herkunft != request.headers.get("host", "").lower()


def einrichten(app: FastAPI) -> None:
    @app.middleware("http")
    async def schutz(request: Request, call_next):
        if fremder_ursprung(request):
            antwort = JSONResponse(
                {"detail": "Anfrage von fremder Webseite abgelehnt"}, status_code=403
            )
        else:
            antwort = await call_next(request)
        for name, wert in SICHERHEITS_HEADER.items():
            antwort.headers.setdefault(name, wert)
        return antwort


async def body_lesen(request: Request, max_bytes: int) -> bytes:
    """Liest den Request-Body, bricht aber ab, sobald er max_bytes überschreitet."""
    zu_gross = HTTPException(status_code=413, detail=f"Body größer als {max_bytes // (1024 * 1024)} MB")
    laenge = request.headers.get("content-length")
    if laenge is not None:
        try:
            if int(laenge) > max_bytes:
                raise zu_gross
        except ValueError:
            raise HTTPException(status_code=400, detail="Ungültige Content-Length") from None
    teile, groesse = [], 0
    async for teil in request.stream():
        groesse += len(teil)
        if groesse > max_bytes:
            raise zu_gross
        teile.append(teil)
    return b"".join(teile)
