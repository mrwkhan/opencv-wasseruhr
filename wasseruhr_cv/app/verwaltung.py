"""Verwaltung (/admin): Lernbilder prüfen, korrigieren und löschen, Vorlagen
ansehen und neu aufbauen, Modell als ZIP exportieren und importieren.

Im Home-Assistant-Add-on ist die Verwaltung standardmäßig nur über Ingress
erreichbar, also nur für in Home Assistant angemeldete Benutzer. Die Lernseite
und die API (/ablesen, /lernen …) bleiben wie bisher im Heimnetz erreichbar."""

from __future__ import annotations

import base64
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from . import modell, schutz, verwaltungsseite
from .erkennung import zerlege_wert
from .konfig import NACHKOMMASTELLEN, Konfig
from .lernbilder import LernbildArchiv
from .vorlagen import ZIFFERN, VorlagenSpeicher
from .automatik import Automatik

AUSSCHNITT_RAND = 12  # px um das Zählwerk beim Vorschaubild


@dataclass
class Kontext:
    konfig: Konfig
    speicher: VorlagenSpeicher
    archiv: LernbildArchiv
    lern_lock: threading.Lock
    neu_aufbauen: Callable[[], int]  # nur mit lern_lock aufrufen
    ablesungen: Callable[[], list]  # Ablesungen im Speicher, neueste zuerst
    version: str
    automatik: Automatik


def verwaltung_erlaubt(konfig: Konfig, request: Request) -> bool:
    if not konfig.admin_nur_ingress:
        return True
    return schutz.ist_ingress(request)


def wert_parsen(wert_text: str, konfig: Konfig) -> float:
    try:
        wert = float(wert_text.strip().replace(",", "."))
        zerlege_wert(wert, konfig.anzahl_rollen, NACHKOMMASTELLEN)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Ungültiger wert={wert_text!r}: {e}") from None
    return wert


