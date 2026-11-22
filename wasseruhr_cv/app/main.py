"""FastAPI-Webdienst: liest die Wasseruhr ab und lernt Ziffern-Vorlagen."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__, debugbild, kamera, lernseite, modell, verwaltung
from .erkennung import (
    BildFehler,
    ZiffernErgebnis,
    dekodiere_bild,
    erkenne_ziffer,
    ist_sicher,
    schneide_ziffern,
    zerlege_wert,
    zusammensetzen,
)
from .konfig import NACHKOMMASTELLEN, Konfig
from .lernbilder import LernbildArchiv
from .vorlagen import VorlagenSpeicher

log = logging.getLogger("wasseruhr")

VERLAUF_LAENGE = 20  # so viele Ablesungen bleiben für Debug-Bild und Lernseite im Speicher


@dataclass
class Ablesung:
    nr: int
    zeit: datetime
    daten: bytes  # Original-JPEG, damit genau dieses Bild gelernt werden kann
    bild: np.ndarray
    ziffern: list[np.ndarray]
    ergebnisse: list[ZiffernErgebnis]
    sicher_pro_rolle: list[bool]
    wert: float | None
    sicher: bool


def _logging_einrichten() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def create_app(konfig: Konfig | None = None) -> FastAPI:
    _logging_einrichten()
    konfig = konfig or Konfig.aus_umgebung()
    speicher = VorlagenSpeicher(konfig.vorlagen_verzeichnis, konfig.max_vorlagen_pro_ziffer)
    archiv = LernbildArchiv(konfig.lernbilder_verzeichnis)
    verlauf: OrderedDict[int, Ablesung] = OrderedDict()
    verlauf_lock = threading.Lock()
    zaehler = [0]
    lern_lock = threading.Lock()  # Archiv + Vorlagen in derselben Reihenfolge

    def _lernbilder_aus_archiv():
        for e in archiv.eintraege():
            try:
                soll = zerlege_wert(e.wert, konfig.anzahl_rollen, NACHKOMMASTELLEN)
                ziffern = schneide_ziffern(dekodiere_bild(e.pfad.read_bytes()), konfig.rois)
            except (ValueError, OSError) as ex:  # BildFehler ist ein ValueError
                log.warning("Lernbild %s übersprungen: %s", e.pfad.name, ex)
                continue
            yield e.zeitstempel, soll, ziffern

    def _neu_aufbauen() -> int:
        """Vorlagen komplett aus dem Archiv neu erzeugen (Aufrufer hält lern_lock)."""
        anzahl = speicher.neu_aufbauen(_lernbilder_aus_archiv())
        log.info("Vorlagen aus %d Lernbildern neu aufgebaut: %s", anzahl, speicher.anzahl_pro_ziffer())
        return anzahl

    def _vorlagen_bereitstellen() -> None:
        speicher.verzeichnis.mkdir(parents=True, exist_ok=True)
        if konfig.modell_verzeichnis is not None:
            modell.erstausstattung(konfig.modell_verzeichnis, konfig.daten_verzeichnis, archiv, speicher)
        if not konfig.lerneffekt:
            speicher.laden()
            log.info("Lerneffekt AUS: Vorlagen eingefroren, /lernen archiviert nur noch")
            return
        if archiv.anzahl() == 0:
            speicher.laden()
            return
        anzahl = speicher.neu_aufbauen(_lernbilder_aus_archiv())
        log.info(
            "Lerneffekt AN: Vorlagen aus %d Lernbildern neu aufgebaut: %s",
            anzahl, speicher.anzahl_pro_ziffer(),
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        log.info(
            "Start v%s: %d ROIs, MIN_SCORE=%.2f, MIN_ABSTAND=%.2f, MAX_VORLAGEN_PRO_ZIFFER=%d, "
            "VERSCHIEBUNG=±%dpx, LERNEFFEKT=%s, Daten in %s",
            __version__, konfig.anzahl_rollen, konfig.min_score, konfig.min_abstand,
            konfig.max_vorlagen_pro_ziffer, konfig.verschiebung,
            "an" if konfig.lerneffekt else "aus", konfig.daten_verzeichnis,
        )
        log.info(
            "Kamera: %s | Verwaltung: %s",
            konfig.kamera or "keine" if konfig.ha_token else f"{konfig.kamera or 'keine'} (ohne HA-Zugang)",
            "nur über HA-Ingress" if konfig.admin_nur_ingress else "im ganzen Netz",
        )
        _vorlagen_bereitstellen()
        yield

    app = FastAPI(title="Wasseruhr-CV", version=__version__, lifespan=lifespan)
    app.state.konfig = konfig
    app.state.speicher = speicher
    app.state.archiv = archiv

    def _ziffern_aus_body(daten: bytes) -> tuple[np.ndarray, list[np.ndarray]]:
        try:
            bild = dekodiere_bild(daten)
            return bild, schneide_ziffern(bild, konfig.rois)
        except BildFehler as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    # ---- POST /ablesen -------------------------------------------------------

    def _ablesen(daten: bytes) -> dict:
        return _ablesen_mit_nr(daten)[1]

    def _ablesen_mit_nr(daten: bytes) -> tuple[int, dict]:
        bild, ziffern = _ziffern_aus_body(daten)
        vorlagen = speicher.momentaufnahme()
        ergebnisse = [
            erkenne_ziffer(rolle, z, vorlagen, konfig.verschiebung)
            for rolle, z in enumerate(ziffern, start=1)
        ]
        sicher_pro_rolle = [ist_sicher(e, konfig.min_score, konfig.min_abstand) for e in ergebnisse]
        sicher = all(sicher_pro_rolle)
        wert = zusammensetzen(ergebnisse, NACHKOMMASTELLEN)
        fehlende = [z for z, liste in vorlagen.items() if not liste]

        with verlauf_lock:
            zaehler[0] += 1
            nr = zaehler[0]
            verlauf[nr] = Ablesung(
                nr, datetime.now(timezone.utc), daten, bild, ziffern, ergebnisse, sicher_pro_rolle, wert, sicher
            )
            while len(verlauf) > VERLAUF_LAENGE:
                verlauf.popitem(last=False)

        log.info(
            "ablesen #%d: wert=%s sicher=%s | %s%s",
            nr,
            "null" if wert is None else f"{wert:.3f}",
            "ja" if sicher else "nein",
            " ".join(_kurz(e, ok) for e, ok in zip(ergebnisse, sicher_pro_rolle)),
            f" | fehlende Vorlagen: {fehlende}" if fehlende else "",
        )
        return nr, {
            "wert": wert,
            "sicher": sicher,
            "ziffern": [e.als_dict() for e in ergebnisse],
            "fehlende_vorlagen": fehlende,
        }

    @app.post("/ablesen")
    async def ablesen(request: Request) -> dict:
        return await run_in_threadpool(_ablesen, await request.body())

    # ---- POST /kamera-ablesen ------------------------------------------------

    def _kamera_ablesen() -> dict:
        if not konfig.kamera:
            raise HTTPException(status_code=400, detail="Keine Kamera eingestellt (Option kamera bzw. KAMERA)")
        if not konfig.ha_token:
            raise HTTPException(
                status_code=400,
                detail="Kein Zugang zu Home Assistant: nur im Add-on oder mit HA_URL und HA_TOKEN",
            )
        try:
            daten = kamera.schnappschuss(konfig.ha_url, konfig.ha_token, konfig.kamera)
        except kamera.KameraFehler as e:
            raise HTTPException(status_code=502, detail=f"Kamerabild nicht geladen: {e}") from None
        nr, ergebnis = _ablesen_mit_nr(daten)
        return {"nr": nr, **ergebnis}

    @app.post("/kamera-ablesen")
    async def kamera_ablesen() -> dict:
        """Holt das aktuelle Bild der eingestellten Kamera aus Home Assistant und liest es ab."""
        return await run_in_threadpool(_kamera_ablesen)

    # ---- POST /lernen --------------------------------------------------------

    def _ablesung(nr: int | None) -> Ablesung | None:
        with verlauf_lock:
            if nr is None:
                return next(reversed(verlauf.values()), None)
            return verlauf.get(nr)

    def _lernen(daten: bytes, wert_text: str, ablesung: int | None) -> dict:
        try:
            wert = float(wert_text.strip().replace(",", "."))
            soll = zerlege_wert(wert, konfig.anzahl_rollen, NACHKOMMASTELLEN)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Ungültiger wert={wert_text!r}: {e}") from None
        aus_verlauf = not daten and ablesung is not None
        if aus_verlauf:
            a = _ablesung(ablesung)
            if a is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Ablesung #{ablesung} ist nicht mehr im Speicher – Seite neu laden",
                )
            daten = a.daten
        _bild, ziffern = _ziffern_aus_body(daten)  # erst prüfen, dann archivieren
        with lern_lock:
            zeitstempel = archiv.speichern(daten, wert)
            gespeichert = speicher.lernen(zeitstempel, soll, ziffern) if konfig.lerneffekt else 0
        anzahl = speicher.anzahl_pro_ziffer()
        log.info(
            "lernen: wert=%s ziffern=%s gespeichert=%d%s vorlagen_pro_ziffer=%s",
            wert_text, "".join(map(str, soll)), gespeichert,
            "" if konfig.lerneffekt else " (Lerneffekt aus, nur archiviert)", anzahl,
        )
        if aus_verlauf:
            _ablesen(daten)  # gleiches Bild sofort neu ablesen -> Lernseite zeigt den Effekt
        return {"gespeichert": gespeichert, "vorlagen_pro_ziffer": anzahl}

    @app.post("/lernen")
    async def lernen(
        request: Request,
        wert: str = Query(..., description="Abgelesener Zählerstand, z. B. 506.388"),
        ablesung: int | None = Query(
            None, description="Ohne Body: das Bild dieser Ablesung (Nr. aus der Lernseite) lernen"
        ),
    ) -> dict:
        return await run_in_threadpool(_lernen, await request.body(), wert, ablesung)

    # ---- GET /status, /debug.png, /health ----------------------------------

    @app.get("/status")
    def status() -> dict:
        return {
            "vorlagen_pro_ziffer": speicher.anzahl_pro_ziffer(),
            "fehlende_vorlagen": speicher.fehlende_ziffern(),
            "lerneffekt": konfig.lerneffekt,
            "lernbilder": archiv.anzahl(),
        }

    @app.get("/debug.png")
    def debug_png(
        letztes: int = Query(1, description="1 = Bild des letzten /ablesen-Aufrufs"),
        nr: int | None = Query(None, description="stattdessen eine bestimmte Ablesung"),
    ) -> Response:
        a = _ablesung(nr)
        if a is None:
            raise HTTPException(
                status_code=404,
                detail="Noch kein /ablesen-Aufruf seit dem Start" if nr is None
                else f"Ablesung #{nr} ist nicht mehr im Speicher",
            )
        png = debugbild.zeichne(
            a.bild, konfig.rois, a.ziffern, a.ergebnisse, a.sicher_pro_rolle, a.wert, a.sicher
        )
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def startseite(request: Request, nr: int | None = None) -> HTMLResponse:
        a = _ablesung(nr) or _ablesung(None)
        neueste = _ablesung(None)
        return HTMLResponse(
            lernseite.rendern(
                lerneffekt=konfig.lerneffekt,
                lernbilder=archiv.anzahl(),
                fehlende=speicher.fehlende_ziffern(),
                nr=a.nr if a else None,
                zeit=a.zeit if a else None,
                wert=a.wert if a else None,
                sicher=a.sicher if a else False,
                ist_neueste=a is neueste,
                kamera=bool(konfig.kamera and konfig.ha_token),
                verwaltung=verwaltung.verwaltung_erlaubt(konfig, request),
            ),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    # ---- /admin: Verwaltung ----------------------------------------------------

    def _ablesungen() -> list[Ablesung]:
        with verlauf_lock:
            return list(reversed(verlauf.values()))

    app.include_router(
        verwaltung.router(
            verwaltung.Kontext(
                konfig=konfig,
                speicher=speicher,
                archiv=archiv,
                lern_lock=lern_lock,
                neu_aufbauen=_neu_aufbauen,
                ablesungen=_ablesungen,
                version=__version__,
            )
        )
    )

    return app


def _kurz(e: ZiffernErgebnis, ok: bool) -> str:
    if e.ziffer is None:
        return f"r{e.rolle}=?"
    zweite = "" if e.zweitbeste is None else f"/{e.zweitbeste}:{e.score2:.2f}"
    return f"r{e.rolle}={e.ziffer}({e.score:.2f}{zweite}){'' if ok else '!'}"


app = create_app()
