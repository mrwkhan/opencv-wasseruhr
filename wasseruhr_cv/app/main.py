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

from . import __version__, debugbild, ha, kamera, lernseite, modell, schutz, sprache, verwaltung
from .automatik import Automatik
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
from .sprache import T, aus_anfrage, meldung
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
    sprache.einstellen(konfig.sprache)
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
                log.warning(T("log.lernbild_uebersprungen", name=e.pfad.name, fehler=ex))
                continue
            yield e.zeitstempel, soll, ziffern

    def _neu_aufbauen() -> int:
        """Vorlagen komplett aus dem Archiv neu erzeugen (Aufrufer hält lern_lock)."""
        anzahl = speicher.neu_aufbauen(_lernbilder_aus_archiv())
        log.info(T("log.neu_aufgebaut", n=anzahl, anzahl=speicher.anzahl_pro_ziffer()))
        return anzahl

    def _vorlagen_bereitstellen() -> None:
        speicher.verzeichnis.mkdir(parents=True, exist_ok=True)
        if konfig.modell_verzeichnis is not None:
            modell.erstausstattung(konfig.modell_verzeichnis, konfig.daten_verzeichnis, archiv, speicher)
        if not konfig.lerneffekt:
            speicher.laden()
            log.info(T("log.lerneffekt_aus"))
            return
        if archiv.anzahl() == 0:
            speicher.laden()
            return
        anzahl = speicher.neu_aufbauen(_lernbilder_aus_archiv())
        log.info(T("log.lerneffekt_an", n=anzahl, anzahl=speicher.anzahl_pro_ziffer()))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # SPRACHE=auto: Protokoll und Sensor in der Sprache von HA (start.py fragt meist schon vorher)
        if konfig.ha_token and not sprache.versucht():
            ha.sprache_uebernehmen(konfig.ha_url, konfig.ha_token)
        log.info(T(
            "log.start", version=__version__, rollen=konfig.anzahl_rollen,
            min_score=f"{konfig.min_score:.2f}", min_abstand=f"{konfig.min_abstand:.2f}",
            max_vorlagen=konfig.max_vorlagen_pro_ziffer, verschiebung=konfig.verschiebung,
            lerneffekt=T("ui.an" if konfig.lerneffekt else "ui.aus"), daten=konfig.daten_verzeichnis,
        ))
        log.info(T("log.sprache", quelle=T(f"log.sprache.{sprache.quelle()}")))
        kamera_text = konfig.kamera or T("log.keine")
        log.info(T(
            "log.kamera",
            kamera=kamera_text if konfig.ha_token else T("log.ohne_ha", kamera=kamera_text),
            verwaltung=T("log.verwaltung_ingress" if konfig.admin_nur_ingress else "log.verwaltung_netz"),
        ))
        _vorlagen_bereitstellen()
        automatik.starten()
        yield
        automatik.stoppen()

    app = FastAPI(title="Wasseruhr-CV", version=__version__, lifespan=lifespan)
    schutz.einrichten(app)
    sprache.einrichten(app)
    app.state.konfig = konfig
    app.state.speicher = speicher
    app.state.archiv = archiv

    def _ziffern_aus_body(daten: bytes) -> tuple[np.ndarray, list[np.ndarray]]:
        try:
            bild = dekodiere_bild(daten)
            return bild, schneide_ziffern(bild, konfig.rois)
        except BildFehler as e:
            raise HTTPException(status_code=400, detail=meldung(e)) from None

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

        log.info(T(
            "log.ablesen", nr=nr, wert="null" if wert is None else f"{wert:.3f}",
            sicher=T("ui.ja" if sicher else "ui.nein"),
            rollen=" ".join(_kurz(e, ok) for e, ok in zip(ergebnisse, sicher_pro_rolle)),
            fehlend=T("log.fehlende_vorlagen", liste=str(fehlende)) if fehlende else "",
        ))
        return nr, {
            "wert": wert,
            "sicher": sicher,
            "ziffern": [e.als_dict() for e in ergebnisse],
            "fehlende_vorlagen": fehlende,
        }

    # Liest selbst in festen Abständen ab und schreibt nach Home Assistant (siehe automatik.py)
    automatik = Automatik(konfig, lambda daten: _ablesen_mit_nr(daten))
    app.state.automatik = automatik

    @app.post("/ablesen")
    async def ablesen(request: Request) -> dict:
        return await run_in_threadpool(_ablesen, await schutz.body_lesen(request, schutz.MAX_BILD_BYTES))

    # ---- POST /kamera-ablesen ------------------------------------------------

    def _kamera_ablesen() -> dict:
        if not konfig.kamera:
            raise HTTPException(status_code=400, detail=T("api.keine_kamera"))
        if not konfig.ha_token:
            raise HTTPException(status_code=400, detail=T("api.kein_ha"))
        try:
            daten = kamera.schnappschuss(konfig.ha_url, konfig.ha_token, konfig.kamera)
        except kamera.KameraFehler as e:
            raise HTTPException(status_code=502, detail=T("api.kamerabild_fehlt", fehler=e)) from None
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
            raise HTTPException(status_code=400, detail=T("api.wert_ungueltig", wert=repr(wert_text), fehler=e)) from None
        aus_verlauf = not daten and ablesung is not None
        if aus_verlauf:
            a = _ablesung(ablesung)
            if a is None:
                raise HTTPException(status_code=404, detail=T("api.ablesung_neu_laden", nr=ablesung))
            daten = a.daten
        _bild, ziffern = _ziffern_aus_body(daten)  # erst prüfen, dann archivieren
        with lern_lock:
            zeitstempel = archiv.speichern(daten, wert)
            gespeichert = speicher.lernen(zeitstempel, soll, ziffern) if konfig.lerneffekt else 0
        anzahl = speicher.anzahl_pro_ziffer()
        log.info(T(
            "log.lernen", wert=f"{wert:.3f}", ziffern="".join(map(str, soll)), gespeichert=gespeichert,
            zusatz="" if konfig.lerneffekt else T("log.nur_archiviert"), anzahl=anzahl,
        ))
        if aus_verlauf:
            _ablesen(daten)  # gleiches Bild sofort neu ablesen -> Lernseite zeigt den Effekt
        return {"gespeichert": gespeichert, "vorlagen_pro_ziffer": anzahl}

    @app.post("/lernen")
    async def lernen(
        request: Request,
        wert: str = Query(..., description="Meter reading shown on the image, e.g. 506.388"),
        ablesung: int | None = Query(
            None, description="Without body: learn the image of this reading (number from the training page)"
        ),
    ) -> dict:
        daten = await schutz.body_lesen(request, schutz.MAX_BILD_BYTES)
        return await run_in_threadpool(_lernen, daten, wert, ablesung)

    # ---- GET /status, /debug.png, /health ----------------------------------

    @app.get("/status")
    def status() -> dict:
        return {
            "vorlagen_pro_ziffer": speicher.anzahl_pro_ziffer(),
            "fehlende_vorlagen": speicher.fehlende_ziffern(),
            "lerneffekt": konfig.lerneffekt,
            "lernbilder": archiv.anzahl(),
            "zaehlerstand": automatik.zustand()["zaehlerstand"],
        }

    @app.get("/debug.png")
    def debug_png(
        request: Request,
        letztes: int = Query(1, description="1 = image of the latest /ablesen call"),
        nr: int | None = Query(None, description="a specific reading instead"),
    ) -> Response:
        a = _ablesung(nr)
        if a is None:
            raise HTTPException(
                status_code=404,
                detail=T("api.noch_keine_ablesung") if nr is None else T("api.ablesung_weg", nr=nr),
            )
        png = debugbild.zeichne(
            a.bild, konfig.rois, a.ziffern, a.ergebnisse, a.sicher_pro_rolle, a.wert, a.sicher,
            sprache=aus_anfrage(request),
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
                automatik_intervall=konfig.intervall_minuten if automatik.aktiv else None,
                zaehlerstand=automatik.zustand()["zaehlerstand"],
                verwaltung=verwaltung.verwaltung_erlaubt(konfig, request),
                sprache=aus_anfrage(request),
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
                automatik=automatik,
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
