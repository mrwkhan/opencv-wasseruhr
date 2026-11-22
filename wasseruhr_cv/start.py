"""Start von Wasseruhr-CV – als Home-Assistant-Add-on und mit Docker Compose.

Im Add-on übersetzt das Skript die Optionen aus /data/options.json in die
Umgebungsvariablen des Webdienstes. Ohne options.json (Docker Compose) gelten
die Umgebungsvariablen unverändert. Danach wird die Konfiguration geprüft und
uvicorn auf Port 8099 gestartet (Ingress + API)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

OPTIONEN = Path(os.environ.get("ADDON_OPTIONEN", "/data/options.json"))
PORT = "8099"

# Add-on-Option -> Umgebungsvariable des Dienstes (siehe app/konfig.py)
ZUORDNUNG = {
    "lerneffekt": "LERNEFFEKT",
    "min_score": "MIN_SCORE",
    "min_abstand": "MIN_ABSTAND",
    "max_vorlagen_pro_ziffer": "MAX_VORLAGEN_PRO_ZIFFER",
    "verschiebung": "VERSCHIEBUNG",
    "rois": "ROIS",
    "kamera": "KAMERA",
    "admin_nur_ueber_ingress": "ADMIN_NUR_INGRESS",
    "log_level": "LOG_LEVEL",
}


def umgebung_setzen(optionen: dict) -> None:
    """Gesetzte Optionen überschreiben die Umgebung, leere/fehlende lassen sie stehen."""
    for option, variable in ZUORDNUNG.items():
        wert = optionen.get(option)
        if wert is None or (isinstance(wert, str) and not wert.strip()):
            continue
        if isinstance(wert, bool):
            wert = "an" if wert else "aus"
        os.environ[variable] = str(wert).strip()


def main() -> None:
    try:
        optionen = json.loads(OPTIONEN.read_text())
    except FileNotFoundError:
        optionen = {}
    except ValueError as e:
        sys.exit(f"[wasseruhr] {OPTIONEN} ist kein gültiges JSON: {e}")
    umgebung_setzen(optionen)

    from app.konfig import Konfig, KonfigFehler

    try:
        Konfig.aus_umgebung()
    except KonfigFehler as e:
        sys.exit(f"[wasseruhr] Konfiguration ungültig: {e}. Bitte in der Add-on-Konfiguration korrigieren.")

    os.execvp(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(Path(__file__).resolve().parent),
         "--host", "0.0.0.0", "--port", PORT, "--no-access-log"],
    )


if __name__ == "__main__":
    main()
