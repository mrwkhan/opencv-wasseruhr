# Wasseruhr-CV

**English** · [Deutsch](README.de.md)

[![CI](https://github.com/mrwkhan/opencv-wasseruhr/actions/workflows/ci.yaml/badge.svg)](https://github.com/mrwkhan/opencv-wasseruhr/actions/workflows/ci.yaml)

Reads the roller counter of a water meter ("Wasseruhr" in German) with
**classic computer vision**: OpenCV template matching, no LLM, no cloud. The
service learns the digits from camera images with a known meter reading,
then recognises them on its own and writes the checked reading to Home
Assistant.

Runs as a **Home Assistant add-on** (e.g. on Home Assistant Green) or as a
standalone Docker service – no other tools needed.

- **Automatic reading:** fetches the camera image from Home Assistant every
  few minutes and writes only certain, plausible values (forward only, and no
  faster than water can flow) to a sensor for the Energy dashboard and
  optionally to an `input_number` helper
- **Bundled initial model** ([wasseruhr_cv/model](wasseruhr_cv/model)), ready
  to use on first start
- Training page and admin page in the Home Assistant sidebar: train more,
  correct or delete wrongly learned images, view templates, back up and
  transfer the model as a ZIP
- **English and German:** pages, messages, log and sensor. The pages follow
  the browser language and can be switched on the page (EN/DE), the log and
  the sensor follow the Home Assistant language. See [Language](#language).
- Optionally reachable in the local network via **HTTP and/or HTTPS**, ports
  freely selectable
- Simple HTTP API (`POST /read` with the JPEG) for your own integrations

## Installation in Home Assistant

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmrwkhan%2Fopencv-wasseruhr)

Or by hand:

1. Settings → Add-ons → **Add-on Store** → menu (⋮) → **Repositories**
2. Enter `https://github.com/mrwkhan/opencv-wasseruhr` → **Add**
3. Select **Wasseruhr-CV** → **Install**. The image is built on the device
   (Python + OpenCV), which takes a few minutes.
4. On the Info tab, turn on "Show in sidebar" and "Watchdog" → **Start**

Supported: `aarch64` (Home Assistant Green/Yellow, Raspberry Pi 4/5 with a
64-bit OS) and `amd64`. Setup, training and usage are described in the
[add-on documentation](wasseruhr_cv/DOCS.md), which also appears in the
add-on under "Documentation".

## Getting started

1. **Select the camera:** sidebar → Wasseruhr-CV → Admin → pick the camera
   from the list (with preview) → Apply.
2. **Check the ROIs:** training page → "Read camera now". The drawn
   rectangles must sit on the digit windows, otherwise
   [adjust the ROIs](#adjusting-the-rois).
3. **Model:** the initial model is installed on first start. For a different
   meter, use "Reset model" on the admin page and teach it on the training
   page: enter the correct meter reading → "Learn from this image", until
   every digit 0–9 has been learned once.
4. **Done:** from now on the reading is in `sensor.wasseruhr_cv_meter_reading`
   every 5 minutes. For the Energy dashboard: Settings → Dashboards → Energy
   → Water consumption → select this sensor.

Details on automatic reading, HTTP/HTTPS and all options are in the
[add-on documentation](wasseruhr_cv/DOCS.md).

## Updating from version 1.x

Version 2.0 uses English names for options, variables, API paths and data
folders. Everything is taken over automatically on the first start:

- **Add-on options** (`kamera` → `camera`, `lerneffekt` → `learning` …) are
  copied to the new names and saved.
- **Data** (`lernbilder/` → `images/`, `vorlagen/` → `templates/`, the
  confirmed meter reading, the self-signed certificate) is renamed in place.
- **Sensor:** an installation that wrote to the old default
  `sensor.wasseruhr_cv_zaehlerstand` keeps writing there, so the history in the
  Energy dashboard continues. New installations use
  `sensor.wasseruhr_cv_meter_reading`.
- **Docker:** the German variable names (`KAMERA`, `LERNEFFEKT` …) and values
  (`an`/`aus`) still work. Please switch to the English ones when convenient.
- **API:** the paths of version 1.x (`/ablesen`, `/lernen?wert=`,
  `/kamera-ablesen`) still answer in their old format, but are no longer
  documented.

## Standalone with Docker Compose

```bash
git clone https://github.com/mrwkhan/opencv-wasseruhr.git
cd opencv-wasseruhr
docker compose up -d --build
curl http://localhost:8099/health        # -> {"ok":true}
```

Training page: `http://<host>:8099/`, admin page: `http://<host>:8099/admin`.
For automatic reading set `CAMERA`, `HA_URL` and `HA_TOKEN` (see
[docker-compose.yml](docker-compose.yml)). All data lives in `./data` and
survives restarts and updates:

```
data/
  images/              every image sent to /learn, e.g. 20261109T172251000000Z_506.388.jpg
  templates/           digit templates created from them, <digit>/<timestamp>_r<wheel>.png
  meter_reading.json   last confirmed meter reading of the automatic reading
```

Settings via the environment variables in
[docker-compose.yml](docker-compose.yml), see [Configuration](#configuration).
Log with the result and scores of every call:

```bash
docker compose logs -f
# ... read #12: value=506.388 certain=yes | r1=0(1.00/3:0.51) r2=0(1.00/5:0.53) ...
```

Format per wheel: `r<wheel>=<digit>(<score>/<second best>:<score2>)`, a `!`
marks an uncertain wheel.

> **Security:** the service has no password. Only run the ports in your local
> network, never forward them in your router. Websites in the browser cannot
> teach it anything (origin check), images are limited to 10 MB and 25
> megapixels. In the add-on, HTTP and HTTPS in the local network are off by
> default.

> **Privacy:** running training images show your own water meter including
> its readings. `data/` and model exports (`*.zip`) are therefore excluded via
> `.gitignore`. The bundled model shows only the counter; a test makes sure it
> stays that way.

## Language

All pages, messages, the log and the sensor exist in **English and German**.

| What | Language |
|---|---|
| Training page, admin page, API error messages | switch on the page (EN/DE, remembered in a cookie) → option `language` → browser language → service language |
| Log, sensor name and `reason` attribute | option `language`; with `auto` the language of Home Assistant, without Home Assistant English |
| Add-on options in Home Assistant | Home Assistant user language (`translations/`) |

The option `language` (Docker: `LANGUAGE`) accepts `auto` (default), `en` or
`de`. All names are English in both languages – options, variables, API paths
and the attributes of the sensor: `status`, `reason`, `recognized`,
`last_check` and `source`, where `status` is one of `accepted`, `unchanged`,
`rejected`, `error`, `set`. Only texts are translated.

**Adding a language:** copy `wasseruhr_cv/app/texts/en.json` to
`<code>.json`, translate the values (keep the keys and `{placeholders}`), add
the code to `LANGUAGES` in `wasseruhr_cv/app/i18n.py` and to the `language`
option in `config.yaml`, and add `wasseruhr_cv/translations/<code>.yaml`. The
tests check that every catalogue has the same keys and placeholders.

## Training images & learning

**Every image sent to `/learn` is kept**, byte for byte, as
`images/<timestamp>_<value>.jpg`. The templates are only an intermediate
result and can be rebuilt from the training images at any time.

| `LEARNING` | On start | `POST /learn` |
|------------|----------|---------------|
| `true` (default) | templates are **completely rebuilt from all training images** (oldest first) | archive the image **and** learn it as a template right away |
| `false` | existing templates are loaded unchanged | **only** archive the image |

In the add-on this is the switch **Learning**. It lets you, for example:

- **freeze recognition**: switched off, training images keep being collected
  while recognition stays unchanged. Later switch it on to learn everything.
- **remove wrong data**: correct or delete the training image on the admin
  page, the templates are rebuilt immediately.
- **change ROIs**: set new ROIs and restart with learning on. The templates
  are regenerated from the original images, nothing has to be taught again.

Nearly identical digits (correlation > 0.97) are not stored twice. At most
`MAX_TEMPLATES_PER_DIGIT` templates are kept per digit; the training images
themselves are never deleted automatically. Digits without contrast (camera
dark or overexposed) never become templates.

Tips: learn images under **different lighting**. The last wheel turns all the
time. If it sits between two digits, enter the one that fills more of the
window.

## Adjusting the ROIs

Each wheel of the counter is described by a rectangle (ROI) `[x1, y1, x2, y2]`
in pixels of the camera image: top left `(x1, y1)`, bottom right `(x2, y2)`.
The list goes from left (highest digit) to right, the **last 3 wheels are the
decimals** (litres). Without a value, defaults for a 640×480 image with 8
wheels apply:

```json
[[130,144,162,196],[173,144,205,196],[216,144,248,196],[260,144,292,196],
 [304,144,336,196],[347,144,379,196],[391,144,423,196],[435,144,467,196]]
```

How to find the values for your camera:

1. Open a camera image in an image editor and read the pixel coordinates of
   each digit window. The rectangle may be slightly larger than the digit,
   3 px are cut off on the left and right anyway.
2. Enter them as single-line JSON: in the add-on in the option `rois`, in
   Docker in the variable `ROIS`.
3. Read an image and open the training page. The ROIs are drawn in, below
   them the processed digits as the matcher sees them. Every digit should be
   fully visible and centred.

## Configuration

In the add-on via the options (Configuration tab), in Docker via environment
variables. Switches are toggles in the add-on; in Docker they take `true` or
`false` (`on`/`off`, `yes`/`no` and `1`/`0` work too).

| Variable | Add-on option | Default | Meaning |
|---|---|---|---|
| `LEARNING` | `learning` | `true` | see [learning](#training-images--learning) |
| `ROIS` | `rois` | see above | JSON list `[[x1,y1,x2,y2], …]`, one per wheel, at least 4 |
| `MIN_SCORE` | `min_score` | `0.70` | minimum score of the best digit for "certain" |
| `MIN_MARGIN` | `min_margin` | `0.08` | minimum margin to the second-best digit |
| `MAX_TEMPLATES_PER_DIGIT` | `max_templates_per_digit` | `30` | older templates are dropped |
| `SHIFT` | `shift` | `3` | search range of the template matching in px (±) |
| `CAMERA` | `camera` | – | camera entity that is read |
| `INTERVAL_MINUTES` | `interval_minutes` | `5` | automatic reading, `0` = off (needs `CAMERA` and HA access) |
| `SENSOR` | `sensor` | `sensor.wasseruhr_cv_meter_reading` | target for the meter reading, created or overwritten; `none` (add-on: empty) = no sensor |
| `INPUT_NUMBER` | `input_number` | – | optionally also an existing number helper (reported if missing) |
| `MAX_M3_PER_HOUR` | `max_m3_per_hour` | `3` | faster increase = reading error |
| `TOLERANCE_M3` | `tolerance_m3` | `0.002` | ignore small backward deviations |
| `REQUIRE_ALL_DIGITS` | `require_all_digits` | `true` | only write once 0–9 are learned |
| `HTTP` / `HTTP_PORT` | `http` | `false` / `8080` | additional HTTP listener (add-on: port under Network, default 8099) |
| `HTTPS` / `HTTPS_PORT` | `https` | `false` / `8443` | additional HTTPS listener (add-on: port under Network, default 8100) |
| `CERTIFICATE` / `CERTIFICATE_KEY` | `certificate` / `certificate_key` | `fullchain.pem` / `privkey.pem` | relative to `SSL_DIR` (`/ssl`) or absolute; if missing, a self-signed one is created |
| `LANGUAGE` | `language` | `auto` | `auto`, `en` or `de`, see [Language](#language) |
| `ADMIN_INGRESS_ONLY` | `admin_ingress_only` | Docker `false`, add-on `true` | admin page only via the HA sidebar |
| `LOG_LEVEL` | `log_level` | `INFO` | `DEBUG` also shows skipped duplicates |
| `PORT` | – | `8099` | main port (add-on: ingress/internal, Docker: the published port) |
| `HA_URL` | – | `http://supervisor/core/api` | Home Assistant REST API, for Docker e.g. `http://homeassistant.local:8123/api` |
| `HA_TOKEN` | – | automatic in the add-on | long-lived access token (Docker: in `.env`, never in the repository) |
| `DATA_DIR` | – | `/data` | data directory with `images/` and `templates/` |
| `MODEL_DIR` | – | `/opt/wasseruhr/model` | initial model, copied into an empty `DATA_DIR` on first start |

## API

All image endpoints expect the **raw JPEG as the request body**
(`Content-Type: image/jpeg`), not a multipart form. Error messages
(`detail`) follow the `Accept-Language` header (English or German).

### `POST /read`

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @image.jpg http://localhost:8099/read
```

```json
{
  "value": 506.388,
  "certain": true,
  "digits": [
    {"wheel": 1, "digit": 0, "score": 0.981, "second": 3, "second_score": 0.512},
    "...",
    {"wheel": 8, "digit": 8, "score": 0.913, "second": 6, "second_score": 0.521}
  ],
  "missing_templates": []
}
```

- `value`: all digits combined, the last 3 are decimals
  (`00506388` → `506.388`). Also the best guess when `certain` is `false`,
  `null` only without any template.
- `certain`: `true` only if `score >= MIN_SCORE` and
  `score - second_score >= MIN_MARGIN` hold for **every** wheel.
- `missing_templates`: digits 0–9 without a template. While the list is not
  empty, a never-learned digit can be recognised as a similar one (e.g. 4 as
  8). Your own integrations should check this; the built-in automatic reading
  does.

### `POST /learn?value=506.388`

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @image.jpg "http://localhost:8099/learn?value=506.388"
```

```json
{"saved": 8, "templates_per_digit": {"0": 3, "1": 0, "...": 0, "9": 0}}
```

Archives the image. With learning on, the value is split into digits
(`506.388` → `0 0 5 0 6 3 8 8`) and every digit is learned as a template. A
comma as decimal separator is accepted. **Without a body and with
`reading=<number>`**, the image of one of the last 20 readings is learned and
read again right away.

### `POST /read-camera`

Fetches the current image of the camera `CAMERA` via the Home Assistant API
and reads it. Response like `/read` plus `reading` (its number) for the
training page (`/?reading=<number>`). `400` without camera or token, `502` if
the camera is not reachable.

### `GET /status`, `GET /debug.png`, `GET /health`, `GET /`

| Endpoint | Response |
|---|---|
| `GET /status` | `{"templates_per_digit": {…}, "missing_templates": […], "learning": true, "training_images": 21, "meter_reading": 506.388}` |
| `GET /debug.png[?reading=<number>]` | camera image of the latest (or the given) reading with ROIs (green = certain, red = uncertain) and processed digits |
| `GET /health` | `{"ok": true}` |
| `GET /` | training page; `?reading=<number>` opens one of the last 20 readings, `?lang=en\|de` switches the language |

### `GET /admin` – admin page

| Endpoint | Purpose |
|---|---|
| `GET /admin` | admin page |
| `GET /admin/info` | version, settings, templates per digit, auto-reading |
| `GET /admin/readings` | last 20 readings, newest first |
| `GET /admin/images` | all training images, newest first |
| `GET /admin/images/<name>[?counter=1]` | original or only the counter |
| `POST /admin/images/<name>/value?value=506.388` | correct the value (timestamp stays) |
| `POST /admin/images/<name>/delete` | delete a training image |
| `GET /admin/templates` | templates per digit (PNG as Base64) |
| `POST /admin/rebuild` | rebuild templates from all training images |
| `POST /admin/reset` | delete all training images and templates |
| `GET /admin/auto-reading` | state of the automatic reading |
| `POST /admin/auto-reading/run` | read, check and write now |
| `POST /admin/auto-reading/meter-reading?value=506.388` | set the meter reading by hand |
| `GET /admin/cameras`, `POST /admin/camera?entity_id=…` | list cameras, choose one (add-on: saved, restart) |
| `GET /admin/export.zip` | model export (`images/`, `templates/`, `model.json`) |
| `POST /admin/import?mode=merge\|replace` | ZIP as body; `merge` only takes unknown timestamps, `replace` replaces everything |

With `ADMIN_INGRESS_ONLY=true`, `/admin` only answers requests from the Home
Assistant Supervisor (ingress), everyone else gets `403`.

### Errors

| Status | When |
|---|---|
| `400` | empty body, unreadable or too large image (over 25 megapixels), ROI outside the image, invalid `value`, damaged ZIP |
| `403` | browser request from a foreign website (Origin ≠ Host), or `/admin` without ingress with `ADMIN_INGRESS_ONLY=true` |
| `404` | reading no longer in memory |
| `413` | body larger than 10 MB (images) or 300 MB (model import) |
| `422` | `value` missing |

Response as `{"detail": "<description>"}`. Write requests with an `Origin`
header are only accepted if it matches `Host`. Programs like curl do not send
an `Origin` and are not affected.

## How recognition works

1. **Cut out:** one crop per ROI, 3 px trimmed on the left and right.
2. **"Ink":** `255 - min(blue, green)`. Black **and** red digits appear
   bright on a dark background, whatever the colour of the lighting.
3. **Normalise:** MINMAX to 0–255, GaussianBlur 3×3, size 24×40 px.
4. **Compare:** `cv2.matchTemplate` with `TM_CCOEFF_NORMED` against every
   template, with ±`SHIFT` px leeway. The score of a digit is the best result
   over all its templates.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
DATA_DIR=./data .venv/bin/python wasseruhr_cv/start.py     # locally on port 8099
```

```
repository.yaml          makes the repository a Home Assistant add-on repository
wasseruhr_cv/            the add-on (build context for HA and Docker Compose)
  config.yaml            add-on definition: options, ingress, ports
  translations/          option texts in Home Assistant (en, de)
  Dockerfile, start.py   image and start (options -> environment variables)
  DOCS.md, CHANGELOG.md  documentation shown in the add-on (English and German)
  app/                   the service (FastAPI + OpenCV)
    recognition.py       preprocessing, template matching
    templates.py         store, deduplicate and rebuild templates
    image_archive.py     archive of all training images
    model.py             model export/import (ZIP), bundled model
    admin.py             /admin, admin_page.py its HTML
    training_page.py     training page, debug_image.py /debug.png
    auto_reading.py      reading at intervals, plausibility, writing to HA
    ha.py, camera.py     Home Assistant REST API (states, services, camera)
    security.py          origin check, size limits, security headers
    i18n.py, texts/      English/German: language selection, text catalogues
    migration.py         takes over data and options of version 1.x
    server.py            main port + optional HTTP/HTTPS in one process
    main.py              endpoints, logging
  model/                 initial model: images/ (counter only, PNG), templates/
tests/                   pytest; test images blacked out except for the counter
docker-compose.yml       standalone operation
```

New texts always go into both catalogues (`texts/en.json`, `texts/de.json`).

**Publishing a new version:** raise the version in `wasseruhr_cv/config.yaml`,
`wasseruhr_cv/app/__init__.py` and `pyproject.toml` (a test checks that all
are equal), add an entry to `wasseruhr_cv/CHANGELOG.md`, push to `main`. Home
Assistant then offers the update in the add-on.

## License

[MIT](LICENSE)
