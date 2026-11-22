"""Das "Modell" sind die Lernbilder (Quelle der Wahrheit) plus die daraus
erzeugten Vorlagen. Dieses Modul packt beides in ein ZIP, liest ZIPs bzw.
Verzeichnisse wieder ein und übernimmt beim allerersten Start des
Home-Assistant-Add-ons das mitgelieferte Modell.

Aufbau (ZIP und Verzeichnis gleich):
    modell.json                      Infos zum Export (optional)
    lernbilder/<zeitstempel>_<wert>.jpg
    vorlagen/<ziffer>/<zeitstempel>_r<rolle>.png

Ein beliebiger gemeinsamer Präfix wird toleriert, z. B. ein ZIP des ganzen
data/-Ordners (data/lernbilder/…)."""

from __future__ import annotations

import io
import json
import logging
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

import cv2
import numpy as np

from .erkennung import ZIFFER_BREITE, ZIFFER_HOEHE
from .lernbilder import LernbildArchiv, ist_bild, parse_name
from .sprache import T
from .vorlagen import ZIFFERN, Bestand, Vorlage, VorlagenSpeicher

log = logging.getLogger(__name__)

MARKER = ".modell_erstausstattung.json"
MAX_GROESSE = 300 * 1024 * 1024  # Bytes, für das ZIP und den entpackten Inhalt
FORMAT = 1


class ModellFehler(ValueError):
    pass


@dataclass
class ModellInhalt:
    lernbilder: dict[str, bytes] = field(default_factory=dict)
    vorlagen: dict[int, list[Vorlage]] = field(default_factory=dict)
    uebersprungen: list[str] = field(default_factory=list)

    @property
    def anzahl_vorlagen(self) -> int:
        return sum(len(v) for v in self.vorlagen.values())

    def bestand(self) -> Bestand:
        return {z: sorted(self.vorlagen.get(z, []), key=lambda v: v.name) for z in ZIFFERN}

    def ist_leer(self) -> bool:
        return not self.lernbilder and not self.anzahl_vorlagen


# ---- Lesen -------------------------------------------------------------------


