"""Automatik: liest in festen Abständen das Kamerabild aus Home Assistant ab,
prüft den Wert auf Plausibilität und schreibt nur sichere, plausible Werte nach
Home Assistant – als Sensor (Energie-Dashboard) und optional in einen
input_number-Helfer.

Plausibilität: Ein Wasserzähler zählt nur vorwärts und nur so schnell, wie
Wasser fließen kann. Verglichen wird mit dem zuletzt übernommenen Stand. Ist ein
input_number eingestellt und wurde dort von Hand ein anderer Wert gesetzt, gilt
dieser als Korrektur."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import ha, kamera
from .erkennung import BildFehler
from .konfig import Konfig

log = logging.getLogger(__name__)

UEBERNOMMEN = "übernommen"
UNVERAENDERT = "unverändert"
VERWORFEN = "verworfen"
FEHLER = "fehler"
GESETZT = "gesetzt"

ERSTE_ABLESUNG_NACH_S = 15


@dataclass(frozen=True)
class Regeln:
    max_m3_pro_stunde: float
    toleranz_m3: float
    alle_ziffern_gelernt: bool
    min_score: float
    min_abstand: float


def pruefen(
    ergebnis: dict, bisher: float | None, seit: datetime | None, jetzt: datetime, regeln: Regeln
) -> tuple[str, str]:
    """Entscheidet über eine Ablesung. Rückgabe: (Status, Begründung)."""
    wert = ergebnis.get("wert")
    if wert is None:
        return VERWORFEN, "noch keine Vorlagen gelernt"
    text = f"{wert:.3f}"
    if not ergebnis.get("sicher"):
        schwach = [
            f"R{z['rolle']}={z['ziffer']} ({z['score']}, 2.: {z['zweitbeste']} {z['score2']})"
            for z in ergebnis.get("ziffern", [])
            if z["ziffer"] is None or z["score2"] is None
            or z["score"] < regeln.min_score or z["score"] - z["score2"] < regeln.min_abstand
        ]
        return VERWORFEN, f"unsicher {text} – {', '.join(schwach)}"
    if regeln.alle_ziffern_gelernt and ergebnis.get("fehlende_vorlagen"):
        ziffern = ", ".join(map(str, ergebnis["fehlende_vorlagen"]))
        return VERWORFEN, f"{text} nicht übernommen – noch keine Vorlagen für Ziffer {ziffern}"
    if bisher is None or bisher <= 0:
        return UEBERNOMMEN, "erster sicherer Wert"
    diff = round(wert - bisher, 3)
    if diff == 0:
        return UNVERAENDERT, ""
    if diff < 0:
        if -diff <= regeln.toleranz_m3:
            return UNVERAENDERT, f"kleine Rückwärts-Abweichung ({diff:.3f} m³) ignoriert"
        return VERWORFEN, f"{text} ist kleiner als der bisherige Stand {bisher:.3f}"
    minuten = max(0.0, (jetzt - seit).total_seconds() / 60) if seit else 0.0
    if diff > regeln.max_m3_pro_stunde * minuten / 60 + regeln.toleranz_m3:
        return VERWORFEN, f"{text}: +{diff:.3f} m³ in {round(minuten)} min ist unplausibel"
    return UEBERNOMMEN, f"+{diff:.3f} m³"


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


class Automatik:
    def __init__(self, konfig: Konfig, ablesen: Callable[[bytes], tuple[int, dict]]):
        self.konfig = konfig
        self._ablesen = ablesen
        self._datei = konfig.daten_verzeichnis / "zaehlerstand.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stand, self._stand_zeit = self._laden()
        self._letzter: dict | None = None
        self._helfer_fehlt: bool | None = None  # None = noch nicht geprüft / HA nicht erreichbar
        self.regeln = Regeln(
            konfig.max_m3_pro_stunde, konfig.toleranz_m3, konfig.alle_ziffern_gelernt,
            konfig.min_score, konfig.min_abstand,
        )

    # ---- Zeitsteuerung ---------------------------------------------------------

    @property
    def aktiv(self) -> bool:
        return self.konfig.automatik_moeglich

    def starten(self) -> None:
        if not self.aktiv:
            grund = (
                "Intervall 0" if self.konfig.intervall_minuten == 0
                else "keine Kamera eingestellt" if not self.konfig.kamera
                else "kein Zugang zu Home Assistant"
            )
            log.info("Automatik aus (%s)", grund)
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._schleife, name="automatik", daemon=True)
        self._thread.start()
        log.info(
            "Automatik an: %s alle %d min -> %s",
            self.konfig.kamera, self.konfig.intervall_minuten,
            ", ".join(filter(None, [self.konfig.sensor, self.konfig.input_number])) or "keine Entität",
        )

    def stoppen(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None

    def _schleife(self) -> None:
        if self._stop.wait(ERSTE_ABLESUNG_NACH_S):
            return
        while True:
            try:
                self.durchlauf()
            except Exception:  # die Schleife darf nie sterben
                log.exception("Automatik: unerwarteter Fehler")
            if self._stop.wait(self.konfig.intervall_minuten * 60):
                return

    # ---- Ein Durchlauf -------------------------------------------------------------

    def durchlauf(self) -> dict:
        with self._lock:
            jetzt = _jetzt()
            if not (self.konfig.kamera and self.konfig.ha_token):
                return self._melden(jetzt, FEHLER, "Kamera oder Zugang zu Home Assistant fehlt")
            try:
                bild = kamera.schnappschuss(self.konfig.ha_url, self.konfig.ha_token, self.konfig.kamera)
                nr, ergebnis = self._ablesen(bild)
            except (kamera.KameraFehler, BildFehler) as e:
                return self._melden(jetzt, FEHLER, str(e))
            except Exception as e:  # z. B. HTTPException aus dem Ablesen (ROI außerhalb des Bildes)
                return self._melden(jetzt, FEHLER, getattr(e, "detail", None) or str(e))

            bisher, seit = self._basis()
            status, grund = pruefen(ergebnis, bisher, seit, jetzt, self.regeln)
            if status == UEBERNOMMEN:
                self._merken(ergebnis["wert"], jetzt)
            elif status == UNVERAENDERT:
                self._merken(bisher, jetzt)  # bestätigt: Zeitbasis für die Anstiegsprüfung
            return self._melden(jetzt, status, grund, nr=nr, erkannt=ergebnis.get("wert"))

    def zaehlerstand_setzen(self, wert: float) -> dict:
        """Von Hand korrigieren, z. B. nach einem Zählertausch."""
        with self._lock:
            jetzt = _jetzt()
            self._merken(round(wert, 3), jetzt)
            return self._melden(jetzt, GESETZT, "von Hand gesetzt")

    # ---- Stand & Basis -----------------------------------------------------------

    def _basis(self) -> tuple[float | None, datetime | None]:
        """Vergleichswert. Ein von Hand geänderter input_number gilt als Korrektur."""
        if self.konfig.input_number:
            z, wert = None, None
            try:
                z = ha.zustand(self.konfig.ha_url, self.konfig.ha_token, self.konfig.input_number)
                self._helfer_fehlt = z is None
                wert = float(z["state"]) if z else None
            except (ha.HAFehler, ValueError, KeyError, TypeError) as e:
                log.warning("Automatik: %s nicht lesbar (%s) – nutze gespeicherten Stand", self.konfig.input_number, e)
            if wert is not None and wert > 0 and (self._stand is None or round(wert - self._stand, 3) != 0):
                try:
                    geaendert = datetime.fromisoformat(z["last_changed"])
                except (KeyError, TypeError, ValueError):
                    geaendert = None
                # Nur eine Änderung NACH dem letzten bestätigten Stand ist eine Korrektur –
                # sonst würde ein dauerhaft fehlschlagendes Schreiben den Stand hin- und herspringen lassen.
                if self._stand is None or (geaendert is not None and self._stand_zeit is not None and geaendert > self._stand_zeit):
                    log.info("Automatik: %s steht auf %.3f – als Korrektur übernommen", self.konfig.input_number, wert)
                    self._merken(wert, geaendert or _jetzt())
        return self._stand, self._stand_zeit

    def _merken(self, wert: float | None, zeit: datetime) -> None:
        self._stand, self._stand_zeit = wert, zeit
        try:
            self._datei.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._datei.with_suffix(".tmp")
            tmp.write_text(json.dumps({"wert": wert, "zeit": zeit.isoformat()}))
            tmp.replace(self._datei)
        except OSError as e:
            log.warning("Automatik: Zählerstand nicht gespeichert (%s)", e)

    def _laden(self) -> tuple[float | None, datetime | None]:
        try:
            d = json.loads(self._datei.read_text())
            return float(d["wert"]), datetime.fromisoformat(d["zeit"])
        except (OSError, ValueError, KeyError, TypeError):
            return None, None

    # ---- Melden & nach Home Assistant schreiben ------------------------------------

    def _melden(self, jetzt: datetime, status: str, grund: str, nr: int | None = None,
                erkannt: float | None = None) -> dict:
        uebertragen = self._veroeffentlichen(jetzt, status, grund, erkannt)
        self._letzter = {
            "zeit": jetzt.isoformat(), "status": status, "grund": grund, "nr": nr,
            "erkannt": erkannt, "zaehlerstand": self._stand, "uebertragen": uebertragen,
        }
        stufe = logging.WARNING if status == FEHLER else logging.INFO
        log.log(stufe, "Automatik: %s%s%s | Zählerstand %s",
                status, f" – {grund}" if grund else "", f" (Ablesung #{nr})" if nr else "",
                "–" if self._stand is None else f"{self._stand:.3f}")
        return self._letzter

    def _veroeffentlichen(self, jetzt: datetime, status: str, grund: str, erkannt: float | None) -> str:
        k = self.konfig
        if not k.ha_token or self._stand is None:
            return ""
        fehler = []
        if k.sensor:
            attribute = {
                "unit_of_measurement": "m³",
                "device_class": "water",
                "state_class": "total_increasing",
                "icon": "mdi:water",
                "friendly_name": "Wasserzähler",
                "letzte_pruefung": jetzt.isoformat(),
                "status": status,
                "grund": grund,
                "erkannt": erkannt,
                "quelle": "Wasseruhr-CV",
            }
            try:
                ha.zustand_setzen(k.ha_url, k.ha_token, k.sensor, f"{self._stand:.3f}", attribute)
            except ha.HAFehler as e:
                fehler.append(f"{k.sensor}: {e}")
        if k.input_number:
            # Home Assistant meldet einen Dienstaufruf für eine fehlende Entität nicht als
            # Fehler – deshalb selbst prüfen, statt "ok" zu melden, obwohl nichts ankam.
            vorher = self._helfer_fehlt
            if status == GESETZT or self._helfer_fehlt is None:
                self._helfer_fehlt = self._helfer_fehlt_pruefen()
            if self._helfer_fehlt:
                meldung = (f"{k.input_number} gibt es in Home Assistant nicht – Helfer anlegen "
                           "(Einstellungen → Geräte & Dienste → Helfer → Nummer) oder Option input_number leeren")
                if not vorher:  # nur beim ersten Erkennen ins Protokoll, nicht alle 5 Minuten
                    log.warning("Automatik: %s", meldung)
                return "; ".join([*fehler, meldung])
            if status in (UEBERNOMMEN, GESETZT):
                try:
                    ha.dienst(k.ha_url, k.ha_token, "input_number", "set_value",
                              {"entity_id": k.input_number, "value": self._stand})
                except ha.HAFehler as e:
                    fehler.append(f"{k.input_number}: {e}")
        for f in fehler:
            log.warning("Automatik: Übertragen fehlgeschlagen – %s", f)
        return "; ".join(fehler) if fehler else "ok"

    def _helfer_fehlt_pruefen(self) -> bool | None:
        try:
            return ha.zustand(self.konfig.ha_url, self.konfig.ha_token, self.konfig.input_number) is None
        except ha.HAFehler:
            return None  # unklar – dann trotzdem schreiben und einen Fehler melden lassen

    # ---- Anzeige -------------------------------------------------------------------

    def zustand(self) -> dict:
        k = self.konfig
        return {
            "aktiv": self.aktiv,
            "intervall_minuten": k.intervall_minuten,
            "kamera": k.kamera,
            "sensor": k.sensor,
            "input_number": k.input_number,
            "input_number_fehlt": bool(k.input_number) and self._helfer_fehlt is True,
            "zaehlerstand": self._stand,
            "zaehlerstand_zeit": self._stand_zeit.isoformat() if self._stand_zeit else None,
            "letzter": self._letzter,
            "regeln": {
                "max_m3_pro_stunde": k.max_m3_pro_stunde,
                "toleranz_m3": k.toleranz_m3,
                "alle_ziffern_gelernt": k.alle_ziffern_gelernt,
            },
        }
