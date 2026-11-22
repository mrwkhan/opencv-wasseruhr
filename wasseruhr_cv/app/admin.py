"""Admin page (/admin): check, correct and delete training images, view and
rebuild templates, export and import the model as a ZIP, choose the camera.

In the Home Assistant add-on the admin page is only reachable via the ingress
by default, i.e. only for users logged in to Home Assistant. The training page
and the API (/read, /learn …) stay reachable in the local network."""

from __future__ import annotations

import base64
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from . import admin_page, camera, ha, model, security
from .auto_reading import AutoReader
from .config import DECIMALS, Config
from .i18n import T, for_request, message
from .image_archive import ImageArchive
from .migration import LEGACY_OPTIONS
from .recognition import split_value
from .templates import DIGITS, TemplateStore

COUNTER_MARGIN = 12  # px around the counter in the preview image
CAMERA_ENTITY = re.compile(r"camera\.[a-z0-9_]+")
# Import mode; the German names of version 1.x keep working
IMPORT_MODES = {"merge": "merge", "replace": "replace", "ergaenzen": "merge", "ersetzen": "replace"}
log = logging.getLogger(__name__)


@dataclass
class Context:
    config: Config
    store: TemplateStore
    archive: ImageArchive
    learn_lock: threading.Lock
    rebuild: Callable[[], int]  # only call while holding learn_lock
    readings: Callable[[], list]  # readings in memory, newest first
    version: str
    auto_reader: AutoReader


def admin_allowed(config: Config, request: Request) -> bool:
    if not config.admin_ingress_only:
        return True
    return security.is_ingress(request)


def parse_value(text: str, config: Config) -> float:
    try:
        value = float(text.strip().replace(",", "."))
        split_value(value, config.wheel_count, DECIMALS)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=T("api.invalid_value", value=repr(text), error=e)) from None
    return value


