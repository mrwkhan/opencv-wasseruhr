"""Start of Wasseruhr-CV – as a Home Assistant add-on and with Docker Compose.

In the add-on the script turns the options from /data/options.json into the
environment variables of the web service. Without options.json (Docker
Compose) the environment variables apply unchanged. Options of version 1.x
(German names) are taken over once via the Supervisor. Then the configuration
is checked and the service started: port 8099 for ingress/internal, optionally
HTTP and HTTPS for the local network (see app/server.py)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import NoReturn

from app.i18n import LANGUAGES, T, render

OPTIONS = Path(os.environ.get("ADDON_OPTIONS", "/data/options.json"))
PORT = "8099"  # ingress port of the add-on (config.yaml: default ingress_port)

# Add-on option -> environment variable of the service (see app/config.py)
MAPPING = {
    "camera": "CAMERA",
    "interval_minutes": "INTERVAL_MINUTES",
    "sensor": "SENSOR",
    "input_number": "INPUT_NUMBER",
    "max_m3_per_hour": "MAX_M3_PER_HOUR",
    "tolerance_m3": "TOLERANCE_M3",
    "require_all_digits": "REQUIRE_ALL_DIGITS",
    "http": "HTTP",
    "https": "HTTPS",
    "certificate": "CERTIFICATE",
    "certificate_key": "CERTIFICATE_KEY",
    "learning": "LEARNING",
    "min_score": "MIN_SCORE",
    "min_margin": "MIN_MARGIN",
    "max_templates_per_digit": "MAX_TEMPLATES_PER_DIGIT",
    "shift": "SHIFT",
    "rois": "ROIS",
    "admin_ingress_only": "ADMIN_INGRESS_ONLY",
    "language": "LANGUAGE",
    "log_level": "LOG_LEVEL",
}
# In the add-on an emptied field here means "no entity" instead of "default"
ENTITY_OPTIONS = ("sensor", "input_number")


def set_environment(options: dict, addon: bool = False) -> None:
    """Options that are set override the environment, empty/missing ones leave it alone."""
    for option, variable in MAPPING.items():
        value = options.get(option)
        if value is None or (isinstance(value, str) and not value.strip()):
            if addon and option in ENTITY_OPTIONS:
                os.environ[variable] = "none"
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        os.environ[variable] = str(value).strip()


def _languages() -> list[str]:
    """Language for start-up messages; English and German as long as it is open."""
    choice = (os.environ.get("LANGUAGE") or os.environ.get("SPRACHE") or "").strip().lower()
    return [choice] if choice in LANGUAGES else ["en", "de"]


def say(text) -> None:
    for language in _languages():
        print(f"[wasseruhr] {render(text, language)}", flush=True)


def abort(text) -> NoReturn:
    """Start-up error into the log: in the configured language, otherwise English and
    German (the language of Home Assistant is not known at this point)."""
    sys.exit("\n".join(f"[wasseruhr] {render(text, language)}" for language in _languages()))


def migrate_addon_options(options: dict) -> dict:
    """Takes over the options of version 1.x (German names) once and stores them
    under the new names. Returns the options to use for this start."""
    token = (os.environ.get("SUPERVISOR_TOKEN") or "").strip()
    if not token:
        return options
    from app import ha
    from app.migration import is_legacy_installation, migrate_options

    url = (os.environ.get("SUPERVISOR_URL") or "").strip() or "http://supervisor"
    try:
        stored = ha.addon_options(url, token)
    except ha.HAError:
        stored = {}
    new = migrate_options(options, stored, is_legacy_installation(Path(os.environ.get("DATA_DIR") or "/data")))
    if new is None:
        return options
    try:
        ha.set_addon_options(url, token, new)
        say(T("start.options_migrated"))
    except ha.HAError as e:
        say(T("start.options_not_saved", error=e))
    return new


def main() -> None:
    addon = OPTIONS.is_file()
    try:
        options = json.loads(OPTIONS.read_text()) if addon else {}
    except ValueError as e:
        abort(T("start.json", file=OPTIONS, error=e))
    if addon:
        options = migrate_addon_options(options)
    set_environment(options, addon=addon)

    from app.config import Config, ConfigError

    try:
        config = Config.from_env()
    except ConfigError as e:
        abort(T("start.config", error=e))

    from app import ha
    from app.main import app
    from app.server import start

    if config.ha_token:  # LANGUAGE=auto: the very first messages already in the language of HA
        ha.adopt_language(config.ha_url, config.ha_token)
    start(app, config)


if __name__ == "__main__":
    main()
