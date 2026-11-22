"""Vorlagen-Speicher: PNGs unter <verzeichnis>/<ziffer>/<zeitstempel>_r<rolle>.png,
im Speicher als Graubilder je Ziffer 0–9."""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import cv2
import numpy as np

from .erkennung import ZIFFER_BREITE, ZIFFER_HOEHE, ist_kontrastlos, korrelation

log = logging.getLogger(__name__)

ZIFFERN = range(10)
DUPLIKAT_KORRELATION = 0.97


@dataclass(frozen=True)
class Vorlage:
    name: str  # "<zeitstempel>_r<rolle>.png" – alphabetisch = chronologisch
    bild: np.ndarray


Bestand = dict[int, list[Vorlage]]


class VorlagenSpeicher:
    def __init__(self, verzeichnis: Path, max_pro_ziffer: int):
        self.verzeichnis = Path(verzeichnis)
        self.max_pro_ziffer = max_pro_ziffer
        self._lock = threading.Lock()
        self._vorlagen: Bestand = _leer()

    # ---- Lesen -----------------------------------------------------------

    def laden(self) -> None:
        """Alle Vorlagen von der Platte in den Speicher laden."""
        with self._lock:
            self._vorlagen = _von_platte(self.verzeichnis)
        log.info("Vorlagen geladen: %s", self.anzahl_pro_ziffer())

    def momentaufnahme(self) -> dict[int, list[np.ndarray]]:
        """Kopie der Listen (Bilder werden nie verändert) für lock-freies Matching."""
        with self._lock:
            return {z: [v.bild for v in liste] for z, liste in self._vorlagen.items()}

    def anzahl_pro_ziffer(self) -> dict[str, int]:
        return {str(z): len(liste) for z, liste in self._vorlagen.items()}

    def fehlende_ziffern(self) -> list[int]:
        return [z for z, liste in self._vorlagen.items() if not liste]

    def namen(self) -> dict[str, list[str]]:
        """Dateinamen je Ziffer, älteste zuerst."""
        with self._lock:
            return {str(z): [v.name for v in liste] for z, liste in self._vorlagen.items()}

    def bild(self, ziffer: int, name: str) -> np.ndarray | None:
        with self._lock:
            return next((v.bild for v in self._vorlagen.get(ziffer, []) if v.name == name), None)

    # ---- Schreiben -------------------------------------------------------

    def lernen(self, zeitstempel: str, ziffern: Sequence[int], bilder: Sequence[np.ndarray]) -> int:
        """Nimmt die Ziffern eines Bildes als Vorlagen auf (siehe _aufnehmen),
        schreibt/löscht die PNGs und lädt danach neu.
        Rückgabe: Anzahl neu gespeicherter Vorlagen."""
        with self._lock:
            bestand = {z: list(liste) for z, liste in self._vorlagen.items()}
            neu, entfernt = self._aufnehmen(bestand, zeitstempel, ziffern, bilder)
            sofort_entfernt = {(z, v.name) for z, v in entfernt}
            gespeichert = 0
            for z, v in neu:
                if (z, v.name) not in sofort_entfernt:
                    _schreiben(self.verzeichnis, z, v)
                    gespeichert += 1
            for z, v in entfernt:
                (self.verzeichnis / str(z) / v.name).unlink(missing_ok=True)
                log.info("Älteste Vorlage für Ziffer %d gelöscht: %s", z, v.name)
            self._vorlagen = _von_platte(self.verzeichnis)
        return gespeichert

    def neu_aufbauen(self, lernbilder: Iterable[tuple[str, Sequence[int], Sequence[np.ndarray]]]) -> int:
        """Ersetzt alle Vorlagen durch die, die beim Lernen der übergebenen
        Bilder (älteste zuerst) entstanden wären. Rückgabe: Anzahl Bilder."""
        bestand = _leer()
        anzahl = 0
        for zeitstempel, ziffern, bilder in lernbilder:
            self._aufnehmen(bestand, zeitstempel, ziffern, bilder)
            anzahl += 1
        self.ersetzen(bestand)
        return anzahl

    def ersetzen(self, bestand: Bestand) -> None:
        """Ersetzt alle Vorlagen auf der Platte atomar durch `bestand` und lädt neu."""
        with self._lock:
            neu_dir = self.verzeichnis.with_name(self.verzeichnis.name + ".neu")
            alt_dir = self.verzeichnis.with_name(self.verzeichnis.name + ".alt")
            shutil.rmtree(neu_dir, ignore_errors=True)
            shutil.rmtree(alt_dir, ignore_errors=True)
            for z in ZIFFERN:
                (neu_dir / str(z)).mkdir(parents=True, exist_ok=True)
                for v in bestand.get(z, []):
                    _schreiben(neu_dir, z, v)
            if self.verzeichnis.exists():
                self.verzeichnis.rename(alt_dir)
            neu_dir.rename(self.verzeichnis)
            shutil.rmtree(alt_dir, ignore_errors=True)
            self._vorlagen = _von_platte(self.verzeichnis)

    def _aufnehmen(
        self, bestand: Bestand, zeitstempel: str, ziffern: Sequence[int], bilder: Sequence[np.ndarray]
    ) -> tuple[list[tuple[int, Vorlage]], list[tuple[int, Vorlage]]]:
        """Fügt jede Ziffer in `bestand` ein, außer sie ist einer vorhandenen
        Vorlage derselben Ziffer fast identisch (Korrelation > 0.97), und kürzt
        danach je Ziffer auf max_pro_ziffer (älteste fliegen raus).
        Rückgabe: (hinzugefügt, entfernt) als Listen von (ziffer, Vorlage)."""
        if len(ziffern) != len(bilder):
            raise ValueError("ziffern und bilder müssen gleich lang sein")
        neu, entfernt = [], []
        for rolle, (z, bild) in enumerate(zip(ziffern, bilder), start=1):
            if ist_kontrastlos(bild):
                log.warning("Rolle %d (Ziffer %d): kein Kontrast im Bild, nicht gelernt", rolle, z)
                continue
            aehnlichste = max((korrelation(bild, v.bild) for v in bestand[z]), default=-1.0)
            if aehnlichste > DUPLIKAT_KORRELATION:
                log.debug("Rolle %d (Ziffer %d): Duplikat (%.3f), nicht gespeichert", rolle, z, aehnlichste)
                continue
            v = Vorlage(f"{zeitstempel}_r{rolle}.png", bild)
            bestand[z].append(v)
            neu.append((z, v))
        for z in set(ziffern):
            bestand[z].sort(key=lambda v: v.name)
            while len(bestand[z]) > self.max_pro_ziffer:
                entfernt.append((z, bestand[z].pop(0)))
        return neu, entfernt


