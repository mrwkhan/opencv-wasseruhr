"""Archiv aller an /lernen geschickten Bilder: <verzeichnis>/<zeitstempel>_<wert>.jpg.

Die Bilder werden byte-genau so abgelegt, wie sie empfangen wurden. Aus dem
Archiv lassen sich die Vorlagen jederzeit neu aufbauen (z. B. nach einer
ROI-Änderung). Der Zeitstempel ist die Identität eines Lernbildes, der Wert im
Dateinamen lässt sich nachträglich korrigieren."""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

log = logging.getLogger(__name__)

ZEITSTEMPEL_FORMAT = "%Y%m%dT%H%M%S%fZ"  # UTC -> alphabetisch = chronologisch
ENDUNGEN = {".jpg", ".jpeg", ".png", ".bild"}


@dataclass(frozen=True)
class Lernbild:
    zeitstempel: str
    wert: float
    pfad: Path

    @property
    def name(self) -> str:
        return self.pfad.name

    @property
    def zeit(self) -> datetime:
        return datetime.strptime(self.zeitstempel, ZEITSTEMPEL_FORMAT).replace(tzinfo=timezone.utc)


def parse_name(name: str) -> tuple[str, float] | None:
    """'<zeitstempel>_<wert>.<endung>' -> (zeitstempel, wert), sonst None."""
    pfad = Path(name)
    if pfad.name != name or name.startswith(".") or pfad.suffix.lower() not in ENDUNGEN:
        return None
    try:
        zeitstempel, wert_text = pfad.stem.split("_", 1)
        datetime.strptime(zeitstempel, ZEITSTEMPEL_FORMAT)
        wert = float(wert_text)
    except ValueError:
        return None
    if not wert >= 0:  # auch NaN
        return None
    return zeitstempel, wert


def ist_bild(daten: bytes) -> bool:
    return _endung(daten) != ".bild"


class LernbildArchiv:
    def __init__(self, verzeichnis: Path):
        self.verzeichnis = Path(verzeichnis)
        self._lock = threading.Lock()
        self._letzter: datetime | None = None

    def speichern(self, daten: bytes, wert: float) -> str:
        """Legt das Bild ab und gibt seinen (eindeutigen) Zeitstempel zurück."""
        with self._lock:
            zeitstempel = self._neuer_zeitstempel()
            self.verzeichnis.mkdir(parents=True, exist_ok=True)
            pfad = self.verzeichnis / f"{zeitstempel}_{wert:.3f}{_endung(daten)}"
            pfad.write_bytes(daten)
        log.info("Lernbild archiviert: %s", pfad.name)
        return zeitstempel

    def eintraege(self) -> list[Lernbild]:
        """Alle lesbaren Archiv-Einträge, älteste zuerst."""
        if not self.verzeichnis.is_dir():
            return []
        eintraege = []
        for pfad in sorted(p for p in self.verzeichnis.iterdir() if p.is_file() and not p.name.startswith(".")):
            try:
                zeitstempel, wert_text = pfad.stem.split("_", 1)
                datetime.strptime(zeitstempel, ZEITSTEMPEL_FORMAT)
                wert = float(wert_text)
            except ValueError:
                log.warning("Lernbild mit unbekanntem Dateinamen ignoriert: %s", pfad.name)
                continue
            eintraege.append(Lernbild(zeitstempel, wert, pfad))
        return eintraege

    def anzahl(self) -> int:
        return len(self.eintraege())

    def finden(self, name: str) -> Lernbild | None:
        """Nur Namen, die tatsächlich im Archiv liegen – kein Pfad von außen."""
        return next((e for e in self.eintraege() if e.name == name), None)

    # ---- Verwaltung --------------------------------------------------------

    def loeschen(self, name: str) -> Lernbild:
        with self._lock:
            e = self.finden(name)
            if e is None:
                raise KeyError(name)
            e.pfad.unlink()
        log.info("Lernbild gelöscht: %s", name)
        return e

    def wert_aendern(self, name: str, wert: float) -> Lernbild:
        """Korrigiert den Wert im Dateinamen, Zeitstempel und Bild bleiben."""
        with self._lock:
            e = self.finden(name)
            if e is None:
                raise KeyError(name)
            neu = e.pfad.with_name(f"{e.zeitstempel}_{wert:.3f}{e.pfad.suffix}")
            e.pfad.rename(neu)
        log.info("Lernbild korrigiert: %s -> %s", name, neu.name)
        return Lernbild(e.zeitstempel, wert, neu)

    def ergaenzen(self, dateien: Mapping[str, bytes]) -> int:
        """Übernimmt Lernbilder, deren Zeitstempel es noch nicht gibt.
        Rückgabe: Anzahl neu übernommener Bilder."""
        with self._lock:
            vorhanden = {e.zeitstempel for e in self.eintraege()}
            self.verzeichnis.mkdir(parents=True, exist_ok=True)
            neu = 0
            for name, daten in sorted(dateien.items()):
                zeitstempel = parse_name(name)[0]
                if zeitstempel in vorhanden:
                    continue
                (self.verzeichnis / name).write_bytes(daten)
                vorhanden.add(zeitstempel)
                neu += 1
            self._letzter = None  # streng monotone Zeitstempel neu bestimmen
        log.info("Lernbilder ergänzt: %d neu, %d schon vorhanden", neu, len(dateien) - neu)
        return neu

    def ersetzen(self, dateien: Mapping[str, bytes]) -> int:
        """Ersetzt das komplette Archiv (atomar über ein Nachbarverzeichnis)."""
        with self._lock:
            neu_dir = self.verzeichnis.with_name(self.verzeichnis.name + ".neu")
            alt_dir = self.verzeichnis.with_name(self.verzeichnis.name + ".alt")
            shutil.rmtree(neu_dir, ignore_errors=True)
            shutil.rmtree(alt_dir, ignore_errors=True)
            neu_dir.mkdir(parents=True)
            for name, daten in dateien.items():
                (neu_dir / name).write_bytes(daten)
            if self.verzeichnis.exists():
                self.verzeichnis.rename(alt_dir)
            neu_dir.rename(self.verzeichnis)
            shutil.rmtree(alt_dir, ignore_errors=True)
            self._letzter = None
        log.info("Lernbild-Archiv ersetzt: %d Bilder", len(dateien))
        return len(dateien)

    def _neuer_zeitstempel(self) -> str:
        if self._letzter is None:
            self._letzter = max(
                (datetime.strptime(e.zeitstempel, ZEITSTEMPEL_FORMAT).replace(tzinfo=timezone.utc)
                 for e in self.eintraege()),
                default=datetime.min.replace(tzinfo=timezone.utc),
            )
        # streng monoton, auch wenn die Uhr zurückspringt
        jetzt = max(datetime.now(timezone.utc), self._letzter + timedelta(microseconds=1))
        self._letzter = jetzt
        return jetzt.strftime(ZEITSTEMPEL_FORMAT)


def _endung(daten: bytes) -> str:
    if daten.startswith(b"\xff\xd8"):
        return ".jpg"
    if daten.startswith(b"\x89PNG"):
        return ".png"
    return ".bild"