def zip_lesen(daten: bytes) -> ModellInhalt:
    if not daten:
        raise ModellFehler(T("modell.leer"))
    if len(daten) > MAX_GROESSE:
        raise ModellFehler(T("modell.zu_gross", mb=MAX_GROESSE // (1024 * 1024)))
    try:
        zf = zipfile.ZipFile(io.BytesIO(daten))
    except zipfile.BadZipFile:
        raise ModellFehler(T("modell.kein_zip")) from None
    with zf:
        dateien = [i for i in zf.infolist() if not i.is_dir()]
        if sum(i.file_size for i in dateien) > MAX_GROESSE:
            raise ModellFehler(T("modell.entpackt_zu_gross", mb=MAX_GROESSE // (1024 * 1024)))
        try:
            return _einsammeln(
                (PurePosixPath(i.filename).parts, lambda i=i: zf.read(i)) for i in dateien
            )
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as e:
            raise ModellFehler(T("modell.beschaedigt", fehler=e)) from None
        except RuntimeError as e:  # verschlüsselte Einträge
            raise ModellFehler(T("modell.unlesbar", fehler=e)) from None


def verzeichnis_lesen(quelle: Path) -> ModellInhalt:
    return _einsammeln(
        (p.relative_to(quelle).parts, p.read_bytes)
        for p in sorted(quelle.rglob("*")) if p.is_file()
    )


def _einsammeln(eintraege: Iterable[tuple[tuple[str, ...], Callable[[], bytes]]]) -> ModellInhalt:
    inhalt = ModellInhalt()
    for teile, lesen in eintraege:
        pfad = "/".join(teile)
        if any(t.startswith(".") or t == "__MACOSX" for t in teile):
            continue  # macOS-Beiwerk (._*, .DS_Store) still ignorieren
        if teile[-1] == "modell.json":
            continue
        art = _einordnen(teile)
        if art is None:
            inhalt.uebersprungen.append(pfad)
            continue
        if art == "lernbild":
            name, daten = teile[-1], lesen()
            if parse_name(name) is None or not ist_bild(daten):
                inhalt.uebersprungen.append(pfad)
                continue
            inhalt.lernbilder[name] = daten
        else:
            ziffer, name = int(teile[-2]), teile[-1]
            try:
                bild = cv2.imdecode(np.frombuffer(lesen(), np.uint8), cv2.IMREAD_GRAYSCALE)
            except cv2.error:  # Pixelgrenze überschritten
                bild = None
            if bild is None:
                inhalt.uebersprungen.append(pfad)
                continue
            if bild.shape != (ZIFFER_HOEHE, ZIFFER_BREITE):
                bild = cv2.resize(bild, (ZIFFER_BREITE, ZIFFER_HOEHE), interpolation=cv2.INTER_AREA)
            inhalt.vorlagen.setdefault(ziffer, []).append(Vorlage(name, bild))
    if inhalt.uebersprungen:
        log.warning(T("log.modell_uebersprungen", liste=", ".join(inhalt.uebersprungen[:10])))
    return inhalt


def _einordnen(teile: tuple[str, ...]) -> str | None:
    if len(teile) >= 2 and teile[-2] == "lernbilder":
        return "lernbild"
    if (
        len(teile) >= 3
        and teile[-3] == "vorlagen"
        and teile[-2] in {str(z) for z in ZIFFERN}
        and teile[-1].lower().endswith(".png")
    ):
        return "vorlage"
    return None


# ---- Schreiben ---------------------------------------------------------------


def exportieren(archiv: LernbildArchiv, vorlagen_verzeichnis: Path, info: dict) -> bytes:
    """ZIP mit allen Lernbildern und Vorlagen. JPEG/PNG sind schon komprimiert,
    daher ohne erneute Kompression (schont die CPU des HA Green)."""
    puffer = io.BytesIO()
    lernbilder = archiv.eintraege()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_STORED) as z:
        anzahl_vorlagen = 0
        for e in lernbilder:
            z.write(e.pfad, f"lernbilder/{e.name}")
        for ziffer in ZIFFERN:
            ordner = vorlagen_verzeichnis / str(ziffer)
            if not ordner.is_dir():
                continue
            for p in sorted(ordner.glob("*.png")):
                if p.is_file() and not p.name.startswith("."):
                    z.write(p, f"vorlagen/{ziffer}/{p.name}")
                    anzahl_vorlagen += 1
        z.writestr(
            "modell.json",
            json.dumps(
                {
                    "format": FORMAT,
                    "erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "lernbilder": len(lernbilder),
                    "vorlagen": anzahl_vorlagen,
                    **info,
                },
                ensure_ascii=False,
                indent=2,
            ),
            compress_type=zipfile.ZIP_DEFLATED,
        )
    return puffer.getvalue()


def erstausstattung(
    quelle: Path, daten_verzeichnis: Path, archiv: LernbildArchiv, speicher: VorlagenSpeicher
) -> dict | None:
    """Übernimmt das mitgelieferte Modell genau einmal – und nur in ein leeres
    Datenverzeichnis. Gelerntes wird also nie von einem Add-on-Update
    überschrieben. Rückgabe: Inhalt der Markierungsdatei, None = nichts zu tun."""
    marker = daten_verzeichnis / MARKER
    if marker.exists():
        return None
    inhalt = verzeichnis_lesen(quelle) if quelle.is_dir() else ModellInhalt()
    if inhalt.ist_leer():
        # Der Normalfall bei Installation aus dem Repository: kein Modell im Image.
        # Keine Markierung, damit ein später eingebautes Modell noch greift.
        log.debug(T("log.kein_modell", pfad=quelle))
        return None
    vorhanden = archiv.anzahl() > 0 or any(
        p.name[:1] != "." for p in speicher.verzeichnis.glob("*/*.png")
    )
    if vorhanden:
        info = {"uebernommen": False, "grund": "daten_vorhanden"}
        log.info(T("log.modell_nicht_uebernommen"))
    else:
        archiv.ersetzen(inhalt.lernbilder)
        speicher.ersetzen(inhalt.bestand())
        info = {
            "uebernommen": True,
            "lernbilder": len(inhalt.lernbilder),
            "vorlagen": inhalt.anzahl_vorlagen,
        }
        log.info(T("log.modell_uebernommen", lernbilder=len(inhalt.lernbilder), vorlagen=inhalt.anzahl_vorlagen))
    info["zeit"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    daten_verzeichnis.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(info, ensure_ascii=False))
    return info


def erstausstattung_info(daten_verzeichnis: Path) -> dict | None:
    try:
        return json.loads((daten_verzeichnis / MARKER).read_text())
    except (OSError, ValueError):
        return None