def router(k: Kontext) -> APIRouter:
    konfig, archiv, speicher = k.konfig, k.archiv, k.speicher

    def zugang(request: Request) -> None:
        if not verwaltung_erlaubt(konfig, request):
            raise HTTPException(
                status_code=403,
                detail="Die Verwaltung ist nur über Home Assistant erreichbar (Seitenleiste „Wasseruhr“). "
                "Für den Zugriff im Heimnetz die Option admin_nur_ueber_ingress ausschalten.",
            )

    r = APIRouter(prefix="/admin", dependencies=[Depends(zugang)])

    def _zustand(**extra) -> dict:
        return {
            **extra,
            "lernbilder": archiv.anzahl(),
            "vorlagen_pro_ziffer": speicher.anzahl_pro_ziffer(),
            "fehlende_vorlagen": speicher.fehlende_ziffern(),
        }

    def _nach_aenderung() -> dict:
        """Mit Lerneffekt folgen die Vorlagen sofort dem Archiv, ohne bleiben sie eingefroren."""
        if konfig.lerneffekt:
            k.neu_aufbauen()
        return _zustand(vorlagen_neu_aufgebaut=konfig.lerneffekt)

    # ---- Seite & Übersicht --------------------------------------------------

    @r.get("", response_class=HTMLResponse)
    def seite() -> HTMLResponse:
        return HTMLResponse(verwaltungsseite.SEITE, headers={"Cache-Control": "no-store"})

    @r.get("/info")
    def info() -> dict:
        return _zustand(
            version=k.version,
            addon=konfig.ist_addon,
            lerneffekt=konfig.lerneffekt,
            kamera=konfig.kamera,
            kamera_bereit=bool(konfig.kamera and konfig.ha_token),
            erstausstattung=modell.erstausstattung_info(konfig.daten_verzeichnis),
            einstellungen={
                "MIN_SCORE": konfig.min_score,
                "MIN_ABSTAND": konfig.min_abstand,
                "MAX_VORLAGEN_PRO_ZIFFER": konfig.max_vorlagen_pro_ziffer,
                "VERSCHIEBUNG": konfig.verschiebung,
                "ROIS": [list(roi) for roi in konfig.rois],
                "ADMIN_NUR_INGRESS": konfig.admin_nur_ingress,
                "HTTP": konfig.http,
                "HTTPS": konfig.https,
            },
            automatik=k.automatik.zustand(),
        )

    # ---- Automatik -----------------------------------------------------------

    @r.get("/automatik")
    def automatik() -> dict:
        return k.automatik.zustand()

    @r.post("/automatik/jetzt")
    def automatik_jetzt() -> dict:
        """Sofort ablesen, prüfen und nach Home Assistant schreiben."""
        if not (konfig.kamera and konfig.ha_token):
            raise HTTPException(status_code=400, detail="Keine Kamera eingestellt oder kein Zugang zu Home Assistant")
        k.automatik.durchlauf()
        return k.automatik.zustand()

    @r.post("/automatik/zaehlerstand")
    def zaehlerstand_setzen(wert: str = Query(..., description="Richtiger Zählerstand in m³")) -> dict:
        """Von Hand korrigieren, z. B. nach einem Zählertausch."""
        k.automatik.zaehlerstand_setzen(wert_parsen(wert, konfig))
        return k.automatik.zustand()

    @r.get("/ablesungen")
    def ablesungen() -> list[dict]:
        return [
            {"nr": a.nr, "zeit": a.zeit.isoformat(), "wert": a.wert, "sicher": a.sicher}
            for a in k.ablesungen()
        ]

    # ---- Lernbilder ---------------------------------------------------------

    @r.get("/lernbilder")
    def lernbilder() -> list[dict]:
        return [
            {"name": e.name, "zeitstempel": e.zeitstempel, "zeit": e.zeit.isoformat(), "wert": e.wert}
            for e in reversed(archiv.eintraege())
        ]

    @r.get("/lernbilder/{name}")
    def lernbild(name: str, ausschnitt: bool = False) -> Response:
        e = archiv.finden(name)
        if e is None:
            raise HTTPException(status_code=404, detail=f"Lernbild {name} gibt es nicht")
        daten = e.pfad.read_bytes()
        typ = "image/png" if daten.startswith(b"\x89PNG") else "image/jpeg"
        if ausschnitt:
            klein = _zaehlwerk_ausschnitt(daten, konfig.rois)
            if klein is not None:
                daten, typ = klein, "image/jpeg"
        return Response(daten, media_type=typ, headers={"Cache-Control": "private, max-age=600"})

    @r.post("/lernbilder/{name}/loeschen")
    def lernbild_loeschen(name: str) -> dict:
        with k.lern_lock:
            try:
                archiv.loeschen(name)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Lernbild {name} gibt es nicht") from None
            return _nach_aenderung()

    @r.post("/lernbilder/{name}/wert")
    def lernbild_korrigieren(name: str, wert: str = Query(..., description="Richtiger Zählerstand")) -> dict:
        richtig = wert_parsen(wert, konfig)
        with k.lern_lock:
            try:
                neu = archiv.wert_aendern(name, richtig)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"Lernbild {name} gibt es nicht") from None
            return _nach_aenderung() | {"name": neu.name}

    # ---- Vorlagen -----------------------------------------------------------

    @r.get("/vorlagen")
    def vorlagen() -> dict:
        """Alle Vorlagen je Ziffer als kleine PNGs (Base64) – eine Anfrage statt Hunderter."""
        ergebnis: dict[str, list[dict]] = {}
        for ziffer, namen in speicher.namen().items():
            ergebnis[ziffer] = []
            for name in namen:
                bild = speicher.bild(int(ziffer), name)
                if bild is None:
                    continue
                png = cv2.imencode(".png", bild)[1].tobytes()
                ergebnis[ziffer].append({"name": name, "png": base64.b64encode(png).decode("ascii")})
        return ergebnis

    @r.post("/zuruecksetzen")
    def zuruecksetzen() -> dict:
        """Alle Lernbilder und Vorlagen löschen, um ganz neu anzulernen."""
        with k.lern_lock:
            archiv.ersetzen({})
            speicher.ersetzen({z: [] for z in ZIFFERN})
            return _zustand(vorlagen_neu_aufgebaut=False)

    @r.post("/neu-aufbauen")
    def neu_aufbauen() -> dict:
        with k.lern_lock:
            k.neu_aufbauen()
            return _zustand(vorlagen_neu_aufgebaut=True)

    # ---- Export & Import ----------------------------------------------------

    @r.get("/export.zip")
    def export() -> Response:
        with k.lern_lock:
            daten = modell.exportieren(
                archiv,
                konfig.vorlagen_verzeichnis,
                {"version": k.version, "rois": [list(roi) for roi in konfig.rois]},
            )
        dateiname = f"wasseruhr-modell-{datetime.now():%Y%m%d-%H%M}.zip"
        return Response(
            daten,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{dateiname}"', "Cache-Control": "no-store"},
        )

    def _importieren(daten: bytes, modus: str) -> dict:
        try:
            inhalt = modell.zip_lesen(daten)
        except modell.ModellFehler as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        if not inhalt.lernbilder:
            raise HTTPException(
                status_code=400,
                detail="Im ZIP sind keine Lernbilder (lernbilder/<zeitstempel>_<wert>.jpg). "
                "Ein Export aus der Verwaltung oder ein ZIP des data-Ordners passt.",
            )
        with k.lern_lock:
            if modus == "ersetzen":
                neu = archiv.ersetzen(inhalt.lernbilder)
                if inhalt.anzahl_vorlagen and not konfig.lerneffekt:
                    speicher.ersetzen(inhalt.bestand())  # eingefrorene Vorlagen 1:1 übernehmen
                    aufgebaut = False
                else:
                    k.neu_aufbauen()
                    aufgebaut = True
            else:
                neu = archiv.ergaenzen(inhalt.lernbilder)
                aufgebaut = konfig.lerneffekt and neu > 0
                if aufgebaut:
                    k.neu_aufbauen()
            return _zustand(
                modus=modus,
                lernbilder_neu=neu,
                uebersprungen=len(inhalt.uebersprungen),
                vorlagen_neu_aufgebaut=aufgebaut,
            )

    @r.post("/import")
    async def importieren(
        request: Request,
        modus: str = Query("ergaenzen", pattern="^(ergaenzen|ersetzen)$"),
    ) -> dict:
        daten = await schutz.body_lesen(request, modell.MAX_GROESSE)
        return await run_in_threadpool(_importieren, daten, modus)

    return r


def _zaehlwerk_ausschnitt(daten: bytes, rois) -> bytes | None:
    """Nur das Zählwerk (alle ROIs plus Rand) – so ist der Wert in der Liste lesbar."""
    try:
        bild = cv2.imdecode(np.frombuffer(daten, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:  # Pixelgrenze überschritten
        return None
    if bild is None:
        return None
    hoehe, breite = bild.shape[:2]
    x1 = max(0, min(r[0] for r in rois) - AUSSCHNITT_RAND)
    y1 = max(0, min(r[1] for r in rois) - AUSSCHNITT_RAND)
    x2 = min(breite, max(r[2] for r in rois) + AUSSCHNITT_RAND)
    y2 = min(hoehe, max(r[3] for r in rois) + AUSSCHNITT_RAND)
    if x2 <= x1 or y2 <= y1:
        return None
    ok, jpg = cv2.imencode(".jpg", bild[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, 88])
    return jpg.tobytes() if ok else None
