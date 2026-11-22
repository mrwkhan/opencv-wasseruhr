# Wasseruhr-CV

[![CI](https://github.com/mrwkhan/opencv-wasseruhr/actions/workflows/ci.yaml/badge.svg)](https://github.com/mrwkhan/opencv-wasseruhr/actions/workflows/ci.yaml)

Liest das Rollenzählwerk einer Wasseruhr per **klassischem Computer Vision** ab:
OpenCV Template Matching, kein LLM, keine Cloud. Der Dienst lernt die Ziffern
aus Kamerabildern mit bekanntem Zählerstand und erkennt sie danach selbstständig.

Läuft als **Home-Assistant-Add-on** (z. B. auf dem Home Assistant Green) oder
als eigenständiger Docker-Dienst.

- Lernseite und Verwaltung in der Home-Assistant-Seitenleiste
- Nachtrainieren jederzeit: falsch gelernte Bilder korrigieren oder löschen,
  Vorlagen ansehen, Modell als ZIP sichern und übertragen
- „Kamera jetzt ablesen“ direkt über die Home-Assistant-API
- Einfache HTTP-API (`POST /ablesen` mit dem JPEG), fertiger
  [Node-RED-Flow](node-red/) schreibt nur sichere und plausible Werte nach HA

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

1. **Kamera einstellen:** Option `kamera` des Add-ons, z. B. `camera.wasseruhr`.
2. **ROIs prüfen:** Lernseite → „Kamera jetzt ablesen“. Die eingezeichneten
   Rechtecke müssen auf den Ziffernfenstern liegen, sonst
   [ROIs anpassen](#rois-anpassen).
3. **Anlernen:** Richtigen Zählerstand eintragen → „Mit diesem Bild lernen“.
   Wiederholen, bis jede Ziffer 0–9 einmal gelernt ist. Ein vorhandenes Modell
   lässt sich stattdessen in der Verwaltung als ZIP importieren.
4. **Anbinden:** den [Node-RED-Flow](node-red/) importieren oder die
   [API](#api) direkt nutzen.

## Eigenständig mit Docker Compose

```bash
git clone https://github.com/mrwkhan/opencv-wasseruhr.git
cd opencv-wasseruhr
docker compose up -d --build
curl http://localhost:8099/health        # -> {"ok":true}
```

Lernseite: `http://<host>:8099/`, Verwaltung: `http://<host>:8099/admin`.
Alle Daten liegen in `./data` und bleiben bei Neustarts und Updates erhalten:

```
data/
  lernbilder/   jedes an /lernen geschickte Bild, z. B. 20261109T172251000000Z_506.388.jpg
  vorlagen/     daraus erzeugte Ziffern-Vorlagen, <ziffer>/<zeitstempel>_r<rolle>.png
```

Einstellungen über die Umgebungsvariablen in [docker-compose.yml](docker-compose.yml),
siehe [Konfiguration](#konfiguration). Logs mit Ergebnis und Scores jedes Aufrufs:

```bash
docker compose logs -f
# ... ablesen #12: wert=506.388 sicher=ja | r1=0(1.00/3:0.51) r2=0(1.00/5:0.53) ...
```

Format pro Rolle: `r<rolle>=<ziffer>(<score>/<zweitbeste>:<score2>)`, ein `!`
markiert eine unsichere Rolle.

> **Sicherheit:** Der Dienst hat kein Passwort. Port 8099 nur im Heimnetz
> betreiben, nie im Router freigeben. Webseiten im Browser können ihm nichts
> beibringen (Ursprungsprüfung), Bilder sind auf 10 MB und 25 Megapixel
> begrenzt. Im Add-on ist der Port standardmäßig geschlossen.

> **Datenschutz:** Lernbilder zeigen die eigene Wasseruhr samt Zählerständen.
> `data/` und Modell-Exporte (`*.zip`) sind deshalb per `.gitignore` vom
> Repository ausgeschlossen. Nicht öffentlich teilen.

## Lernbilder & Lerneffekt

**Jedes Bild, das an `/lernen` geschickt wird, wird aufbewahrt**, byte-genau
unter `lernbilder/<zeitstempel>_<wert>.jpg`. Die Vorlagen sind nur ein
Zwischenergebnis und lassen sich jederzeit aus den Lernbildern neu erzeugen.

| `LERNEFFEKT` | Beim Start | `POST /lernen` |
|--------------|------------|----------------|
| `an` (Standard) | Vorlagen werden **komplett aus allen Lernbildern neu aufgebaut** (älteste zuerst) | Bild archivieren **und** sofort als Vorlage lernen |
| `aus` | Vorhandene Vorlagen werden unverändert geladen | Bild **nur** archivieren |

Damit lässt sich zum Beispiel:

- **die Erkennung einfrieren**: Mit `aus` werden weiter Lernbilder gesammelt,
  die Erkennung bleibt unverändert. Später mit `an` alles nachlernen.
- **Falsches entfernen**: In der Verwaltung das Lernbild korrigieren oder
  löschen, die Vorlagen werden sofort neu aufgebaut.
- **ROIs ändern**: Neue ROIs setzen und mit `an` neu starten. Die Vorlagen
  entstehen aus den Original-Bildern neu, nichts muss neu angelernt werden.

Fast identische Ziffern (Korrelation > 0.97) werden nicht doppelt gespeichert.
Pro Ziffer bleiben höchstens `MAX_VORLAGEN_PRO_ZIFFER` Vorlagen, die Lernbilder
selbst werden nie automatisch gelöscht. Kontrastlose Ziffern (Kamera dunkel
oder überbelichtet) werden nie zur Vorlage.

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
Umgebungsvariablen:

| Variable | Add-on-Option | Standard | Bedeutung |
|---|---|---|---|
| `LERNEFFEKT` | `lerneffekt` | `an` | `an`/`aus`, siehe [Lerneffekt](#lernbilder--lerneffekt) |
| `ROIS` | `rois` | siehe oben | JSON-Liste `[[x1,y1,x2,y2], …]`, eine pro Rolle, mindestens 4 |
| `MIN_SCORE` | `min_score` | `0.70` | Mindest-Score der besten Ziffer für „sicher“ |
| `MIN_ABSTAND` | `min_abstand` | `0.08` | Mindestabstand zur zweitbesten Ziffer |
| `MAX_VORLAGEN_PRO_ZIFFER` | `max_vorlagen_pro_ziffer` | `30` | ältere Vorlagen fallen heraus |
| `VERSCHIEBUNG` | `verschiebung` | `3` | Suchbereich des Template Matchings in px (±) |
| `KAMERA` | `kamera` | – | Kamera-Entität für [„Kamera jetzt ablesen“](#post-kamera-ablesen) |
| `ADMIN_NUR_INGRESS` | `admin_nur_ueber_ingress` | Docker `aus`, Add-on `an` | Verwaltung nur über die HA-Seitenleiste |
| `LOG_LEVEL` | `log_level` | `INFO` | `DEBUG` zeigt auch übersprungene Duplikate |
| `HA_URL` | – | `http://supervisor/core/api` | REST-API von HA, für Docker z. B. `http://homeassistant.local:8123/api` |
| `HA_TOKEN` | – | im Add-on automatisch | Langlebiges Zugriffstoken (Docker: in `.env`, nie ins Repository) |
| `DATA_DIR` | – | `/data` | Datenverzeichnis mit `lernbilder/` und `vorlagen/` |
| `MODELL_DIR` | – | `/opt/wasseruhr/modell` | Optionales eingebautes Modell, wird beim ersten Start in ein leeres `DATA_DIR` übernommen |

## API

Alle Bild-Endpunkte erwarten das **rohe JPEG als Request-Body**
(`Content-Type: image/jpeg`), kein Multipart-Formular.

### `POST /ablesen`

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @bild.jpg http://localhost:8099/ablesen
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

- `wert`: alle Ziffern zusammengesetzt, die letzten 3 sind Nachkommastellen
  (`00506388` → `506.388`). Auch bei `sicher: false` die beste Schätzung,
  `null` nur ohne jede Vorlage.
- `sicher`: `true` nur, wenn für **jede** Rolle `score >= MIN_SCORE` und
  `score - score2 >= MIN_ABSTAND` gilt.
- `fehlende_vorlagen`: Ziffern 0–9 ohne Vorlage. Solange die Liste nicht leer
  ist, kann eine nie gelernte Ziffer als ähnliche erkannt werden (z. B. 4 als 8).
  Auswertungen sollten das prüfen. Der Node-RED-Flow tut es.

### `POST /lernen?wert=506.388`

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @bild.jpg "http://localhost:8099/lernen?wert=506.388"
```

```json
{"gespeichert": 8, "vorlagen_pro_ziffer": {"0": 3, "1": 0, "...": 0, "9": 0}}
```

Archiviert das Bild. Mit `LERNEFFEKT=an` wird der Wert in die Ziffern zerlegt
(`506.388` → `0 0 5 0 6 3 8 8`) und jede Ziffer als Vorlage gelernt. Ein Komma
als Dezimaltrenner wird akzeptiert. **Ohne Body mit `ablesung=<nr>`** wird das
Bild einer der letzten 20 Ablesungen gelernt und gleich neu abgelesen.

### `POST /kamera-ablesen`

Holt das aktuelle Bild der Kamera `KAMERA` über die Home-Assistant-API und
liest es ab. Antwort wie `/ablesen` plus `nr` für die Lernseite (`/?nr=<nr>`).
`400` ohne Kamera oder Token, `502` wenn die Kamera nicht erreichbar ist.

### `GET /status`, `GET /debug.png`, `GET /health`, `GET /`

| Endpunkt | Antwort |
|---|---|
| `GET /status` | `{"vorlagen_pro_ziffer": {…}, "fehlende_vorlagen": […], "lerneffekt": true, "lernbilder": 21}` |
| `GET /debug.png?letztes=1` / `?nr=<nr>` | Kamerabild mit ROIs (grün = sicher, rot = unsicher) und aufbereiteten Ziffern |
| `GET /health` | `{"ok": true}` |
| `GET /` | Lernseite, `?nr=<nr>` öffnet eine der letzten 20 Ablesungen |

### `GET /admin` – Verwaltung

| Endpunkt | Zweck |
|---|---|
| `GET /admin` | Verwaltungsseite |
| `GET /admin/info` | Version, Einstellungen, Vorlagen pro Ziffer |
| `GET /admin/ablesungen` | letzte 20 Ablesungen, neueste zuerst |
| `GET /admin/lernbilder` | alle Lernbilder, neueste zuerst |
| `GET /admin/lernbilder/<name>[?ausschnitt=1]` | Original bzw. nur das Zählwerk |
| `POST /admin/lernbilder/<name>/wert?wert=506.388` | Wert korrigieren (Zeitstempel bleibt) |
| `POST /admin/lernbilder/<name>/loeschen` | Lernbild löschen |
| `GET /admin/vorlagen` | Vorlagen je Ziffer (PNG als Base64) |
| `POST /admin/neu-aufbauen` | Vorlagen aus allen Lernbildern neu aufbauen |
| `GET /admin/export.zip` | Modell-Export (`lernbilder/`, `vorlagen/`, `modell.json`) |
| `POST /admin/import?modus=ergaenzen\|ersetzen` | ZIP als Body; `ergaenzen` übernimmt nur unbekannte Zeitstempel |

Mit `ADMIN_NUR_INGRESS=an` beantwortet `/admin` nur Anfragen des
Home-Assistant-Supervisors (Ingress), alle anderen bekommen `403`.

### Fehler

| Status | Wann |
|---|---|
| `400` | leerer Body, unlesbares oder zu großes Bild (über 25 Megapixel), ROI außerhalb des Bildes, ungültiger `wert`, beschädigtes ZIP |
| `403` | Browser-Anfrage von einer fremden Webseite (Origin ≠ Host), oder `/admin` ohne Ingress bei `ADMIN_NUR_INGRESS=an` |
| `404` | Ablesung nicht mehr im Speicher |
| `413` | Body größer als 10 MB (Bilder) bzw. 300 MB (Modell-Import) |
| `422` | `wert` fehlt |

Antwort jeweils als `{"detail": "<Beschreibung>"}`. Schreibende Anfragen mit
einem `Origin`-Header werden nur angenommen, wenn er zum `Host` passt.
Programme wie Node-RED oder curl senden keinen `Origin` und sind nicht betroffen.

## So funktioniert die Erkennung

1. **Ausschneiden:** pro ROI ein Ausschnitt, links/rechts je 3 px gekürzt.
2. **„Tinte“:** `255 - min(Blau, Grün)`. Schwarze **und** rote Ziffern
   erscheinen hell auf dunklem Grund, egal welche Farbe die Beleuchtung hat.
3. **Normieren:** MINMAX auf 0–255, GaussianBlur 3×3, Größe 24×40 px.
4. **Vergleichen:** `cv2.matchTemplate` mit `TM_CCOEFF_NORMED` gegen jede
   Vorlage, mit ±`VERSCHIEBUNG` px Spielraum. Der Score einer Ziffer ist das
   beste Ergebnis über alle ihre Vorlagen.

## Entwicklung

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
DATA_DIR=./data .venv/bin/python wasseruhr_cv/start.py     # lokal auf Port 8099
```

```
repository.yaml          macht das Repository zum Home-Assistant-Add-on-Repository
wasseruhr_cv/            das Add-on (Build-Kontext für HA und Docker Compose)
  config.yaml            Add-on-Definition: Optionen, Ingress, Port
  Dockerfile, start.py   Image und Start (Optionen -> Umgebungsvariablen)
  DOCS.md, CHANGELOG.md  im Add-on angezeigte Dokumentation
  app/                   der Dienst (FastAPI + OpenCV)
    erkennung.py         Aufbereitung, Template Matching
    vorlagen.py          Vorlagen speichern, deduplizieren, neu aufbauen
    lernbilder.py        Archiv aller Lernbilder
    modell.py            Modell-Export/-Import (ZIP)
    verwaltung.py        /admin, verwaltungsseite.py ihr HTML
    lernseite.py         Lernseite, debugbild.py /debug.png, kamera.py HA-Kamera
    main.py              Endpunkte, Logging
  modell/                optionales eingebautes Modell (im Repository leer)
node-red/                Flow + Anleitung für Node-RED
tests/                   pytest; Testbilder bis auf das Zählwerk geschwärzt
docker-compose.yml       eigenständiger Betrieb
```

**Neue Version veröffentlichen:** Version in `wasseruhr_cv/config.yaml`,
`wasseruhr_cv/app/__init__.py` und `pyproject.toml` erhöhen (ein Test prüft,
dass alle gleich sind), Eintrag in `wasseruhr_cv/CHANGELOG.md`, auf `main`
pushen. Home Assistant bietet das Update dann im Add-on an.

## Lizenz

[MIT](LICENSE)
