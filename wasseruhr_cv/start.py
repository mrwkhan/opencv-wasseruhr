"""Start von Wasseruhr-CV – als Home-Assistant-Add-on und mit Docker Compose.

Im Add-on übersetzt das Skript die Optionen aus /data/options.json in die
Umgebungsvariablen des Webdienstes. Ohne options.json (Docker Compose) gelten
die Umgebungsvariablen unverändert. Danach wird die Konfiguration geprüft und
der Dienst gestartet: Port 8099 für Ingress/intern, optional HTTP und HTTPS
fürs Heimnetz (siehe app/server.py)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OPTIONEN = Path(os.environ.get("ADDON_OPTIONEN", "/data/options.json"))
PORT = "8099"  # Ingress-Port des Add-ons (config.yaml: Standard ingress_port)

# Add-on-Option -> Umgebungsvariable des Dienstes (siehe app/konfig.py)
ZUORDNUNG = {
    "kamera": "KAMERA",
    "intervall_minuten": "INTERVALL_MINUTEN",
    "sensor": "SENSOR",
    "input_number": "INPUT_NUMBER",
    "max_m3_pro_stunde": "MAX_M3_PRO_STUNDE",
    "toleranz_m3": "TOLERANZ_M3",
    "alle_ziffern_gelernt": "ALLE_ZIFFERN_GELERNT",
    "http": "HTTP",
    "https": "HTTPS",
    "zertifikat": "ZERTIFIKAT",
    "schluessel": "SCHLUESSEL",
    "lerneffekt": "LERNEFFEKT",
    "min_score": "MIN_SCORE",
    "min_abstand": "MIN_ABSTAND",
    "max_vorlagen_pro_ziffer": "MAX_VORLAGEN_PRO_ZIFFER",
    "verschiebung": "VERSCHIEBUNG",
    "rois": "ROIS",
    "admin_nur_ueber_ingress": "ADMIN_NUR_INGRESS",
    "log_level": "LOG_LEVEL",
}
# Im Add-on bedeutet ein geleertes Feld hier "keine Entität" statt "Standard"
ENTITAETEN = ("sensor", "input_number")


def umgebung_setzen(optionen: dict, addon: bool = False) -> None:
    """Gesetzte Optionen überschreiben die Umgebung, leere/fehlende lassen sie stehen."""
    for option, variable in ZUORDNUNG.items():
        wert = optionen.get(option)
        if wert is None or (isinstance(wert, str) and not wert.strip()):
            if addon and option in ENTITAETEN:
                os.environ[variable] = "-"
            continue
        if isinstance(wert, bool):
            wert = "an" if wert else "aus"
        os.environ[variable] = str(wert).strip()


def main() -> None:
    addon = OPTIONEN.is_file()
    try:
        optionen = json.loads(OPTIONEN.read_text()) if addon else {}
    except ValueError as e:
        sys.exit(f"[wasseruhr] {OPTIONEN} ist kein gültiges JSON: {e}")
    umgebung_setzen(optionen, addon=addon)

    from app.konfig import Konfig, KonfigFehler

    try:
        konfig = Konfig.aus_umgebung()
    except KonfigFehler as e:
        sys.exit(f"[wasseruhr] Konfiguration ungültig: {e}. Bitte in der Konfiguration korrigieren.")

    from app.main import app
    from app.server import starten

    starten(app, konfig)


if __name__ == "__main__":
    main()
