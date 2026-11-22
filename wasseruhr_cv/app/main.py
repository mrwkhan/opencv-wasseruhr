"""FastAPI web service: reads the water meter and learns digit templates.

The API is English (/read, /learn, /read-camera). The German paths of version
1.x (/ablesen, /lernen, /kamera-ablesen) keep working with their old answers."""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from . import __version__, admin, camera, debug_image, ha, i18n, model, security, training_page
from .auto_reading import AutoReader
from .config import DECIMALS, Config
from .i18n import T, for_request, message
from .image_archive import ImageArchive
from .migration import migrate_data
from .recognition import (
    DigitResult,
    ImageError,
    combine,
    cut_digits,
    decode_image,
    is_certain,
    recognise_digit,
    split_value,
)
from .templates import TemplateStore

log = logging.getLogger("wasseruhr")

HISTORY_LENGTH = 20  # readings kept in memory for the debug image and the training page


@dataclass
class Reading:
    number: int
    time: datetime
    data: bytes  # original JPEG, so exactly this image can be learned
    image: np.ndarray
    digits: list[np.ndarray]
    results: list[DigitResult]
    certain_per_wheel: list[bool]
    value: float | None
    certain: bool


def _setup_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )


def create_app(config: Config | None = None) -> FastAPI:
    _setup_logging()
    config = config or Config.from_env()
    i18n.configure(config.language)
    migrate_data(config.data_dir)
    store = TemplateStore(config.templates_dir, config.max_templates_per_digit)
    archive = ImageArchive(config.images_dir)
    history: OrderedDict[int, Reading] = OrderedDict()
    history_lock = threading.Lock()
    counter = [0]
    learn_lock = threading.Lock()  # archive + templates in the same order

    def _training_from_archive():
        for e in archive.entries():
            try:
                digits = split_value(e.value, config.wheel_count, DECIMALS)
                images = cut_digits(decode_image(e.path.read_bytes()), config.rois)
            except (ValueError, OSError) as ex:  # ImageError is a ValueError
                log.warning(T("log.image_skipped", name=e.path.name, error=ex))
                continue
            yield e.timestamp, digits, images

    def _rebuild() -> int:
        """Rebuild all templates from the archive (caller holds learn_lock)."""
        count = store.rebuild(_training_from_archive())
        log.info(T("log.rebuilt", n=count, counts=store.count_per_digit()))
        return count

    def _prepare_templates() -> None:
        store.directory.mkdir(parents=True, exist_ok=True)
        if config.model_dir is not None:
            model.install_bundled(config.model_dir, config.data_dir, archive, store)
        if not config.learning:
            store.load()
            log.info(T("log.learning_off"))
            return
        if archive.count() == 0:
            store.load()
            return
        count = store.rebuild(_training_from_archive())
        log.info(T("log.learning_on", n=count, counts=store.count_per_digit()))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # LANGUAGE=auto: log and sensor in the language of HA (start.py usually asked already)
        if config.ha_token and not i18n.asked():
            ha.adopt_language(config.ha_url, config.ha_token)
        log.info(T(
            "log.start", version=__version__, wheels=config.wheel_count,
            min_score=f"{config.min_score:.2f}", min_margin=f"{config.min_margin:.2f}",
            max_templates=config.max_templates_per_digit, shift=config.shift,
            learning=T("ui.on" if config.learning else "ui.off"), data=config.data_dir,
        ))
        log.info(T("log.language", source=T(f"log.language.{i18n.source()}")))
        camera_text = config.camera or T("log.none")
        log.info(T(
            "log.camera",
            camera=camera_text if config.ha_token else T("log.without_ha", camera=camera_text),
            admin=T("log.admin_ingress" if config.admin_ingress_only else "log.admin_network"),
        ))
        _prepare_templates()
        auto_reader.start()
        yield
        auto_reader.stop()

    app = FastAPI(title="Wasseruhr-CV", version=__version__, lifespan=lifespan)
    security.setup(app)
    i18n.setup(app)
    app.state.config = config
    app.state.store = store
    app.state.archive = archive

    def _digits_from_body(data: bytes) -> tuple[np.ndarray, list[np.ndarray]]:
        try:
            image = decode_image(data)
            return image, cut_digits(image, config.rois)
        except ImageError as e:
            raise HTTPException(status_code=400, detail=message(e)) from None

    # ---- POST /read ----------------------------------------------------------------

    def _read(data: bytes) -> tuple[int, dict]:
        image, digits = _digits_from_body(data)
        templates = store.snapshot()
        results = [recognise_digit(wheel, d, templates, config.shift) for wheel, d in enumerate(digits, start=1)]
        certain_per_wheel = [is_certain(r, config.min_score, config.min_margin) for r in results]
        certain = all(certain_per_wheel)
        value = combine(results, DECIMALS)
        missing = [d for d, t in templates.items() if not t]

        with history_lock:
            counter[0] += 1
            number = counter[0]
            history[number] = Reading(
                number, datetime.now(timezone.utc), data, image, digits, results, certain_per_wheel, value, certain
            )
            while len(history) > HISTORY_LENGTH:
                history.popitem(last=False)

        log.info(T(
            "log.read", n=number, value="null" if value is None else f"{value:.3f}",
            certain=T("ui.yes" if certain else "ui.no"),
            wheels=" ".join(_short(r, ok) for r, ok in zip(results, certain_per_wheel)),
            missing=T("log.missing_templates", digits=str(missing)) if missing else "",
        ))
        return number, {
            "value": value,
            "certain": certain,
            "digits": [r.as_dict() for r in results],
            "missing_templates": missing,
        }

    # Reads by itself at fixed intervals and writes to Home Assistant (see auto_reading.py)
    auto_reader = AutoReader(config, _read)
    app.state.auto_reader = auto_reader

    @app.post("/read")
    async def read(request: Request) -> dict:
        data = await security.read_body(request, security.MAX_IMAGE_BYTES)
        return (await run_in_threadpool(_read, data))[1]

    # ---- POST /read-camera -------------------------------------------------------

    def _read_camera() -> dict:
        if not config.camera:
            raise HTTPException(status_code=400, detail=T("api.no_camera"))
        if not config.ha_token:
            raise HTTPException(status_code=400, detail=T("api.no_ha"))
        try:
            data = camera.snapshot(config.ha_url, config.ha_token, config.camera)
        except camera.CameraError as e:
            raise HTTPException(status_code=502, detail=T("api.camera_failed", error=e)) from None
        number, result = _read(data)
        return {"reading": number, **result}

    @app.post("/read-camera")
    async def read_camera() -> dict:
        """Fetches the current image of the configured camera from Home Assistant and reads it."""
        return await run_in_threadpool(_read_camera)

    # ---- POST /learn ---------------------------------------------------------------

    def _reading(number: int | None) -> Reading | None:
        with history_lock:
            if number is None:
                return next(reversed(history.values()), None)
            return history.get(number)

    def _learn(data: bytes, value_text: str, reading: int | None) -> dict:
        try:
            value = float(value_text.strip().replace(",", "."))
            digits = split_value(value, config.wheel_count, DECIMALS)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=T("api.invalid_value", value=repr(value_text), error=e)) from None
        from_history = not data and reading is not None
        if from_history:
            r = _reading(reading)
            if r is None:
                raise HTTPException(status_code=404, detail=T("api.reading_reload", n=reading))
            data = r.data
        _image, images = _digits_from_body(data)  # check first, then archive
        with learn_lock:
            timestamp = archive.save(data, value)
            saved = store.learn(timestamp, digits, images) if config.learning else 0
        counts = store.count_per_digit()
        log.info(T(
            "log.learn", value=f"{value:.3f}", digits="".join(map(str, digits)), saved=saved,
            extra="" if config.learning else T("log.archived_only"), counts=counts,
        ))
        if from_history:
            _read(data)  # read the same image again right away -> the training page shows the effect
        return {"saved": saved, "templates_per_digit": counts}

    @app.post("/learn")
    async def learn(
        request: Request,
        value: str = Query(..., description="Meter reading shown on the image, e.g. 506.388"),
        reading: int | None = Query(
            None, description="Without body: learn the image of this reading (number from the training page)"
        ),
    ) -> dict:
        data = await security.read_body(request, security.MAX_IMAGE_BYTES)
        return await run_in_threadpool(_learn, data, value, reading)

    # ---- Version 1.x paths: German parameters and answers ----------------------------

    @app.post("/ablesen", include_in_schema=False)
    async def legacy_read(request: Request) -> dict:
        data = await security.read_body(request, security.MAX_IMAGE_BYTES)
        return _legacy_reading((await run_in_threadpool(_read, data))[1])

    @app.post("/kamera-ablesen", include_in_schema=False)
    async def legacy_read_camera() -> dict:
        result = await run_in_threadpool(_read_camera)
        return {"nr": result["reading"], **_legacy_reading(result)}

    @app.post("/lernen", include_in_schema=False)
    async def legacy_learn(request: Request, wert: str = Query(...), ablesung: int | None = Query(None)) -> dict:
        data = await security.read_body(request, security.MAX_IMAGE_BYTES)
        result = await run_in_threadpool(_learn, data, wert, ablesung)
        return {"gespeichert": result["saved"], "vorlagen_pro_ziffer": result["templates_per_digit"]}

    # ---- GET /status, /debug.png, /health ----------------------------------------

    @app.get("/status")
    def status() -> dict:
        return {
            "templates_per_digit": store.count_per_digit(),
            "missing_templates": store.missing_digits(),
            "learning": config.learning,
            "training_images": archive.count(),
            "meter_reading": auto_reader.state()["meter_reading"],
        }

    @app.get("/debug.png")
    def debug_png(
        request: Request,
        reading: int | None = Query(None, description="a specific reading instead of the latest"),
        nr: int | None = Query(None, include_in_schema=False),  # version 1.x
    ) -> Response:
        number = reading if reading is not None else nr
        r = _reading(number)
        if r is None:
            raise HTTPException(
                status_code=404,
                detail=T("api.no_reading_yet") if number is None else T("api.reading_gone", n=number),
            )
        png = debug_image.draw(
            r.image, config.rois, r.digits, r.results, r.certain_per_wheel, r.value, r.certain,
            language=for_request(request),
        )
        return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, reading: int | None = None, nr: int | None = None) -> HTMLResponse:
        r = _reading(reading if reading is not None else nr) or _reading(None)
        latest = _reading(None)
        return HTMLResponse(
            training_page.render(
                learning=config.learning,
                training_images=archive.count(),
                missing=store.missing_digits(),
                reading=r.number if r else None,
                time=r.time if r else None,
                value=r.value if r else None,
                certain=r.certain if r else False,
                is_latest=r is latest,
                camera=bool(config.camera and config.ha_token),
                interval=config.interval_minutes if auto_reader.active else None,
                meter_reading=auto_reader.state()["meter_reading"],
                admin=admin.admin_allowed(config, request),
                language=for_request(request),
            ),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    # ---- /admin ----------------------------------------------------------------------

    def _readings() -> list[Reading]:
        with history_lock:
            return list(reversed(history.values()))

    app.include_router(
        admin.router(
            admin.Context(
                config=config,
                store=store,
                archive=archive,
                learn_lock=learn_lock,
                rebuild=_rebuild,
                readings=_readings,
                version=__version__,
                auto_reader=auto_reader,
            )
        )
    )

    return app


def _legacy_reading(result: dict) -> dict:
    """Answer of /read in the format of version 1.x."""
    return {
        "wert": result["value"],
        "sicher": result["certain"],
        "ziffern": [
            {"rolle": d["wheel"], "ziffer": d["digit"], "score": d["score"],
             "zweitbeste": d["second"], "score2": d["second_score"]}
            for d in result["digits"]
        ],
        "fehlende_vorlagen": result["missing_templates"],
    }


def _short(r: DigitResult, ok: bool) -> str:
    if r.digit is None:
        return f"r{r.wheel}=?"
    second = "" if r.second is None else f"/{r.second}:{r.second_score:.2f}"
    return f"r{r.wheel}={r.digit}({r.score:.2f}{second}){'' if ok else '!'}"


app = create_app()
