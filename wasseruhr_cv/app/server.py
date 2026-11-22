"""Startet den Webdienst auf einem oder mehreren Ports – alle in einem Prozess
mit derselben App:

- PORT (8099): immer an. Im Add-on nur über den Ingress (Seitenleiste) und das
  interne Netz erreichbar, in Docker der Hauptport.
- HTTP_PORT (8080): optional, Klartext-HTTP fürs Heimnetz.
- HTTPS_PORT (8443): optional, verschlüsselt. Ohne eigenes Zertifikat wird
  einmalig ein selbstsigniertes erzeugt.

Die App-Lebensdauer (Vorlagen laden, Automatik starten/stoppen) läuft nur am
Hauptport. Weitere Ports starten erst, wenn der Hauptport bereit ist."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import ssl
import subprocess
from pathlib import Path

import uvicorn

from .konfig import Konfig

log = logging.getLogger("wasseruhr")
HOST = "0.0.0.0"  # im Container: alle Schnittstellen; nach außen entscheidet die Portfreigabe


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):
        # Signale behandelt _laufen() einmal für alle Server gemeinsam
        yield


def tls_dateien(konfig: Konfig) -> tuple[Path, Path, str]:
    """(Zertifikat, Schlüssel, Beschreibung). Fällt auf ein selbstsigniertes zurück."""
    zertifikat, schluessel = konfig.ssl_pfad(konfig.zertifikat), konfig.ssl_pfad(konfig.schluessel)
    if zertifikat.is_file() and schluessel.is_file():
        try:
            ssl.create_default_context(ssl.Purpose.CLIENT_AUTH).load_cert_chain(zertifikat, schluessel)
            return zertifikat, schluessel, f"Zertifikat {zertifikat}"
        except (ssl.SSLError, OSError) as e:
            log.warning("HTTPS: %s / %s nicht nutzbar (%s) – nutze selbstsigniertes Zertifikat",
                        zertifikat, schluessel, e)
    else:
        log.warning("HTTPS: %s oder %s fehlt – nutze selbstsigniertes Zertifikat (Browser warnt)",
                    zertifikat, schluessel)
    zertifikat, schluessel = selbstsigniert(konfig.daten_verzeichnis / "tls")
    return zertifikat, schluessel, "selbstsigniertes Zertifikat"


def selbstsigniert(ordner: Path) -> tuple[Path, Path]:
    zertifikat, schluessel = ordner / "selbstsigniert.crt", ordner / "selbstsigniert.key"
    if zertifikat.is_file() and schluessel.is_file():
        return zertifikat, schluessel
    ordner.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "3650",
         "-subj", "/CN=wasseruhr-cv", "-keyout", str(schluessel), "-out", str(zertifikat)],
        check=True, capture_output=True,
    )
    schluessel.chmod(0o600)
    log.info("HTTPS: selbstsigniertes Zertifikat erzeugt: %s", zertifikat)
    return zertifikat, schluessel


def _config(app, port: int, haupt: bool, **extra) -> uvicorn.Config:
    return uvicorn.Config(
        app, host=HOST, port=port, lifespan="on" if haupt else "off", access_log=False,
        timeout_graceful_shutdown=5, **({} if haupt else {"log_config": None}), **extra,
    )


def server_liste(app, konfig: Konfig) -> list[tuple[str, uvicorn.Server]]:
    liste = [(f"Ingress/intern :{konfig.port}", _Server(_config(app, konfig.port, True)))]
    if konfig.http:
        liste.append((f"HTTP :{konfig.http_port}", _Server(_config(app, konfig.http_port, False))))
    if konfig.https:
        zertifikat, schluessel, art = tls_dateien(konfig)
        liste.append((
            f"HTTPS :{konfig.https_port} ({art})",
            _Server(_config(app, konfig.https_port, False, ssl_certfile=str(zertifikat), ssl_keyfile=str(schluessel))),
        ))
    return liste


async def _laufen(liste: list[tuple[str, uvicorn.Server]]) -> None:
    server = [s for _, s in liste]
    loop = asyncio.get_running_loop()

    def beenden() -> None:
        for s in server:
            s.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, beenden)

    haupt = asyncio.create_task(server[0].serve())
    while not server[0].started:  # weitere Ports erst, wenn Vorlagen geladen sind
        if haupt.done():
            await haupt  # Start fehlgeschlagen: Fehler weiterreichen
            return
        await asyncio.sleep(0.05)
    weitere = [asyncio.create_task(s.serve()) for s in server[1:]]
    log.info("Erreichbar: %s", " | ".join(name for name, _ in liste))
    await asyncio.gather(haupt, *weitere)


def starten(app, konfig: Konfig) -> None:
    asyncio.run(_laufen(server_liste(app, konfig)))