def router(ctx: Context) -> APIRouter:
    config, archive, store = ctx.config, ctx.archive, ctx.store

    def access(request: Request) -> None:
        if not admin_allowed(config, request):
            raise HTTPException(status_code=403, detail=T("api.ingress_only"))

    r = APIRouter(prefix="/admin", dependencies=[Depends(access)])

    def _status(**extra) -> dict:
        return {
            **extra,
            "training_images": archive.count(),
            "templates_per_digit": store.count_per_digit(),
            "missing_templates": store.missing_digits(),
        }

    def _after_change() -> dict:
        """With learning on, the templates follow the archive right away; without it they stay frozen."""
        if config.learning:
            ctx.rebuild()
        return _status(templates_rebuilt=config.learning)

    # ---- Page & overview -------------------------------------------------------

    @r.get("", response_class=HTMLResponse)
    def page(request: Request) -> HTMLResponse:
        return HTMLResponse(admin_page.page(for_request(request)), headers={"Cache-Control": "no-store"})

    @r.get("/info")
    def info(request: Request) -> dict:
        return _status(
            version=ctx.version,
            addon=config.is_addon,
            learning=config.learning,
            camera=config.camera,
            camera_ready=bool(config.camera and config.ha_token),
            ha_access=bool(config.ha_token),
            bundled_model=model.bundled_info(config.data_dir),
            settings={
                "MIN_SCORE": config.min_score,
                "MIN_MARGIN": config.min_margin,
                "MAX_TEMPLATES_PER_DIGIT": config.max_templates_per_digit,
                "SHIFT": config.shift,
                "ROIS": [list(roi) for roi in config.rois],
                "ADMIN_INGRESS_ONLY": config.admin_ingress_only,
                "HTTP": config.http,
                "HTTPS": config.https,
                "LANGUAGE": config.language,
            },
            auto_reading=ctx.auto_reader.state(for_request(request)),
        )

    # ---- Auto-reading --------------------------------------------------------------

    @r.get("/auto-reading")
    def auto_reading(request: Request) -> dict:
        return ctx.auto_reader.state(for_request(request))

    @r.post("/auto-reading/run")
    def run_now(request: Request) -> dict:
        """Read, check and write to Home Assistant right away."""
        if not (config.camera and config.ha_token):
            raise HTTPException(status_code=400, detail=T("api.no_auto_reading"))
        ctx.auto_reader.run_once()
        return ctx.auto_reader.state(for_request(request))

    @r.post("/auto-reading/meter-reading")
    def set_meter_reading(
        request: Request, value: str = Query(..., description="Correct meter reading in m³")
    ) -> dict:
        """Correct by hand, e.g. after replacing the meter."""
        ctx.auto_reader.set_meter_reading(parse_value(value, config))
        return ctx.auto_reader.state(for_request(request))

    # ---- Choose the camera -------------------------------------------------------

    def _ha_access() -> None:
        if not config.ha_token:
            raise HTTPException(status_code=400, detail=T("api.no_ha"))

    @r.get("/cameras")
    def cameras() -> dict:
        """All cameras from Home Assistant – for the choice on the admin page."""
        _ha_access()
        try:
            found = ha.cameras(config.ha_url, config.ha_token)
        except ha.HAError as e:
            raise HTTPException(status_code=502, detail=T("api.cameras_failed", error=e)) from None
        return {"cameras": found, "current": config.camera, "can_save": config.is_addon}

    @r.get("/cameras/{entity_id}/image")
    def camera_preview(entity_id: str) -> Response:
        _ha_access()
        if not CAMERA_ENTITY.fullmatch(entity_id):
            raise HTTPException(status_code=400, detail=T("api.not_a_camera"))
        try:
            image = camera.snapshot(config.ha_url, config.ha_token, entity_id)
        except camera.CameraError as e:
            raise HTTPException(status_code=502, detail=message(e)) from None
        kind = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"
        return Response(image, media_type=kind, headers={"Cache-Control": "no-store"})

    @r.post("/camera")
    def choose_camera(entity_id: str = Query(..., description="e.g. camera.water_meter")) -> dict:
        """Stores the camera in the add-on configuration and restarts the add-on."""
        _ha_access()
        if not config.is_addon:
            raise HTTPException(status_code=400, detail=T("api.addon_only", entity=entity_id))
        try:
            known = {c["entity_id"] for c in ha.cameras(config.ha_url, config.ha_token)}
            if entity_id not in known:
                raise HTTPException(status_code=400, detail=T("api.entity_missing", entity=entity_id))
            options = {k: v for k, v in ha.addon_options(config.supervisor_url, config.ha_token).items()
                       if k not in LEGACY_OPTIONS}
            options["camera"] = entity_id
            ha.set_addon_options(config.supervisor_url, config.ha_token, options)
        except ha.HAError as e:
            raise HTTPException(status_code=502, detail=T("api.options_failed", error=e, entity=entity_id)) from None
        threading.Thread(target=_restart, daemon=True).start()
        return {"camera": entity_id, "restart": True}

    def _restart() -> None:
        time.sleep(1.5)  # deliver the answer to the browser first
        try:
            ha.restart_addon(config.supervisor_url, config.ha_token)
        except ha.HAError as e:  # the connection drops during the restart – expected
            log.info(T("log.restart", error=e))

    @r.get("/readings")
    def readings() -> list[dict]:
        return [
            {"number": a.number, "time": a.time.isoformat(), "value": a.value, "certain": a.certain}
            for a in ctx.readings()
        ]

    # ---- Training images -----------------------------------------------------

    @r.get("/images")
    def images() -> list[dict]:
        return [
            {"name": e.name, "timestamp": e.timestamp, "time": e.time.isoformat(), "value": e.value}
            for e in reversed(archive.entries())
        ]

    @r.get("/images/{name}")
    def image(name: str, counter: bool = False) -> Response:
        entry = archive.find(name)
        if entry is None:
            raise HTTPException(status_code=404, detail=T("api.image_missing", name=name))
        data = entry.path.read_bytes()
        kind = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        if counter:
            crop = _counter_crop(data, config.rois)
            if crop is not None:
                data, kind = crop, "image/jpeg"
        return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=600"})

    @r.post("/images/{name}/delete")
    def delete_image(name: str) -> dict:
        with ctx.learn_lock:
            try:
                archive.delete(name)
            except KeyError:
                raise HTTPException(status_code=404, detail=T("api.image_missing", name=name)) from None
            return _after_change()

    @r.post("/images/{name}/value")
    def correct_image(name: str, value: str = Query(..., description="Correct meter reading")) -> dict:
        correct = parse_value(value, config)
        with ctx.learn_lock:
            try:
                new = archive.change_value(name, correct)
            except KeyError:
                raise HTTPException(status_code=404, detail=T("api.image_missing", name=name)) from None
            return _after_change() | {"name": new.name}

    # ---- Templates ---------------------------------------------------------------

    @r.get("/templates")
    def templates() -> dict:
        """All templates per digit as small PNGs (Base64) – one request instead of hundreds."""
        result: dict[str, list[dict]] = {}
        for digit, names in store.names().items():
            result[digit] = []
            for name in names:
                picture = store.image(int(digit), name)
                if picture is None:
                    continue
                png = cv2.imencode(".png", picture)[1].tobytes()
                result[digit].append({"name": name, "png": base64.b64encode(png).decode("ascii")})
        return result

    @r.post("/reset")
    def reset() -> dict:
        """Delete all training images and templates to teach from scratch."""
        with ctx.learn_lock:
            archive.replace({})
            store.replace({d: [] for d in DIGITS})
            return _status(templates_rebuilt=False)

    @r.post("/rebuild")
    def rebuild() -> dict:
        with ctx.learn_lock:
            ctx.rebuild()
            return _status(templates_rebuilt=True)

    # ---- Export & import -------------------------------------------------------

    @r.get("/export.zip")
    def export() -> Response:
        with ctx.learn_lock:
            data = model.export(
                archive, config.templates_dir, {"version": ctx.version, "rois": [list(roi) for roi in config.rois]}
            )
        filename = f"wasseruhr-cv-model-{datetime.now():%Y%m%d-%H%M}.zip"
        return Response(
            data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
        )

    def _import(data: bytes, mode: str) -> dict:
        try:
            content = model.read_zip(data)
        except model.ModelError as e:
            raise HTTPException(status_code=400, detail=message(e)) from None
        if not content.images:
            raise HTTPException(status_code=400, detail=T("api.zip_without_images"))
        with ctx.learn_lock:
            if mode == "replace":
                new = archive.replace(content.images)
                if content.template_count and not config.learning:
                    store.replace(content.stock())  # take frozen templates over 1:1
                    rebuilt = False
                else:
                    ctx.rebuild()
                    rebuilt = True
            else:
                new = archive.merge(content.images)
                rebuilt = config.learning and new > 0
                if rebuilt:
                    ctx.rebuild()
            return _status(mode=mode, new_images=new, skipped=len(content.skipped), templates_rebuilt=rebuilt)

    @r.post("/import")
    async def import_model(
        request: Request,
        mode: str = Query("merge", pattern="^(merge|replace|ergaenzen|ersetzen)$"),
    ) -> dict:
        data = await security.read_body(request, model.MAX_SIZE)
        return await run_in_threadpool(_import, data, IMPORT_MODES[mode])

    return r


def _counter_crop(data: bytes, rois) -> bytes | None:
    """Only the counter (all ROIs plus margin) – so the value is readable in the list."""
    try:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    except cv2.error:  # pixel limit exceeded
        return None
    if image is None:
        return None
    height, width = image.shape[:2]
    x1 = max(0, min(r[0] for r in rois) - COUNTER_MARGIN)
    y1 = max(0, min(r[1] for r in rois) - COUNTER_MARGIN)
    x2 = min(width, max(r[2] for r in rois) + COUNTER_MARGIN)
    y2 = min(height, max(r[3] for r in rois) + COUNTER_MARGIN)
    if x2 <= x1 or y2 <= y1:
        return None
    ok, jpg = cv2.imencode(".jpg", image[y1:y2, x1:x2], [cv2.IMWRITE_JPEG_QUALITY, 88])
    return jpg.tobytes() if ok else None
