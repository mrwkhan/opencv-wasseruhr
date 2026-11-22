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
- **Bundled initial model** ([wasseruhr_cv/modell](wasseruhr_cv/modell)),
  ready to use on first start
- Training page and admin page in the Home Assistant sidebar: train more,
  correct or delete wrongly learned images, view templates, back up and
  transfer the model as a ZIP
- **English and German:** pages, messages, log and sensor. The pages follow
  the browser language and can be switched on the page (DE/EN), the log and
  sensor follow the Home Assistant language. See [Language](#language).
- Optionally reachable in the local network via **HTTP and/or HTTPS**, ports
  freely selectable
- Simple HTTP API (`POST /ablesen` with the JPEG) for your own integrations

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

1. **Select the camera:** sidebar → Wasseruhr → Admin → pick the camera from
   the list (with preview) → Apply.
2. **Check the ROIs:** training page → "Read camera now". The drawn
   rectangles must sit on the digit windows, otherwise
   [adjust the ROIs](#adjusting-the-rois).
3. **Model:** the initial model is installed on first start. For a different
   meter, use "Reset model" on the admin page and teach it on the training
   page: enter the correct meter reading → "Learn from this image", until
   every digit 0–9 has been learned once.
4. **Done:** from now on the reading is in `sensor.wasseruhr_cv_zaehlerstand`
   every 5 minutes. For the Energy dashboard: Settings → Dashboards → Energy
   → Water consumption → select this sensor.

Details on automatic reading, HTTP/HTTPS and all options are in the
[add-on documentation](wasseruhr_cv/DOCS.md).

## Standalone with Docker Compose

```bash
git clone https://github.com/mrwkhan/opencv-wasseruhr.git
cd opencv-wasseruhr
docker compose up -d --build
curl http://localhost:8099/health        # -> {"ok":true}
```

Training page: `http://<host>:8099/`, admin page: `http://<host>:8099/admin`.
For automatic reading set `KAMERA`, `HA_URL` and `HA_TOKEN` (see
[docker-compose.yml](docker-compose.yml)). All data lives in `./data` and
survives restarts and updates:

```
data/
  lernbilder/   every image sent to /lernen, e.g. 20261109T172251000000Z_506.388.jpg
  vorlagen/     digit templates created from them, <digit>/<timestamp>_r<wheel>.png
```

Settings via the environment variables in [docker-compose.yml](docker-compose.yml),
see [Configuration](#configuration). Log with the result and scores of every
call:

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
| Training page, admin page, API error messages | Switch on the page (DE/EN, remembered in a cookie) → option `sprache` → browser language → service language |
| Log, sensor name and `reason` attribute | Option `sprache`; with `auto` the language of Home Assistant, without Home Assistant English |
| Add-on options in Home Assistant | Home Assistant user language (`translations/`) |

The option `sprache` (Docker: `SPRACHE`) accepts `auto` (default), `de` or
`en`. Codes that automations rely on are language-neutral: the sensor
attributes are `status`, `reason`, `recognized`, `last_check` and `source`,
and `status` is one of `accepted`, `unchanged`, `rejected`, `error`, `set`.

**Adding a language:** copy `wasseruhr_cv/app/texte/en.json` to
`<code>.json`, translate the values (keep the keys and `{placeholders}`), add
the code to `SPRACHEN` in `wasseruhr_cv/app/sprache.py` and to the `sprache`
option in `config.yaml`, and add `wasseruhr_cv/translations/<code>.yaml`. The
tests check that every catalogue has the same keys and placeholders.

## Training images & learning

**Every image sent to `/lernen` is kept**, byte for byte, as
`lernbilder/<timestamp>_<value>.jpg`. The templates are only an intermediate
result and can be rebuilt from the training images at any time.

| `LERNEFFEKT` | On start | `POST /lernen` |
|--------------|----------|----------------|
| `an` (default) | Templates are **completely rebuilt from all training images** (oldest first) | Archive the image **and** learn it as a template right away |
| `aus` | Existing templates are loaded unchanged | **Only** archive the image |

This lets you, for example:

- **freeze recognition**: with `aus`, training images keep being collected
  while recognition stays unchanged. Later, learn everything with `an`.
- **remove wrong data**: correct or delete the training image on the admin
  page, the templates are rebuilt immediately.
- **change ROIs**: set new ROIs and restart with `an`. The templates are
  regenerated from the original images, nothing has to be taught again.

Nearly identical digits (correlation > 0.97) are not stored twice. At most
`MAX_VORLAGEN_PRO_ZIFFER` templates are kept per digit; the training images
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

In the add-on via the options (Configuration tab), in Docker via
environment variables:

| Variable | Add-on option | Default | Meaning |
|---|---|---|---|
| `LERNEFFEKT` | `lerneffekt` | `an` | `an`/`aus` (also `on`/`off`), see [learning](#training-images--learning) |
| `ROIS` | `rois` | see above | JSON list `[[x1,y1,x2,y2], …]`, one per wheel, at least 4 |
| `MIN_SCORE` | `min_score` | `0.70` | minimum score of the best digit for "certain" |
| `MIN_ABSTAND` | `min_abstand` | `0.08` | minimum margin to the second-best digit |
| `MAX_VORLAGEN_PRO_ZIFFER` | `max_vorlagen_pro_ziffer` | `30` | older templates are dropped |
| `VERSCHIEBUNG` | `verschiebung` | `3` | search range of the template matching in px (±) |
| `KAMERA` | `kamera` | – | camera entity that is read |
| `INTERVALL_MINUTEN` | `intervall_minuten` | `5` | automatic reading, `0` = off (needs `KAMERA` and HA access) |
| `SENSOR` | `sensor` | `sensor.wasseruhr_cv_zaehlerstand` | target for the meter reading, created or overwritten; `-`/`off` = no sensor |
| `INPUT_NUMBER` | `input_number` | – | optionally also an existing number helper (reported if missing) |
| `MAX_M3_PRO_STUNDE` | `max_m3_pro_stunde` | `3` | faster increase = reading error |
| `TOLERANZ_M3` | `toleranz_m3` | `0.002` | ignore small backward deviations |
| `ALLE_ZIFFERN_GELERNT` | `alle_ziffern_gelernt` | `an` | only write once 0–9 are learned |
| `HTTP` / `HTTP_PORT` | `http` | `aus` / `8080` | additional HTTP listener (add-on: port under Network, default 8099) |
| `HTTPS` / `HTTPS_PORT` | `https` | `aus` / `8443` | additional HTTPS listener (add-on: port under Network, default 8100) |
| `ZERTIFIKAT` / `SCHLUESSEL` | `zertifikat` / `schluessel` | `fullchain.pem` / `privkey.pem` | relative to `SSL_VERZEICHNIS` (`/ssl`) or absolute; if missing, a self-signed one is created |
| `SPRACHE` | `sprache` | `auto` | `auto`, `de` or `en`, see [Language](#language) |
| `PORT` | – | `8099` | main port (add-on: ingress/internal, Docker: the published port) |
| `ADMIN_NUR_INGRESS` | `admin_nur_ueber_ingress` | Docker `aus`, add-on `an` | admin page only via the HA sidebar |
| `LOG_LEVEL` | `log_level` | `INFO` | `DEBUG` also shows skipped duplicates |
| `HA_URL` | – | `http://supervisor/core/api` | Home Assistant REST API, for Docker e.g. `http://homeassistant.local:8123/api` |
| `HA_TOKEN` | – | automatic in the add-on | long-lived access token (Docker: in `.env`, never in the repository) |
| `DATA_DIR` | – | `/data` | data directory with `lernbilder/` and `vorlagen/` |
| `MODELL_DIR` | – | `/opt/wasseruhr/modell` | initial model, copied into an empty `DATA_DIR` on first start |

The option and variable names are German and stay that way, so existing
configurations keep working.

## API

All image endpoints expect the **raw JPEG as the request body**
(`Content-Type: image/jpeg`), not a multipart form. Error messages
(`detail`) follow the `Accept-Language` header (English or German).

### `POST /ablesen` (read)

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @image.jpg http://localhost:8099/ablesen
```

```json
{
  "wert": 506.388,
  "sicher": true,
  "ziffern": [
    {"rolle": 1, "ziffer": 0, "score": 0.981, "zweitbeste": 3, "score2": 0.512},
    "...",
    {"rolle": 8, "ziffer": 8, "score": 0.913, "zweitbeste": 6, "score2": 0.521}
  ],
  "fehlende_vorlagen": []
}
```

- `wert` (value): all digits combined, the last 3 are decimals
  (`00506388` → `506.388`). Also the best guess when `sicher: false`, `null`
  only without any template.
- `sicher` (certain): `true` only if `score >= MIN_SCORE` and
  `score - score2 >= MIN_ABSTAND` hold for **every** wheel (`rolle`).
- `fehlende_vorlagen` (missing templates): digits 0–9 without a template.
  While the list is not empty, a never-learned digit can be recognised as a
  similar one (e.g. 4 as 8). Your own integrations should check this; the
  built-in automatic reading does.

### `POST /lernen?wert=506.388` (learn)

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @image.jpg "http://localhost:8099/lernen?wert=506.388"
```

```json
{"gespeichert": 8, "vorlagen_pro_ziffer": {"0": 3, "1": 0, "...": 0, "9": 0}}
```

Archives the image. With `LERNEFFEKT=an` the value is split into digits
(`506.388` → `0 0 5 0 6 3 8 8`) and every digit is learned as a template. A
comma as decimal separator is accepted. **Without a body and with
`ablesung=<nr>`**, the image of one of the last 20 readings is learned and
read again right away.

### `POST /kamera-ablesen` (read camera)

Fetches the current image of the camera `KAMERA` via the Home Assistant API
and reads it. Response like `/ablesen` plus `nr` for the training page
(`/?nr=<nr>`). `400` without camera or token, `502` if the camera is not
reachable.

### `GET /status`, `GET /debug.png`, `GET /health`, `GET /`

| Endpoint | Response |
|---|---|
| `GET /status` | `{"vorlagen_pro_ziffer": {…}, "fehlende_vorlagen": […], "lerneffekt": true, "lernbilder": 21, "zaehlerstand": 506.388}` |
| `GET /debug.png?letztes=1` / `?nr=<nr>` | camera image with ROIs (green = certain, red = uncertain) and processed digits |
| `GET /health` | `{"ok": true}` |
| `GET /` | training page, `?nr=<nr>` opens one of the last 20 readings, `?sprache=en\|de` switches the language |

### `GET /admin` – admin page

| Endpoint | Purpose |
|---|---|
| `GET /admin` | admin page |
| `GET /admin/info` | version, settings, templates per digit |
| `GET /admin/ablesungen` | last 20 readings, newest first |
| `GET /admin/lernbilder` | all training images, newest first |
| `GET /admin/lernbilder/<name>[?ausschnitt=1]` | original or only the counter |
| `POST /admin/lernbilder/<name>/wert?wert=506.388` | correct the value (timestamp stays) |
| `POST /admin/lernbilder/<name>/loeschen` | delete a training image |
| `GET /admin/vorlagen` | templates per digit (PNG as Base64) |
| `POST /admin/neu-aufbauen` | rebuild templates from all training images |
| `GET /admin/export.zip` | model export (`lernbilder/`, `vorlagen/`, `modell.json`) |
| `POST /admin/import?modus=ergaenzen\|ersetzen` | ZIP as body; `ergaenzen` (also `merge`) only takes unknown timestamps, `ersetzen` (also `replace`) replaces everything |

With `ADMIN_NUR_INGRESS=an`, `/admin` only answers requests from the Home
Assistant Supervisor (ingress), everyone else gets `403`.

### Errors

| Status | When |
|---|---|
| `400` | empty body, unreadable or too large image (over 25 megapixels), ROI outside the image, invalid `wert`, damaged ZIP |
| `403` | browser request from a foreign website (Origin ≠ Host), or `/admin` without ingress with `ADMIN_NUR_INGRESS=an` |
| `404` | reading no longer in memory |
| `413` | body larger than 10 MB (images) or 300 MB (model import) |
| `422` | `wert` missing |

Response as `{"detail": "<description>"}`. Write requests with an `Origin`
header are only accepted if it matches `Host`. Programs like curl do not send
an `Origin` and are not affected.

## How recognition works

1. **Cut out:** one crop per ROI, 3 px trimmed on the left and right.
2. **"Ink":** `255 - min(blue, green)`. Black **and** red digits appear
   bright on a dark background, whatever the colour of the lighting.
3. **Normalise:** MINMAX to 0–255, GaussianBlur 3×3, size 24×40 px.
4. **Compare:** `cv2.matchTemplate` with `TM_CCOEFF_NORMED` against every
   template, with ±`VERSCHIEBUNG` px leeway. The score of a digit is the best
   result over all its templates.

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
  translations/          option texts in Home Assistant (de, en)
  Dockerfile, start.py   image and start (options -> environment variables)
  DOCS.md, CHANGELOG.md  documentation shown in the add-on (English and German)
  app/                   the service (FastAPI + OpenCV)
    erkennung.py         preprocessing, template matching
    vorlagen.py          store, deduplicate and rebuild templates
    lernbilder.py        archive of all training images
    modell.py            model export/import (ZIP)
    verwaltung.py        /admin, verwaltungsseite.py its HTML
    lernseite.py         training page, debugbild.py /debug.png
    automatik.py         reading at intervals, plausibility, writing to HA
    ha.py, kamera.py     Home Assistant REST API (states, services, camera)
    schutz.py            origin check, size limits, security headers
    sprache.py           English/German: language selection, translation
    texte/               text catalogues de.json, en.json
    server.py            main port + optional HTTP/HTTPS in one process
    main.py              endpoints, logging
  modell/                initial model: lernbilder/ (counter only, PNG), vorlagen/
tests/                   pytest; test images blacked out except for the counter
docker-compose.yml       standalone operation
```

The code itself (identifiers, comments) is German; everything users see is
available in both languages.

**Publishing a new version:** raise the version in `wasseruhr_cv/config.yaml`,
`wasseruhr_cv/app/__init__.py` and `pyproject.toml` (a test checks that all
are equal), add an entry to `wasseruhr_cv/CHANGELOG.md`, push to `main`. Home
Assistant then offers the update in the add-on.

## License

[MIT](LICENSE)
