"""Configuration from environment variables.

The names are English. The German names of version 1.x (KAMERA, LERNEFFEKT …)
are still accepted, so existing Docker setups keep working."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .i18n import AUTO, T, from_code

# Counter in a 640x480 image (OV3660 snapshot): 8 wheels, each [x1, y1, x2, y2] in pixels.
DEFAULT_ROIS: list[tuple[int, int, int, int]] = [
    (130, 144, 162, 196),
    (173, 144, 205, 196),
    (216, 144, 248, 196),
    (260, 144, 292, 196),
    (304, 144, 336, 196),
    (347, 144, 379, 196),
    (391, 144, 423, 196),
    (435, 144, 467, 196),
]

DECIMALS = 3
DEFAULT_SENSOR = "sensor.wasseruhr_cv_meter_reading"
LEGACY_DEFAULT_SENSOR = "sensor.wasseruhr_cv_zaehlerstand"  # default up to version 1.5

# English variable -> German name of version 1.x (still accepted)
LEGACY_ENV = {
    "CAMERA": "KAMERA",
    "INTERVAL_MINUTES": "INTERVALL_MINUTEN",
    "MAX_M3_PER_HOUR": "MAX_M3_PRO_STUNDE",
    "TOLERANCE_M3": "TOLERANZ_M3",
    "REQUIRE_ALL_DIGITS": "ALLE_ZIFFERN_GELERNT",
    "CERTIFICATE": "ZERTIFIKAT",
    "CERTIFICATE_KEY": "SCHLUESSEL",
    "SSL_DIR": "SSL_VERZEICHNIS",
    "LEARNING": "LERNEFFEKT",
    "MIN_MARGIN": "MIN_ABSTAND",
    "MAX_TEMPLATES_PER_DIGIT": "MAX_VORLAGEN_PRO_ZIFFER",
    "SHIFT": "VERSCHIEBUNG",
    "ADMIN_INGRESS_ONLY": "ADMIN_NUR_INGRESS",
    "LANGUAGE": "SPRACHE",
    "MODEL_DIR": "MODELL_DIR",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    rois: tuple[tuple[int, int, int, int], ...] = tuple(DEFAULT_ROIS)
    min_score: float = 0.70
    min_margin: float = 0.08
    max_templates_per_digit: int = 30
    shift: int = 3
    data_dir: Path = Path("/data")
    learning: bool = True
    # Bundled model (Home Assistant add-on): copied into an empty data directory
    # on the very first start.
    model_dir: Path | None = None
    # Camera entity read via the Home Assistant API
    camera: str | None = None
    ha_url: str = "http://supervisor/core/api"
    supervisor_url: str = "http://supervisor"  # add-on only: own options, restart
    ha_token: str | None = field(default=None, repr=False)
    # Admin page (/admin) only via the HA ingress, i.e. only for logged-in HA users
    admin_ingress_only: bool = False
    is_addon: bool = False

    # Automatic reading: read the camera every N minutes and write to Home Assistant
    interval_minutes: int = 5  # 0 = no automatic reading
    sensor: str | None = DEFAULT_SENSOR
    input_number: str | None = None
    max_m3_per_hour: float = 3.0  # faster increase = reading error
    tolerance_m3: float = 0.002  # silently ignore small backward deviations
    require_all_digits: bool = True  # only write once 0–9 are all learned

    # Access: port 8099 always serves the ingress and the internal network (not
    # published in the add-on). Optionally HTTP and HTTPS for the local network.
    port: int = 8099
    http: bool = False
    http_port: int = 8080
    https: bool = False
    https_port: int = 8443
    certificate: str = "fullchain.pem"  # relative to ssl_dir or absolute
    certificate_key: str = "privkey.pem"
    ssl_dir: Path = Path("/ssl")

    # "en"/"de" fixed, "auto" = pages follow the browser, log and sensor follow
    # Home Assistant (see i18n.py)
    language: str = AUTO

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def wheel_count(self) -> int:
        return len(self.rois)

    @property
    def auto_reading_possible(self) -> bool:
        return self.interval_minutes > 0 and bool(self.camera) and bool(self.ha_token)

    def ssl_path(self, name: str) -> Path:
        path = Path(name)
        return path if path.is_absolute() else self.ssl_dir / path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = with_legacy_names(os.environ if env is None else env)
        config = cls(
            rois=_parse_rois(env.get("ROIS")),
            min_score=_number(env, "MIN_SCORE", 0.70, float),
            min_margin=_number(env, "MIN_MARGIN", 0.08, float),
            max_templates_per_digit=_number(env, "MAX_TEMPLATES_PER_DIGIT", 30, int),
            shift=_number(env, "SHIFT", 3, int),
            data_dir=Path(env.get("DATA_DIR") or "/data"),
            learning=_switch(env, "LEARNING", True),
            model_dir=Path(env["MODEL_DIR"]) if (env.get("MODEL_DIR") or "").strip() else None,
            camera=(env.get("CAMERA") or "").strip() or None,
            ha_url=(env.get("HA_URL") or "").strip() or "http://supervisor/core/api",
            supervisor_url=(env.get("SUPERVISOR_URL") or "").strip() or "http://supervisor",
            ha_token=(env.get("HA_TOKEN") or env.get("SUPERVISOR_TOKEN") or "").strip() or None,
            admin_ingress_only=_switch(env, "ADMIN_INGRESS_ONLY", False),
            is_addon=bool((env.get("SUPERVISOR_TOKEN") or "").strip()),
            interval_minutes=_number(env, "INTERVAL_MINUTES", 5, int),
            sensor=_entity(env, "SENSOR", DEFAULT_SENSOR),
            input_number=_entity(env, "INPUT_NUMBER", None),
            max_m3_per_hour=_number(env, "MAX_M3_PER_HOUR", 3.0, float),
            tolerance_m3=_number(env, "TOLERANCE_M3", 0.002, float),
            require_all_digits=_switch(env, "REQUIRE_ALL_DIGITS", True),
            port=_number(env, "PORT", 8099, int),
            http=_switch(env, "HTTP", False),
            http_port=_number(env, "HTTP_PORT", 8080, int),
            https=_switch(env, "HTTPS", False),
            https_port=_number(env, "HTTPS_PORT", 8443, int),
            certificate=(env.get("CERTIFICATE") or "").strip() or "fullchain.pem",
            certificate_key=(env.get("CERTIFICATE_KEY") or "").strip() or "privkey.pem",
            ssl_dir=Path((env.get("SSL_DIR") or "").strip() or "/ssl"),
            language=_parse_language(env),
        )
        if config.max_templates_per_digit < 1:
            raise ConfigError(T("config.max_templates"))
        if not 0 <= config.shift <= 10:
            raise ConfigError(T("config.shift"))
        if config.camera and not _CAMERA.fullmatch(config.camera):
            raise ConfigError(T("config.camera", value=repr(config.camera)))
        if config.sensor and not config.sensor.startswith("sensor."):
            raise ConfigError(T("config.sensor", value=repr(config.sensor)))
        if config.input_number and not config.input_number.startswith("input_number."):
            raise ConfigError(T("config.input_number", value=repr(config.input_number)))
        if not 0 <= config.interval_minutes <= 1440:
            raise ConfigError(T("config.interval"))
        if config.max_m3_per_hour <= 0 or config.tolerance_m3 < 0:
            raise ConfigError(T("config.m3"))
        ports = [config.port] + [p for p, on in ((config.http_port, config.http), (config.https_port, config.https)) if on]
        if any(not 1 <= p <= 65535 for p in ports) or len(set(ports)) != len(ports):
            raise ConfigError(T("config.ports", ports=str(ports)))
        return config


def with_legacy_names(env: Mapping[str, str]) -> dict[str, str]:
    """Copy of the environment in which the German names of version 1.x fill in
    the English ones that are not set."""
    result = dict(env)
    for name, legacy in LEGACY_ENV.items():
        if name not in result and legacy in result:
            result[name] = result[legacy]
    return result


def _number(env: Mapping[str, str], name: str, default, kind):
    raw = env.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return kind(raw.strip().replace(",", ".") if kind is float else raw.strip())
    except ValueError:
        raise ConfigError(T("config.number", name=name, value=repr(raw))) from None


_CAMERA = re.compile(r"camera\.[a-z0-9_]+")
_ENTITY = re.compile(r"[a-z_]+\.[a-z0-9_]+")
_NONE = ("-", "none", "off", "aus")  # aus: version 1.x


def _entity(env: Mapping[str, str], name: str, default: str | None) -> str | None:
    """Empty = default; 'none', 'off' or '-' = deliberately no entity."""
    raw = env.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return default
    if raw.lower() in _NONE:
        return None
    if not _ENTITY.fullmatch(raw):
        raise ConfigError(T("config.entity", name=name, value=repr(raw)))
    return raw


_ON = {"true", "on", "yes", "1", "an", "ein", "ja"}  # an/ein/ja: version 1.x
_OFF = {"false", "off", "no", "0", "aus", "nein"}


def _switch(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in _ON:
        return True
    if raw in _OFF:
        return False
    raise ConfigError(T("config.switch", name=name, value=repr(env[name])))


def _parse_language(env: Mapping[str, str]) -> str:
    """auto, en or de. Locale notations such as de_DE.UTF-8 or en_US:en are understood."""
    raw = (env.get("LANGUAGE") or "").strip()
    first = raw.split(":")[0].strip()
    if first.lower() in ("", AUTO, "c", "posix") or first.lower().startswith("c."):
        return AUTO
    if language := from_code(first):
        return language
    raise ConfigError(T("config.language", value=repr(raw)))


def _parse_rois(raw: str | None) -> tuple[tuple[int, int, int, int], ...]:
    if raw is None or raw.strip() == "":
        return tuple(DEFAULT_ROIS)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConfigError(T("config.rois_json", error=e)) from None
    if not isinstance(data, list) or len(data) <= DECIMALS:
        raise ConfigError(T("config.rois_list", n=DECIMALS + 1))
    rois = []
    for i, entry in enumerate(data, start=1):
        if (
            not isinstance(entry, list)
            or len(entry) != 4
            or not all(isinstance(v, int) and not isinstance(v, bool) for v in entry)
        ):
            raise ConfigError(T("config.roi_format", i=i))
        x1, y1, x2, y2 = entry
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ConfigError(T("config.roi_position", i=i, roi=str(entry)))
        if x2 - x1 <= 6:
            raise ConfigError(T("config.roi_narrow", i=i, roi=str(entry)))
        rois.append((x1, y1, x2, y2))
    return tuple(rois)
