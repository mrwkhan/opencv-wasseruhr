"""Konfiguration über Umgebungsvariablen."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Zählwerk 640x480 (OV3660-Snapshot): 8 Rollen, je [x1, y1, x2, y2] in Pixeln.
STANDARD_ROIS: list[tuple[int, int, int, int]] = [
    (130, 144, 162, 196),
    (173, 144, 205, 196),
    (216, 144, 248, 196),
    (260, 144, 292, 196),
    (304, 144, 336, 196),
    (347, 144, 379, 196),
    (391, 144, 423, 196),
    (435, 144, 467, 196),
]

NACHKOMMASTELLEN = 3


class KonfigFehler(ValueError):
    pass


@dataclass(frozen=True)
class Konfig:
    rois: tuple[tuple[int, int, int, int], ...] = tuple(STANDARD_ROIS)
    min_score: float = 0.70
    min_abstand: float = 0.08
    max_vorlagen_pro_ziffer: int = 30
    verschiebung: int = 3
    daten_verzeichnis: Path = Path("/data")
    lerneffekt: bool = True
    # Mitgeliefertes Modell (Home-Assistant-Add-on): wird beim allerersten Start
    # in ein leeres Datenverzeichnis übernommen.
    modell_verzeichnis: Path | None = None
    # Kamera-Entität für "Kamera jetzt ablesen" über die Home-Assistant-API
    kamera: str | None = None
    ha_url: str = "http://supervisor/core/api"
    ha_token: str | None = field(default=None, repr=False)
    # Verwaltung (/admin) nur über HA-Ingress, d. h. nur für angemeldete HA-Benutzer
    admin_nur_ingress: bool = False
    ist_addon: bool = False

    # Automatik: Kamerabild alle N Minuten ablesen und nach Home Assistant schreiben
    intervall_minuten: int = 5  # 0 = keine automatische Ablesung
    sensor: str | None = "sensor.wasseruhr_cv_zaehlerstand"
    input_number: str | None = None
    max_m3_pro_stunde: float = 3.0  # schnellerer Anstieg = Lesefehler
    toleranz_m3: float = 0.002  # kleine Rückwärts-Abweichung still ignorieren
    alle_ziffern_gelernt: bool = True  # erst schreiben, wenn 0–9 alle gelernt sind

    # Erreichbarkeit: Port 8099 dient immer Ingress & internem Netz (im Add-on
    # nicht nach außen freigegeben). Zusätzlich optional HTTP und HTTPS fürs Heimnetz.
    port: int = 8099
    http: bool = False
    http_port: int = 8080
    https: bool = False
    https_port: int = 8443
    zertifikat: str = "fullchain.pem"  # relativ zu ssl_verzeichnis oder absolut
    schluessel: str = "privkey.pem"
    ssl_verzeichnis: Path = Path("/ssl")

    @property
    def vorlagen_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "vorlagen"

    @property
    def lernbilder_verzeichnis(self) -> Path:
        return self.daten_verzeichnis / "lernbilder"

    @property
    def anzahl_rollen(self) -> int:
        return len(self.rois)

    @classmethod
    def aus_umgebung(cls, env: dict[str, str] | None = None) -> "Konfig":
        env = dict(os.environ if env is None else env)
        konfig = cls(
            rois=_parse_rois(env.get("ROIS")),
            min_score=_parse_zahl(env, "MIN_SCORE", 0.70, float),
            min_abstand=_parse_zahl(env, "MIN_ABSTAND", 0.08, float),
            max_vorlagen_pro_ziffer=_parse_zahl(env, "MAX_VORLAGEN_PRO_ZIFFER", 30, int),
            verschiebung=_parse_zahl(env, "VERSCHIEBUNG", 3, int),
            daten_verzeichnis=Path(env.get("DATA_DIR") or "/data"),
            lerneffekt=_parse_schalter(env, "LERNEFFEKT", True),
            modell_verzeichnis=Path(env["MODELL_DIR"]) if (env.get("MODELL_DIR") or "").strip() else None,
            kamera=(env.get("KAMERA") or "").strip() or None,
            ha_url=(env.get("HA_URL") or "").strip() or "http://supervisor/core/api",
            ha_token=(env.get("HA_TOKEN") or env.get("SUPERVISOR_TOKEN") or "").strip() or None,
            admin_nur_ingress=_parse_schalter(env, "ADMIN_NUR_INGRESS", False),
            ist_addon=bool((env.get("SUPERVISOR_TOKEN") or "").strip()),
            intervall_minuten=_parse_zahl(env, "INTERVALL_MINUTEN", 5, int),
            sensor=_entitaet(env, "SENSOR", "sensor.wasseruhr_cv_zaehlerstand"),
            input_number=_entitaet(env, "INPUT_NUMBER", None),
            max_m3_pro_stunde=_parse_zahl(env, "MAX_M3_PRO_STUNDE", 3.0, float),
            toleranz_m3=_parse_zahl(env, "TOLERANZ_M3", 0.002, float),
            alle_ziffern_gelernt=_parse_schalter(env, "ALLE_ZIFFERN_GELERNT", True),
            port=_parse_zahl(env, "PORT", 8099, int),
            http=_parse_schalter(env, "HTTP", False),
            http_port=_parse_zahl(env, "HTTP_PORT", 8080, int),
            https=_parse_schalter(env, "HTTPS", False),
            https_port=_parse_zahl(env, "HTTPS_PORT", 8443, int),
            zertifikat=(env.get("ZERTIFIKAT") or "").strip() or "fullchain.pem",
            schluessel=(env.get("SCHLUESSEL") or "").strip() or "privkey.pem",
            ssl_verzeichnis=Path((env.get("SSL_VERZEICHNIS") or "").strip() or "/ssl"),
        )
        if konfig.max_vorlagen_pro_ziffer < 1:
            raise KonfigFehler("MAX_VORLAGEN_PRO_ZIFFER muss >= 1 sein")
        if not 0 <= konfig.verschiebung <= 10:
            raise KonfigFehler("VERSCHIEBUNG muss zwischen 0 und 10 liegen")
        if konfig.kamera and not _KAMERA.fullmatch(konfig.kamera):
            raise KonfigFehler(f"KAMERA={konfig.kamera!r}: erwartet eine Entität wie camera.wasseruhr")
        if konfig.sensor and not konfig.sensor.startswith("sensor."):
            raise KonfigFehler(f"SENSOR={konfig.sensor!r}: erwartet eine Entität wie sensor.wasserzaehler")
        if konfig.input_number and not konfig.input_number.startswith("input_number."):
            raise KonfigFehler(f"INPUT_NUMBER={konfig.input_number!r}: erwartet eine Entität wie input_number.wasserzaehler")
        if not 0 <= konfig.intervall_minuten <= 1440:
            raise KonfigFehler("INTERVALL_MINUTEN muss zwischen 0 und 1440 liegen")
        if konfig.max_m3_pro_stunde <= 0 or konfig.toleranz_m3 < 0:
            raise KonfigFehler("MAX_M3_PRO_STUNDE muss > 0 und TOLERANZ_M3 >= 0 sein")
        ports = [konfig.port] + [p for p, an in ((konfig.http_port, konfig.http), (konfig.https_port, konfig.https)) if an]
        if any(not 1 <= p <= 65535 for p in ports) or len(set(ports)) != len(ports):
            raise KonfigFehler(f"Ports müssen zwischen 1 und 65535 liegen und verschieden sein: {ports}")
        return konfig

    @property
    def automatik_moeglich(self) -> bool:
        return self.intervall_minuten > 0 and bool(self.kamera) and bool(self.ha_token)

    def ssl_pfad(self, name: str) -> Path:
        pfad = Path(name)
        return pfad if pfad.is_absolute() else self.ssl_verzeichnis / pfad


def _parse_zahl(env: dict[str, str], name: str, standard, typ):
    roh = env.get(name)
    if roh is None or roh.strip() == "":
        return standard
    try:
        return typ(roh.strip().replace(",", ".") if typ is float else roh.strip())
    except ValueError:
        raise KonfigFehler(f"{name}={roh!r} ist keine gültige Zahl") from None


_KAMERA = re.compile(r"camera\.[a-z0-9_]+")
_ENTITAET = re.compile(r"[a-z_]+\.[a-z0-9_]+")


def _entitaet(env: dict[str, str], name: str, standard: str | None) -> str | None:
    """Leer = Standard; '-' oder 'aus' = bewusst keine Entität."""
    roh = env.get(name)
    if roh is None:
        return standard
    roh = roh.strip()
    if roh.lower() in ("", "-", "aus", "none"):
        return None if roh else standard
    if not _ENTITAET.fullmatch(roh):
        raise KonfigFehler(f"{name}={roh!r} ist keine gültige Entität")
    return roh

_AN = {"an", "ein", "ja", "1", "true", "on", "yes"}
_AUS = {"aus", "nein", "0", "false", "off", "no"}


def _parse_schalter(env: dict[str, str], name: str, standard: bool) -> bool:
    roh = (env.get(name) or "").strip().lower()
    if roh == "":
        return standard
    if roh in _AN:
        return True
    if roh in _AUS:
        return False
    raise KonfigFehler(f"{name}={env[name]!r}: erwartet 'an' oder 'aus'")


def _parse_rois(roh: str | None) -> tuple[tuple[int, int, int, int], ...]:
    if roh is None or roh.strip() == "":
        return tuple(STANDARD_ROIS)
    try:
        daten = json.loads(roh)
    except json.JSONDecodeError as e:
        raise KonfigFehler(f"ROIS ist kein gültiges JSON: {e}") from None
    if not isinstance(daten, list) or len(daten) <= NACHKOMMASTELLEN:
        raise KonfigFehler(
            f"ROIS muss eine JSON-Liste mit mindestens {NACHKOMMASTELLEN + 1} Einträgen sein"
        )
    rois = []
    for i, eintrag in enumerate(daten, start=1):
        if (
            not isinstance(eintrag, list)
            or len(eintrag) != 4
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in eintrag)
        ):
            raise KonfigFehler(f"ROIS[{i}] muss [x1, y1, x2, y2] mit ganzen Zahlen sein")
        x1, y1, x2, y2 = eintrag
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise KonfigFehler(f"ROIS[{i}]={eintrag}: erwartet 0 <= x1 < x2 und 0 <= y1 < y2")
        if x2 - x1 <= 6:
            raise KonfigFehler(f"ROIS[{i}]={eintrag}: zu schmal (links/rechts werden je 3 px abgeschnitten)")
        rois.append((x1, y1, x2, y2))
    return tuple(rois)