def _leer() -> Bestand:
    return {z: [] for z in ZIFFERN}


def _schreiben(verzeichnis: Path, ziffer: int, v: Vorlage) -> None:
    ordner = verzeichnis / str(ziffer)
    ordner.mkdir(parents=True, exist_ok=True)
    ok, png = cv2.imencode(".png", v.bild)
    if not ok:
        raise RuntimeError("PNG-Kodierung fehlgeschlagen")
    (ordner / v.name).write_bytes(png.tobytes())


def _von_platte(verzeichnis: Path) -> Bestand:
    bestand = _leer()
    for z in ZIFFERN:
        ordner = verzeichnis / str(z)
        if not ordner.is_dir():
            continue
        for pfad in sorted(p for p in ordner.glob("*.png") if p.is_file() and not p.name.startswith(".")):
            bild = cv2.imdecode(np.frombuffer(pfad.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            if bild is None:
                log.warning("Vorlage nicht lesbar, ignoriert: %s", pfad)
                continue
            if bild.shape != (ZIFFER_HOEHE, ZIFFER_BREITE):
                bild = cv2.resize(bild, (ZIFFER_BREITE, ZIFFER_HOEHE), interpolation=cv2.INTER_AREA)
            if ist_kontrastlos(bild):
                log.warning("Kontrastlose Vorlage ignoriert (würde alles treffen): %s", pfad)
                continue
            bestand[z].append(Vorlage(pfad.name, bild))
    return bestand
