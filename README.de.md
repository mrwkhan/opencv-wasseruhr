# Wasseruhr-CV

[English](README.md) · **Deutsch**

[![CI](https://github.com/mrwkhan/opencv-wasseruhr/actions/workflows/ci.yaml/badge.svg)](https://github.com/mrwkhan/opencv-wasseruhr/actions/workflows/ci.yaml)

Liest das Rollenzählwerk einer Wasseruhr per **klassischem Computer Vision** ab:
OpenCV Template Matching, kein LLM, keine Cloud. Der Dienst lernt die Ziffern
aus Kamerabildern mit bekanntem Zählerstand, erkennt sie danach selbstständig
und schreibt den geprüften Zählerstand nach Home Assistant.

Läuft als **Home-Assistant-Add-on** (z. B. auf dem Home Assistant Green) oder
als eigenständiger Docker-Dienst – ohne weitere Werkzeuge.

- **Automatische Ablesung:** holt alle paar Minuten das Kamerabild aus Home
  Assistant und schreibt nur sichere, plausible Werte (nur vorwärts, höchstens
  so schnell, wie Wasser fließen kann) in einen Sensor fürs Energie-Dashboard
  und optional in einen `input_number`-Helfer
- **Initiales Modell** eingebaut ([wasseruhr_cv/model](wasseruhr_cv/model)),
  beim ersten Start sofort einsatzbereit
- Lernseite und Verwaltung in der Home-Assistant-Seitenleiste: nachtrainieren,
  falsch gelernte Bilder korrigieren oder löschen, Vorlagen ansehen, Modell
  als ZIP sichern und übertragen
- **Deutsch und Englisch:** Seiten, Meldungen, Protokoll und Sensor. Die
  Seiten folgen der Browsersprache und lassen sich auf der Seite umschalten
  (EN/DE), Protokoll und Sensor folgen der Sprache von Home Assistant. Siehe
  [Sprache](#sprache).
- Im Heimnetz optional per **HTTP und/oder HTTPS** erreichbar, Ports frei wählbar
- Einfache HTTP-API (`POST /read` mit dem JPEG) für eigene Anbindungen

## Installation in Home Assistant

[![Repository zu Home Assistant hinzufügen](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fmrwkhan%2Fopencv-wasseruhr)

Oder von Hand:

1. Einstellungen → Add-ons → **Add-on-Store** → Menü (⋮) → **Repositories**
2. `https://github.com/mrwkhan/opencv-wasseruhr` eintragen → **Hinzufügen**
3. **Wasseruhr-CV** auswählen → **Installieren**. Das Image wird auf dem Gerät
   gebaut (Python + OpenCV), das dauert einige Minuten.
4. Im Reiter Info „In der Seitenleiste anzeigen“ und „Watchdog“ einschalten → **Starten**

Unterstützt: `aarch64` (Home Assistant Green/Yellow, Raspberry Pi 4/5 mit
64-Bit-OS) und `amd64`. Einrichtung, Anlernen und Bedienung stehen in der
[Add-on-Dokumentation](wasseruhr_cv/DOCS.md), die auch im Add-on unter
„Dokumentation“ erscheint.

## Erste Schritte

1. **Kamera auswählen:** Seitenleiste → Wasseruhr-CV → Verwaltung → Kamera aus
   der Liste wählen (mit Vorschaubild) → Übernehmen.
2. **ROIs prüfen:** Lernseite → „Kamera jetzt ablesen“. Die eingezeichneten
   Rechtecke müssen auf den Ziffernfenstern liegen, sonst
   [ROIs anpassen](#rois-anpassen).
3. **Modell:** Das initiale Modell wird beim ersten Start übernommen. Für eine
   andere Uhr in der Verwaltung „Modell zurücksetzen“ und auf der Lernseite
   anlernen: richtigen Zählerstand eintragen → „Mit diesem Bild lernen“, bis
   jede Ziffer 0–9 einmal gelernt ist.
4. **Fertig:** Ab jetzt steht der Zählerstand alle 5 Minuten in
   `sensor.wasseruhr_cv_meter_reading`. Fürs Energie-Dashboard: Einstellungen
   → Dashboards → Energie → Wasserverbrauch → diesen Sensor auswählen.

Details zur Automatik, zu HTTP/HTTPS und allen Optionen stehen in der
[Add-on-Dokumentation](wasseruhr_cv/DOCS.md).

## Update von Version 1.x

Version 2.0 verwendet englische Namen für Optionen, Variablen, API-Pfade und
Datenordner. Beim ersten Start wird alles automatisch übernommen:

- **Add-on-Optionen** (`kamera` → `camera`, `lerneffekt` → `learning` …)
  werden unter die neuen Namen kopiert und gespeichert.
- **Daten** (`lernbilder/` → `images/`, `vorlagen/` → `templates/`, der
  bestätigte Zählerstand, das selbstsignierte Zertifikat) werden an Ort und
  Stelle umbenannt.
- **Sensor:** Eine Installation, die in den alten Standardsensor
  `sensor.wasseruhr_cv_zaehlerstand` geschrieben hat, schreibt weiter dorthin,
  damit der Verlauf im Energie-Dashboard weiterläuft. Neue Installationen
  nutzen `sensor.wasseruhr_cv_meter_reading`.
- **Docker:** Die deutschen Variablennamen (`KAMERA`, `LERNEFFEKT` …) und
  Werte (`an`/`aus`) funktionieren weiter. Bitte bei Gelegenheit auf die
  englischen umstellen.
- **API:** Die Pfade der Version 1.x (`/ablesen`, `/lernen?wert=`,
  `/kamera-ablesen`) antworten weiter im alten Format, sind aber nicht mehr
  dokumentiert.

## Eigenständig mit Docker Compose

```bash
git clone https://github.com/mrwkhan/opencv-wasseruhr.git
cd opencv-wasseruhr
docker compose up -d --build
curl http://localhost:8099/health        # -> {"ok":true}
```

Lernseite: `http://<host>:8099/`, Verwaltung: `http://<host>:8099/admin`. Für
die automatische Ablesung `CAMERA`, `HA_URL` und `HA_TOKEN` setzen (siehe
[docker-compose.yml](docker-compose.yml)). Alle Daten liegen in `./data` und
bleiben bei Neustarts und Updates erhalten:

```
data/
  images/              jedes an /learn geschickte Bild, z. B. 20261109T172251000000Z_506.388.jpg
  templates/           daraus erzeugte Ziffern-Vorlagen, <ziffer>/<zeitstempel>_r<rolle>.png
  meter_reading.json   zuletzt bestätigter Zählerstand der Automatik
```

Einstellungen über die Umgebungsvariablen in
[docker-compose.yml](docker-compose.yml), siehe [Konfiguration](#konfiguration).
Protokoll mit Ergebnis und Scores jedes Aufrufs (hier mit `LANGUAGE=de`):

```bash
docker compose logs -f
# ... ablesen #12: wert=506.388 sicher=ja | r1=0(1.00/3:0.51) r2=0(1.00/5:0.53) ...
```

Format pro Rolle: `r<rolle>=<ziffer>(<score>/<zweitbeste>:<score2>)`, ein `!`
markiert eine unsichere Rolle.

> **Sicherheit:** Der Dienst hat kein Passwort. Ports nur im Heimnetz
> betreiben, nie im Router freigeben. Webseiten im Browser können ihm nichts
> beibringen (Ursprungsprüfung), Bilder sind auf 10 MB und 25 Megapixel
> begrenzt. Im Add-on sind HTTP und HTTPS im Heimnetz standardmäßig aus.

> **Datenschutz:** Laufende Lernbilder zeigen die eigene Wasseruhr samt
> Zählerständen. `data/` und Modell-Exporte (`*.zip`) sind deshalb per
> `.gitignore` ausgeschlossen. Das mitgelieferte Modell zeigt nur das Zählwerk;
> ein Test stellt sicher, dass das so bleibt.

## Sprache

Alle Seiten, Meldungen, das Protokoll und der Sensor gibt es auf **Deutsch und
Englisch**.

| Was | Sprache |
|---|---|
| Lernseite, Verwaltung, Fehlermeldungen der API | Umschalter auf der Seite (EN/DE, per Cookie gemerkt) → Option `language` → Browsersprache → Sprache des Dienstes |
| Protokoll, Name und Attribut `reason` des Sensors | Option `language`; bei `auto` die Sprache von Home Assistant, ohne Home Assistant Englisch |
| Add-on-Optionen in Home Assistant | Sprache des Home-Assistant-Benutzers (`translations/`) |

Die Option `language` (Docker: `LANGUAGE`) kennt `auto` (Standard), `en` und
`de`. Alle Namen sind in beiden Sprachen englisch – Optionen, Variablen,
API-Pfade und die Attribute des Sensors: `status`, `reason`, `recognized`,
`last_check` und `source`, wobei `status` einer von `accepted` (übernommen),
`unchanged` (unverändert), `rejected` (verworfen), `error` (Fehler) und `set`
(von Hand gesetzt) ist. Übersetzt werden nur Texte.

**Weitere Sprache ergänzen:** `wasseruhr_cv/app/texts/en.json` nach
`<kürzel>.json` kopieren, die Werte übersetzen (Schlüssel und `{Platzhalter}`
bleiben), das Kürzel in `LANGUAGES` in `wasseruhr_cv/app/i18n.py` und bei der
Option `language` in `config.yaml` eintragen und
`wasseruhr_cv/translations/<kürzel>.yaml` anlegen. Die Tests prüfen, dass alle
Kataloge dieselben Schlüssel und Platzhalter haben.

## Lernbilder & Lerneffekt

**Jedes Bild, das an `/learn` geschickt wird, wird aufbewahrt**, byte-genau
unter `images/<zeitstempel>_<wert>.jpg`. Die Vorlagen sind nur ein
Zwischenergebnis und lassen sich jederzeit aus den Lernbildern neu erzeugen.

| `LEARNING` | Beim Start | `POST /learn` |
|------------|------------|---------------|
| `true` (Standard) | Vorlagen werden **komplett aus allen Lernbildern neu aufgebaut** (älteste zuerst) | Bild archivieren **und** sofort als Vorlage lernen |
| `false` | vorhandene Vorlagen werden unverändert geladen | Bild **nur** archivieren |

Im Add-on ist das der Schalter **Lerneffekt**. Damit lässt sich zum Beispiel:

- **die Erkennung einfrieren**: Ausgeschaltet werden weiter Lernbilder
  gesammelt, die Erkennung bleibt unverändert. Später einschalten, um alles
  nachzulernen.
- **Falsches entfernen**: In der Verwaltung das Lernbild korrigieren oder
  löschen, die Vorlagen werden sofort neu aufgebaut.
- **ROIs ändern**: Neue ROIs setzen und mit eingeschaltetem Lerneffekt neu
  starten. Die Vorlagen entstehen aus den Original-Bildern neu, nichts muss
  neu angelernt werden.

Fast identische Ziffern (Korrelation > 0.97) werden nicht doppelt gespeichert.
Pro Ziffer bleiben höchstens `MAX_TEMPLATES_PER_DIGIT` Vorlagen, die
Lernbilder selbst werden nie automatisch gelöscht. Kontrastlose Ziffern
(Kamera dunkel oder überbelichtet) werden nie zur Vorlage.

Tipps: Bilder bei **unterschiedlicher Beleuchtung** lernen. Die letzte Rolle
dreht sich laufend. Steht sie zwischen zwei Ziffern, die eintragen, die mehr
vom Fenster einnimmt.

## ROIs anpassen

Jede Rolle des Zählwerks wird durch ein Rechteck (ROI) `[x1, y1, x2, y2]` in
Pixeln des Kamerabildes beschrieben: links oben `(x1, y1)`, rechts unten
`(x2, y2)`. Die Liste geht von links (höchste Stelle) nach rechts, die
**letzten 3 Rollen sind die Nachkommastellen** (Liter). Ohne Angabe gelten
Standardwerte für ein 640×480-Bild mit 8 Rollen:

```json
[[130,144,162,196],[173,144,205,196],[216,144,248,196],[260,144,292,196],
 [304,144,336,196],[347,144,379,196],[391,144,423,196],[435,144,467,196]]
```

So findest du die Werte für deine Kamera:

1. Ein Kamerabild in einem Bildprogramm öffnen und für jede Ziffer die
   Pixelkoordinaten des Fensters ablesen. Das Rechteck darf etwas größer als
   die Ziffer sein, links und rechts werden ohnehin je 3 px abgeschnitten.
2. Als einzeiliges JSON eintragen: im Add-on in der Option `rois`, in Docker
   in der Variable `ROIS`.
3. Ein Bild ablesen und die Lernseite öffnen. Die ROIs sind eingezeichnet,
   darunter stehen die aufbereiteten Ziffern so, wie der Matcher sie sieht.
   Jede Ziffer sollte vollständig und mittig zu sehen sein.

## Konfiguration

Im Add-on über die Optionen (Reiter Konfiguration), in Docker über
Umgebungsvariablen. Schalter sind im Add-on Kippschalter; in Docker nehmen sie
`true` oder `false` (auch `on`/`off`, `yes`/`no`, `1`/`0`).

| Variable | Add-on-Option | Standard | Bedeutung |
|---|---|---|---|
| `LEARNING` | `learning` | `true` | siehe [Lerneffekt](#lernbilder--lerneffekt) |
| `ROIS` | `rois` | siehe oben | JSON-Liste `[[x1,y1,x2,y2], …]`, eine pro Rolle, mindestens 4 |
| `MIN_SCORE` | `min_score` | `0.70` | Mindest-Score der besten Ziffer für „sicher“ |
| `MIN_MARGIN` | `min_margin` | `0.08` | Mindestabstand zur zweitbesten Ziffer |
| `MAX_TEMPLATES_PER_DIGIT` | `max_templates_per_digit` | `30` | ältere Vorlagen fallen heraus |
| `SHIFT` | `shift` | `3` | Suchbereich des Template Matchings in px (±) |
| `CAMERA` | `camera` | – | Kamera-Entität, die abgelesen wird |
| `INTERVAL_MINUTES` | `interval_minutes` | `5` | automatische Ablesung, `0` = aus (braucht `CAMERA` und HA-Zugang) |
| `SENSOR` | `sensor` | `sensor.wasseruhr_cv_meter_reading` | Ziel für den Zählerstand, wird angelegt bzw. überschrieben; `none` (Add-on: leer) = kein Sensor |
| `INPUT_NUMBER` | `input_number` | – | optional zusätzlich ein vorhandener Zahlen-Helfer (fehlt er, wird das gemeldet) |
| `MAX_M3_PER_HOUR` | `max_m3_per_hour` | `3` | schnellerer Anstieg = Lesefehler |
| `TOLERANCE_M3` | `tolerance_m3` | `0.002` | kleine Rückwärts-Abweichung ignorieren |
| `REQUIRE_ALL_DIGITS` | `require_all_digits` | `true` | erst schreiben, wenn 0–9 gelernt sind |
| `HTTP` / `HTTP_PORT` | `http` | `false` / `8080` | zusätzlicher HTTP-Listener (Add-on: Port unter Netzwerk, Standard 8099) |
| `HTTPS` / `HTTPS_PORT` | `https` | `false` / `8443` | zusätzlicher HTTPS-Listener (Add-on: Port unter Netzwerk, Standard 8100) |
| `CERTIFICATE` / `CERTIFICATE_KEY` | `certificate` / `certificate_key` | `fullchain.pem` / `privkey.pem` | relativ zu `SSL_DIR` (`/ssl`) oder absolut; fehlt es, wird ein selbstsigniertes erzeugt |
| `LANGUAGE` | `language` | `auto` | `auto`, `en` oder `de`, siehe [Sprache](#sprache) |
| `ADMIN_INGRESS_ONLY` | `admin_ingress_only` | Docker `false`, Add-on `true` | Verwaltung nur über die HA-Seitenleiste |
| `LOG_LEVEL` | `log_level` | `INFO` | `DEBUG` zeigt auch übersprungene Duplikate |
| `PORT` | – | `8099` | Hauptport (Add-on: Ingress/intern, Docker: der freigegebene Port) |
| `HA_URL` | – | `http://supervisor/core/api` | REST-API von HA, für Docker z. B. `http://homeassistant.local:8123/api` |
| `HA_TOKEN` | – | im Add-on automatisch | langlebiges Zugriffstoken (Docker: in `.env`, nie ins Repository) |
| `DATA_DIR` | – | `/data` | Datenverzeichnis mit `images/` und `templates/` |
| `MODEL_DIR` | – | `/opt/wasseruhr/model` | initiales Modell, wird beim ersten Start in ein leeres `DATA_DIR` übernommen |

## API

Alle Bild-Endpunkte erwarten das **rohe JPEG als Request-Body**
(`Content-Type: image/jpeg`), kein Multipart-Formular. Fehlermeldungen
(`detail`) folgen dem Header `Accept-Language` (Deutsch oder Englisch).

### `POST /read`

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @bild.jpg http://localhost:8099/read
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

- `value`: alle Ziffern zusammengesetzt, die letzten 3 sind
  Nachkommastellen (`00506388` → `506.388`). Auch bei `certain: false` die
  beste Schätzung, `null` nur ohne jede Vorlage.
- `certain`: `true` nur, wenn für **jede** Rolle (`wheel`)
  `score >= MIN_SCORE` und `score - second_score >= MIN_MARGIN` gilt.
- `missing_templates`: Ziffern 0–9 ohne Vorlage. Solange die Liste nicht leer
  ist, kann eine nie gelernte Ziffer als ähnliche erkannt werden (z. B. 4 als
  8). Eigene Auswertungen sollten das prüfen; die eingebaute Automatik tut es.

### `POST /learn?value=506.388`

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @bild.jpg "http://localhost:8099/learn?value=506.388"
```

```json
{"saved": 8, "templates_per_digit": {"0": 3, "1": 0, "...": 0, "9": 0}}
```

Archiviert das Bild. Mit eingeschaltetem Lerneffekt wird der Wert in die
Ziffern zerlegt (`506.388` → `0 0 5 0 6 3 8 8`) und jede Ziffer als Vorlage
gelernt. Ein Komma als Dezimaltrenner wird akzeptiert. **Ohne Body mit
`reading=<nummer>`** wird das Bild einer der letzten 20 Ablesungen gelernt
und gleich neu abgelesen.

### `POST /read-camera`

Holt das aktuelle Bild der Kamera `CAMERA` über die Home-Assistant-API und
liest es ab. Antwort wie `/read` plus `reading` (ihre Nummer) für die
Lernseite (`/?reading=<nummer>`). `400` ohne Kamera oder Token, `502` wenn die
Kamera nicht erreichbar ist.

### `GET /status`, `GET /debug.png`, `GET /health`, `GET /`

| Endpunkt | Antwort |
|---|---|
| `GET /status` | `{"templates_per_digit": {…}, "missing_templates": […], "learning": true, "training_images": 21, "meter_reading": 506.388}` |
| `GET /debug.png[?reading=<nummer>]` | Kamerabild der letzten (bzw. angegebenen) Ablesung mit ROIs (grün = sicher, rot = unsicher) und aufbereiteten Ziffern |
| `GET /health` | `{"ok": true}` |
| `GET /` | Lernseite; `?reading=<nummer>` öffnet eine der letzten 20 Ablesungen, `?lang=de\|en` schaltet die Sprache um |

### `GET /admin` – Verwaltung

| Endpunkt | Zweck |
|---|---|
| `GET /admin` | Verwaltungsseite |
| `GET /admin/info` | Version, Einstellungen, Vorlagen pro Ziffer, Automatik |
| `GET /admin/readings` | letzte 20 Ablesungen, neueste zuerst |
| `GET /admin/images` | alle Lernbilder, neueste zuerst |
| `GET /admin/images/<name>[?counter=1]` | Original bzw. nur das Zählwerk |
| `POST /admin/images/<name>/value?value=506.388` | Wert korrigieren (Zeitstempel bleibt) |
| `POST /admin/images/<name>/delete` | Lernbild löschen |
| `GET /admin/templates` | Vorlagen je Ziffer (PNG als Base64) |
| `POST /admin/rebuild` | Vorlagen aus allen Lernbildern neu aufbauen |
| `POST /admin/reset` | alle Lernbilder und Vorlagen löschen |
| `GET /admin/auto-reading` | Zustand der Automatik |
| `POST /admin/auto-reading/run` | jetzt ablesen, prüfen und schreiben |
| `POST /admin/auto-reading/meter-reading?value=506.388` | Zählerstand von Hand setzen |
| `GET /admin/cameras`, `POST /admin/camera?entity_id=…` | Kameras auflisten, eine wählen (Add-on: gespeichert, Neustart) |
| `GET /admin/export.zip` | Modell-Export (`images/`, `templates/`, `model.json`) |
| `POST /admin/import?mode=merge\|replace` | ZIP als Body; `merge` übernimmt nur unbekannte Zeitstempel, `replace` ersetzt alles |

Mit `ADMIN_INGRESS_ONLY=true` beantwortet `/admin` nur Anfragen des
Home-Assistant-Supervisors (Ingress), alle anderen bekommen `403`.

### Fehler

| Status | Wann |
|---|---|
| `400` | leerer Body, unlesbares oder zu großes Bild (über 25 Megapixel), ROI außerhalb des Bildes, ungültiger `value`, beschädigtes ZIP |
| `403` | Browser-Anfrage von einer fremden Webseite (Origin ≠ Host), oder `/admin` ohne Ingress bei `ADMIN_INGRESS_ONLY=true` |
| `404` | Ablesung nicht mehr im Speicher |
| `413` | Body größer als 10 MB (Bilder) bzw. 300 MB (Modell-Import) |
| `422` | `value` fehlt |

Antwort jeweils als `{"detail": "<Beschreibung>"}`. Schreibende Anfragen mit
einem `Origin`-Header werden nur angenommen, wenn er zum `Host` passt.
Programme wie curl senden keinen `Origin` und sind nicht betroffen.

## So funktioniert die Erkennung

1. **Ausschneiden:** pro ROI ein Ausschnitt, links/rechts je 3 px gekürzt.
2. **„Tinte“:** `255 - min(Blau, Grün)`. Schwarze **und** rote Ziffern
   erscheinen hell auf dunklem Grund, egal welche Farbe die Beleuchtung hat.
3. **Normieren:** MINMAX auf 0–255, GaussianBlur 3×3, Größe 24×40 px.
4. **Vergleichen:** `cv2.matchTemplate` mit `TM_CCOEFF_NORMED` gegen jede
   Vorlage, mit ±`SHIFT` px Spielraum. Der Score einer Ziffer ist das beste
   Ergebnis über alle ihre Vorlagen.

## Entwicklung

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
DATA_DIR=./data .venv/bin/python wasseruhr_cv/start.py     # lokal auf Port 8099
```

Aufbau des Repositorys: siehe [README.md](README.md#development) (Code und
Bezeichner sind englisch). Neue Texte immer in beide Kataloge eintragen
(`texts/en.json`, `texts/de.json`).

**Neue Version veröffentlichen:** Version in `wasseruhr_cv/config.yaml`,
`wasseruhr_cv/app/__init__.py` und `pyproject.toml` erhöhen (ein Test prüft,
dass alle gleich sind), Eintrag in `wasseruhr_cv/CHANGELOG.md`, auf `main`
pushen. Home Assistant bietet das Update dann im Add-on an.

## Lizenz

[MIT](LICENSE)
