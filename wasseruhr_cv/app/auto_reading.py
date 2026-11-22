"""Automatic reading: reads the camera image from Home Assistant at fixed
intervals, checks the value for plausibility and writes only certain, plausible
values to Home Assistant – as a sensor (Energy dashboard) and optionally into
an input_number helper.

Plausibility: a water meter only counts forward and only as fast as water can
flow. The comparison is with the last accepted meter reading. If an
input_number is configured and a different value was set there by hand, it
counts as a correction.

Status codes and attribute names of the sensor are language-neutral, so
automations work in every language. Reasons are texts that are translated for
each output (see i18n.py)."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from . import camera, ha, i18n
from .config import DEFAULT_SENSOR, Config
from .i18n import T, Text, message, render, translate
from .migration import STATE_FILE
from .recognition import ImageError

log = logging.getLogger(__name__)

# Status of a check – codes for the sensor attribute, the API and automations
ACCEPTED = "accepted"
UNCHANGED = "unchanged"
REJECTED = "rejected"
ERROR = "error"
SET = "set"
STATUSES = (ACCEPTED, UNCHANGED, REJECTED, ERROR, SET)

FIRST_READING_AFTER_S = 15


@dataclass(frozen=True)
class Rules:
    max_m3_per_hour: float
    tolerance_m3: float
    require_all_digits: bool
    min_score: float
    min_margin: float


def check(
    result: dict, previous: float | None, since: datetime | None, now: datetime, rules: Rules
) -> tuple[str, Text | str]:
    """Decides on a reading. Returns (status, reason)."""
    value = result.get("value")
    if value is None:
        return REJECTED, T("auto.no_templates")
    text = f"{value:.3f}"
    if not result.get("certain"):
        weak = [
            f"R{d['wheel']}={d['digit']} ({d['score']} vs {d['second']}: {d['second_score']})"
            for d in result.get("digits", [])
            if d["digit"] is None or d["second_score"] is None
            or d["score"] < rules.min_score or d["score"] - d["second_score"] < rules.min_margin
        ]
        return REJECTED, T("auto.uncertain", value=text, wheels=", ".join(weak))
    if rules.require_all_digits and result.get("missing_templates"):
        digits = ", ".join(map(str, result["missing_templates"]))
        return REJECTED, T("auto.missing_templates", value=text, digits=digits)
    if previous is None or previous <= 0:
        return ACCEPTED, T("auto.first")
    diff = round(value - previous, 3)
    if diff == 0:
        return UNCHANGED, ""
    if diff < 0:
        if -diff <= rules.tolerance_m3:
            return UNCHANGED, T("auto.backward", diff=f"{diff:.3f}")
        return REJECTED, T("auto.lower", value=text, previous=f"{previous:.3f}")
    minutes = max(0.0, (now - since).total_seconds() / 60) if since else 0.0
    if diff > rules.max_m3_per_hour * minutes / 60 + rules.tolerance_m3:
        return REJECTED, T("auto.implausible", value=text, diff=f"{diff:.3f}", minutes=round(minutes))
    return ACCEPTED, f"+{diff:.3f} m³"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AutoReader:
    def __init__(self, config: Config, read: Callable[[bytes], tuple[int, dict]]):
        self.config = config
        self._read = read
        self._file = config.data_dir / STATE_FILE
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._value, self._time, self._legacy_sensor = self._load()
        # Installations from version 1.x keep writing to their old default sensor
        # (history in the Energy dashboard), unless another sensor is configured.
        self.sensor = self._legacy_sensor if config.sensor == DEFAULT_SENSOR and self._legacy_sensor else config.sensor
        self._last: dict | None = None
        self._helper_missing: bool | None = None  # None = not checked yet / HA not reachable
        self._helper_value: float | None = None  # last value read from the helper
        self.rules = Rules(
            config.max_m3_per_hour, config.tolerance_m3, config.require_all_digits,
            config.min_score, config.min_margin,
        )

    # ---- Scheduling ------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.config.auto_reading_possible

    def start(self) -> None:
        if not self.active:
            reason = (
                T("auto.off.interval") if self.config.interval_minutes == 0
                else T("auto.off.camera") if not self.config.camera
                else T("auto.off.ha")
            )
            log.info(T("log.auto.off", reason=reason))
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="auto-reading", daemon=True)
        self._thread.start()
        targets = ", ".join(filter(None, [self.sensor, self.config.input_number]))
        log.info(T("log.auto.on", camera=self.config.camera, n=self.config.interval_minutes,
                   targets=targets or T("log.auto.no_entity")))

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=30)
            self._thread = None

    def _loop(self) -> None:
        if self._stop.wait(FIRST_READING_AFTER_S):
            return
        while True:
            try:
                self.run_once()
            except Exception:  # the loop must never die
                log.exception(T("log.auto.unexpected"))
            if self._stop.wait(self.config.interval_minutes * 60):
                return

    # ---- One run ---------------------------------------------------------------

    def run_once(self) -> dict:
        with self._lock:
            now = _now()
            c = self.config
            if not (c.camera and c.ha_token):
                return self._report(now, ERROR, T("auto.no_access"))
            if i18n.pending() and ha.adopt_language(c.ha_url, c.ha_token):
                log.info(T("log.language_from_ha"))  # Home Assistant was not reachable at start-up
            try:
                image = camera.snapshot(c.ha_url, c.ha_token, c.camera)
                number, result = self._read(image)
            except (camera.CameraError, ImageError) as e:
                return self._report(now, ERROR, message(e))
            except Exception as e:  # e.g. HTTPException from reading (ROI outside the image)
                return self._report(now, ERROR, getattr(e, "detail", None) or message(e))

            previous, since = self._baseline()
            status, reason = check(result, previous, since, now, self.rules)
            if status == ACCEPTED:
                self._remember(result["value"], now)
            elif status == UNCHANGED:
                self._remember(previous, now)  # confirmed: time base for the increase check
            return self._report(now, status, reason, reading=number, recognized=result.get("value"))

    def set_meter_reading(self, value: float) -> dict:
        """Correct by hand, e.g. after replacing the meter."""
        with self._lock:
            now = _now()
            self._remember(round(value, 3), now)
            return self._report(now, SET, T("auto.by_hand"))

    # ---- Meter reading & baseline --------------------------------------------------

    def _baseline(self) -> tuple[float | None, datetime | None]:
        """Value to compare with. A value changed by hand in the input_number counts as a correction."""
        c = self.config
        if c.input_number:
            state, value = None, None
            try:
                state = ha.state(c.ha_url, c.ha_token, c.input_number)
                self._helper_missing = state is None
                self._helper_value = None
                value = float(state["state"]) if state else None
                self._helper_value = value
            except (ha.HAError, ValueError, KeyError, TypeError) as e:
                log.warning(T("log.auto.helper_unreadable", entity=c.input_number, error=e))
            if value is not None and value > 0 and (self._value is None or round(value - self._value, 3) != 0):
                try:
                    changed = datetime.fromisoformat(state["last_changed"])
                except (KeyError, TypeError, ValueError):
                    changed = None
                # Only a change AFTER the last confirmed reading is a correction –
                # otherwise a permanently failing write would make the value jump back and forth.
                if self._value is None or (changed is not None and self._time is not None and changed > self._time):
                    log.info(T("log.auto.correction", entity=c.input_number, value=f"{value:.3f}"))
                    self._remember(value, changed or _now())
        return self._value, self._time

    def _remember(self, value: float | None, time: datetime) -> None:
        self._value, self._time = value, time
        state = {"value": value, "time": time.isoformat()}
        if self._legacy_sensor:
            state["legacy_sensor"] = self._legacy_sensor
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            tmp.replace(self._file)
        except OSError as e:
            log.warning(T("log.auto.not_saved", error=e))

    def _load(self) -> tuple[float | None, datetime | None, str | None]:
        try:
            d = json.loads(self._file.read_text())
        except (OSError, ValueError):
            return None, None, None
        legacy = d.get("legacy_sensor") if isinstance(d, dict) else None
        try:
            return float(d["value"]), datetime.fromisoformat(d["time"]), legacy
        except (KeyError, TypeError, ValueError):
            return None, None, legacy

    # ---- Report & write to Home Assistant -------------------------------------------

    def _report(self, now: datetime, status: str, reason: Text | str, reading: int | None = None,
                recognized: float | None = None) -> dict:
        """Remember and send the result. reason/sent stay translatable (see state)."""
        sent = self._publish(now, status, reason, recognized)
        self._last = {
            "time": now.isoformat(), "status": status, "reason": reason, "reading": reading,
            "recognized": recognized, "meter_reading": self._value, "sent": sent,
        }
        level = logging.WARNING if status == ERROR else logging.INFO
        log.log(level, T(
            "log.auto.result", status=T(f"ui.status.{status}"),
            reason=T("log.auto.reason", reason=reason) if reason else "",
            reading=T("log.auto.reading", n=reading) if reading else "",
            value="–" if self._value is None else f"{self._value:.3f}",
        ))
        return self._last

    def _publish(self, now: datetime, status: str, reason: Text | str, recognized: float | None) -> str | list:
        """"" = nothing to do, "ok" = everything arrived, otherwise the errors (translatable)."""
        c = self.config
        if not c.ha_token or self._value is None:
            return ""
        errors: list = []
        if self.sensor:
            attributes = {  # names and status language-neutral, texts in the service language
                "unit_of_measurement": "m³",
                "device_class": "water",
                "state_class": "total_increasing",
                "icon": "mdi:water",
                "friendly_name": translate("sensor.name"),
                "last_check": now.isoformat(),
                "status": status,
                "reason": render(reason),
                "recognized": recognized,
                "source": "Wasseruhr-CV",
            }
            try:
                ha.set_state(c.ha_url, c.ha_token, self.sensor, f"{self._value:.3f}", attributes)
            except ha.HAError as e:
                errors.append(T("auto.target_error", entity=self.sensor, error=e))
        if c.input_number:
            # Home Assistant does not report a service call for a missing entity as an
            # error – so check ourselves instead of reporting "ok" although nothing arrived.
            before = self._helper_missing
            if status == SET or self._helper_missing is None:
                self._helper_missing = self._check_helper_missing()
            if self._helper_missing:
                hint = T("auto.helper_missing", entity=c.input_number)
                if not before:  # only into the log when first noticed, not every 5 minutes
                    log.warning(T("log.auto.hint", text=hint))
                return [*errors, hint]
            # New reading – or the helper lags behind (e.g. still the value of an earlier
            # tool) and was not corrected by hand (_baseline would have taken that over).
            differs = self._helper_value is None or round(self._helper_value - self._value, 3) != 0
            if status in (ACCEPTED, SET) or differs:
                try:
                    ha.call_service(c.ha_url, c.ha_token, "input_number", "set_value",
                                    {"entity_id": c.input_number, "value": self._value})
                    self._helper_value = self._value
                except ha.HAError as e:
                    errors.append(T("auto.target_error", entity=c.input_number, error=e))
        for error in errors:
            log.warning(T("log.auto.send_failed", error=error))
        return errors or "ok"

    def _check_helper_missing(self) -> bool | None:
        try:
            return ha.state(self.config.ha_url, self.config.ha_token, self.config.input_number) is None
        except ha.HAError:
            return None  # unclear – then write anyway and let an error be reported

    # ---- Display -------------------------------------------------------------------

    def state(self, language: str | None = None) -> dict:
        """For the admin page and the API; reasons in the requested language."""
        c = self.config
        last = self._last
        if last is not None:
            last = {**last, "reason": render(last["reason"], language), "sent": render(last["sent"], language)}
        return {
            "active": self.active,
            "interval_minutes": c.interval_minutes,
            "camera": c.camera,
            "sensor": self.sensor,
            "input_number": c.input_number,
            "input_number_missing": bool(c.input_number) and self._helper_missing is True,
            "meter_reading": self._value,
            "meter_reading_time": self._time.isoformat() if self._time else None,
            "last": last,
            "rules": {
                "max_m3_per_hour": c.max_m3_per_hour,
                "tolerance_m3": c.tolerance_m3,
                "require_all_digits": c.require_all_digits,
            },
        }
