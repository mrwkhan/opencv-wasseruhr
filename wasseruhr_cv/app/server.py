"""Starts the web service on one or more ports – all in one process with the
same app:

- PORT (8099): always on. In the add-on only reachable via the ingress
  (sidebar) and the internal network, in Docker the main port.
- HTTP_PORT (8080): optional, plain HTTP for the local network.
- HTTPS_PORT (8443): optional, encrypted. Without an own certificate a
  self-signed one is created once.

The app lifespan (load templates, start/stop the automatic reading) only runs
on the main port. Further ports start once the main port is ready."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import ssl
import subprocess
from pathlib import Path

import uvicorn

from .config import Config
from .i18n import T, Text

log = logging.getLogger("wasseruhr")
HOST = "0.0.0.0"  # in the container: all interfaces; the port mapping decides what is reachable


class _Server(uvicorn.Server):
    @contextlib.contextmanager
    def capture_signals(self):
        # _run() handles signals once for all servers together
        yield


def tls_files(config: Config) -> tuple[Path, Path, Text]:
    """(certificate, key, description). Falls back to a self-signed certificate."""
    certificate, key = config.ssl_path(config.certificate), config.ssl_path(config.certificate_key)
    if certificate.is_file() and key.is_file():
        try:
            ssl.create_default_context(ssl.Purpose.CLIENT_AUTH).load_cert_chain(certificate, key)
            return certificate, key, T("server.certificate", path=certificate)
        except (ssl.SSLError, OSError) as e:
            log.warning(T("log.https_unusable", certificate=certificate, key=key, error=e))
    else:
        log.warning(T("log.https_missing", certificate=certificate, key=key))
    certificate, key = self_signed(config.data_dir / "tls")
    return certificate, key, T("server.self_signed")


def self_signed(folder: Path) -> tuple[Path, Path]:
    certificate, key = folder / "self-signed.crt", folder / "self-signed.key"
    if certificate.is_file() and key.is_file():
        return certificate, key
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "3650",
         "-subj", "/CN=wasseruhr-cv", "-keyout", str(key), "-out", str(certificate)],
        check=True, capture_output=True,
    )
    key.chmod(0o600)
    log.info(T("log.self_signed_created", path=certificate))
    return certificate, key


def _config(app, port: int, main: bool, **extra) -> uvicorn.Config:
    return uvicorn.Config(
        app, host=HOST, port=port, lifespan="on" if main else "off", access_log=False,
        timeout_graceful_shutdown=5, **({} if main else {"log_config": None}), **extra,
    )


def server_list(app, config: Config) -> list[tuple[Text | str, uvicorn.Server]]:
    servers = [(T("server.internal", port=config.port), _Server(_config(app, config.port, True)))]
    if config.http:
        servers.append((f"HTTP :{config.http_port}", _Server(_config(app, config.http_port, False))))
    if config.https:
        certificate, key, kind = tls_files(config)
        servers.append((
            T("server.https", port=config.https_port, kind=kind),
            _Server(_config(app, config.https_port, False, ssl_certfile=str(certificate), ssl_keyfile=str(key))),
        ))
    return servers


async def _run(servers: list[tuple[Text | str, uvicorn.Server]]) -> None:
    instances = [s for _, s in servers]
    loop = asyncio.get_running_loop()

    def stop() -> None:
        for s in instances:
            s.should_exit = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop)

    main = asyncio.create_task(instances[0].serve())
    while not instances[0].started:  # further ports only once the templates are loaded
        if main.done():
            await main  # start failed: pass the error on
            return
        await asyncio.sleep(0.05)
    others = [asyncio.create_task(s.serve()) for s in instances[1:]]
    log.info(T("log.listening", servers=" | ".join(str(name) for name, _ in servers)))
    await asyncio.gather(main, *others)


def start(app, config: Config) -> None:
    asyncio.run(_run(server_list(app, config)))
