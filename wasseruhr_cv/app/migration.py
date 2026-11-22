"""Takes over data and settings of version 1.x, which used German names.

- Data directory: lernbilder/ -> images/, vorlagen/ -> templates/,
  zaehlerstand.json -> meter_reading.json, .modell_erstausstattung.json ->
  .bundled_model.json, tls/selbstsigniert.* -> tls/self-signed.*
- Add-on options: German keys (kamera, lerneffekt …) -> English keys. After an
  update the Supervisor still returns the values stored under the old keys
  until the options are saved again.
- Sensor: an installation that wrote to the old default sensor keeps writing
  there, so the history in the Energy dashboard continues.

Everything here is idempotent: a second run finds nothing left to do."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import DEFAULT_SENSOR, LEGACY_DEFAULT_SENSOR
from .i18n import T

log = logging.getLogger(__name__)

STATE_FILE = "meter_reading.json"

# German add-on option of version 1.x -> English option
LEGACY_OPTIONS = {
    "kamera": "camera",
    "intervall_minuten": "interval_minutes",
    "max_m3_pro_stunde": "max_m3_per_hour",
    "toleranz_m3": "tolerance_m3",
    "alle_ziffern_gelernt": "require_all_digits",
    "zertifikat": "certificate",
    "schluessel": "certificate_key",
    "lerneffekt": "learning",
    "min_abstand": "min_margin",
    "max_vorlagen_pro_ziffer": "max_templates_per_digit",
    "verschiebung": "shift",
    "admin_nur_ueber_ingress": "admin_ingress_only",
    "sprache": "language",
}

_LEGACY_STATE = "zaehlerstand.json"
_LEGACY_MARKER = ".modell_erstausstattung.json"


def migrate_data(data_dir: Path) -> list[str]:
    """Renames the data of version 1.x. Returns what was migrated (for the log)."""
    done: list[str] = []
    for old, new in (("lernbilder", "images"), ("vorlagen", "templates")):
        if (data_dir / old).is_dir() and not (data_dir / new).exists():
            (data_dir / old).rename(data_dir / new)
            done.append(f"{old}/ -> {new}/")

    old_state = data_dir / _LEGACY_STATE
    if old_state.is_file():
        try:
            d = json.loads(old_state.read_text())
            state = {"value": float(d["wert"]), "time": d["zeit"], "legacy_sensor": LEGACY_DEFAULT_SENSOR}
        except (OSError, ValueError, KeyError, TypeError):
            state = None
        if state is not None and not (data_dir / STATE_FILE).exists():
            (data_dir / STATE_FILE).write_text(json.dumps(state))
            old_state.unlink()
            done.append(f"{_LEGACY_STATE} -> {STATE_FILE}")

    old_marker = data_dir / _LEGACY_MARKER
    if old_marker.is_file():
        try:
            d = json.loads(old_marker.read_text())
            marker = {"installed": bool(d.get("uebernommen")), "time": d.get("zeit")}
            if "lernbilder" in d:
                marker.update(images=d["lernbilder"], templates=d.get("vorlagen", 0))
            if not marker["installed"]:
                marker["reason"] = "data_present"
        except (OSError, ValueError, TypeError, AttributeError):
            marker = {"installed": False, "reason": "data_present"}
        new_marker = data_dir / ".bundled_model.json"
        if not new_marker.exists():
            new_marker.write_text(json.dumps(marker))
        old_marker.unlink()
        done.append(f"{_LEGACY_MARKER} -> .bundled_model.json")

    tls = data_dir / "tls"
    for ending in ("crt", "key"):
        old, new = tls / f"selbstsigniert.{ending}", tls / f"self-signed.{ending}"
        if old.is_file() and not new.exists():
            old.rename(new)
            done.append(f"tls/{old.name} -> tls/{new.name}")

    if done:
        log.info(T("log.data_migrated", items=", ".join(done)))
    return done


def is_legacy_installation(data_dir: Path) -> bool:
    """Is this the first start after an update from version 1.x (data not migrated yet)?"""
    return (data_dir / _LEGACY_STATE).exists() or (data_dir / "lernbilder").exists()


def migrate_options(current: dict, stored: dict, legacy_installation: bool) -> dict | None:
    """New add-on options or None if nothing changes.

    current: options.json of this start (English keys, defaults for renamed ones)
    stored: options as the Supervisor returns them, possibly with German keys.
    Old keys only exist until the options are saved once, so their presence
    means the English keys still hold their defaults."""
    new = dict(current)
    changed = False
    for old, key in LEGACY_OPTIONS.items():
        if old in stored and key in new and new[key] != stored[old]:
            new[key] = stored[old]
            changed = True
    if legacy_installation and new.get("sensor") == DEFAULT_SENSOR:
        new["sensor"] = LEGACY_DEFAULT_SENSOR
        changed = True
    return new if changed else None
