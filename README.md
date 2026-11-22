# Wasseruhr-CV

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
- **Initiales Modell** eingebaut ([wasseruhr_cv/modell](wasseruhr_cv/modell)),
  beim ersten Start sofort einsatzbereit
- Lernseite und Verwaltung in der Home-Assistant-Seitenleiste: nachtrainieren,
  falsch gelernte Bilder korrigieren oder löschen, Vorlagen ansehen, Modell
  als ZIP sichern und übertragen
- Im Heimnetz optional per **HTTP und/oder HTTPS** erreichbar, Ports frei wählbar
- Einfache HTTP-API (`POST /ablesen` mit dem JPEG) für eigene Anbindungen

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

1. **Kamera auswählen:** Seitenleiste → Wasseruhr → Verwaltung → Kamera aus der
   Liste wählen (mit Vorschaubild) → Übernehmen.
2. **ROIs prüfen:** Lernseite → „Kamera jetzt ablesen“. Die eingezeichneten
   Rechtecke müssen auf den Ziffernfenstern liegen, sonst
   [ROIs anpassen](#rois-anpassen).
3. **Modell:** Das initiale Modell wird beim ersten Start übernommen. Für eine
   andere Uhr in der Verwaltung „Modell zurücksetzen“ und auf der Lernseite
   anlernen: richtigen Zählerstand eintragen → „Mit diesem Bild lernen“, bis
   jede Ziffer 0–9 einmal gelernt ist.
4. **Fertig:** Ab jetzt steht der Zählerstand alle 5 Minuten in
   `sensor.wasseruhr_cv_zaehlerstand`. Fürs Energie-Dashboard: Einstellungen →
   Dashboards → Energie → Wasserverbrauch → diesen Sensor auswählen.

Details zur Automatik, zu HTTP/HTTPS und allen Optionen stehen in der
[Add-on-Dokumentation](wasseruhr_cv/DOCS.md).

## Eigenständig mit Docker Compose

```bash
git clone https://github.com/mrwkhan/opencv-wasseruhr.git
cd opencv-wasseruhr
docker compose up -d --build
curl http://localhost:8099/health        # -> {"ok":true}
```

Lernseite: `http://<host>:8099/`, Verwaltung: `http://<host>:8099/admin`. Für
die automatische Ablesung `KAMERA`, `HA_URL` und `HA_TOKEN` setzen (siehe
[docker-compose.yml](docker-compose.yml)). Alle Daten liegen in `./data` und
bleiben bei Neustarts und Updates erhalten:

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

> **Sicherheit:** Der Dienst hat kein Passwort. Ports nur im Heimnetz
> betreiben, nie im Router freigeben. Webseiten im Browser können ihm nichts
> beibringen (Ursprungsprüfung), Bilder sind auf 10 MB und 25 Megapixel
> begrenzt. Im Add-on sind HTTP und HTTPS im Heimnetz standardmäßig aus.

> **Datenschutz:** Laufende Lernbilder zeigen die eigene Wasseruhr samt
> Zählerständen. `data/` und Modell-Exporte (`*.zip`) sind deshalb per
> `.gitignore` ausgeschlossen. Das mitgelieferte Modell zeigt nur das Zählwerk;
> ein Test stellt sicher, dass das so bleibt.

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
| `KAMERA` | `kamera` | – | Kamera-Entität, die abgelesen wird |
| `INTERVALL_MINUTEN` | `intervall_minuten` | `5` | automatische Ablesung, `0` = aus (braucht `KAMERA` und HA-Zugang) |
| `SENSOR` | `sensor` | `sensor.wasseruhr_cv_zaehlerstand` | Ziel für den Zählerstand, wird angelegt bzw. überschrieben; `-` = kein Sensor |
| `INPUT_NUMBER` | `input_number` | – | optional zusätzlich ein vorhandener Zahlen-Helfer (fehlt er, wird das gemeldet) |
| `MAX_M3_PRO_STUNDE` | `max_m3_pro_stunde` | `3` | schnellerer Anstieg = Lesefehler |
| `TOLERANZ_M3` | `toleranz_m3` | `0.002` | kleine Rückwärts-Abweichung ignorieren |
| `ALLE_ZIFFERN_GELERNT` | `alle_ziffern_gelernt` | `an` | erst schreiben, wenn 0–9 gelernt sind |
| `HTTP` / `HTTP_PORT` | `http` | `aus` / `8080` | zusätzlicher HTTP-Listener (Add-on: Port unter Netzwerk, Standard 8099) |
| `HTTPS` / `HTTPS_PORT` | `https` | `aus` / `8443` | zusätzlicher HTTPS-Listener (Add-on: Port unter Netzwerk, Standard 8100) |
| `ZERTIFIKAT` / `SCHLUESSEL` | `zertifikat` / `schluessel` | `fullchain.pem` / `privkey.pem` | relativ zu `SSL_VERZEICHNIS` (`/ssl`) oder absolut; fehlt es, wird ein selbstsigniertes erzeugt |
| `PORT` | – | `8099` | Hauptport (Add-on: Ingress/intern, Docker: der freigegebene Port) |
| `ADMIN_NUR_INGRESS` | `admin_nur_ueber_ingress` | Docker `aus`, Add-on `an` | Verwaltung nur über die HA-Seitenleiste |
| `LOG_LEVEL` | `log_level` | `INFO` | `DEBUG` zeigt auch übersprungene Duplikate |
| `HA_URL` | – | `http://supervisor/core/api` | REST-API von HA, für Docker z. B. `http://homeassistant.local:8123/api` |
| `HA_TOKEN` | – | im Add-on automatisch | Langlebiges Zugriffstoken (Docker: in `.env`, nie ins Repository) |
| `DATA_DIR` | – | `/data` | Datenverzeichnis mit `lernbilder/` und `vorlagen/` |
| `MODELL_DIR` | – | `/opt/wasseruhr/modell` | Initiales Modell, wird beim ersten Start in ein leeres `DATA_DIR` übernommen |

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
  Eigene Auswertungen sollten das prüfen; die eingebaute Automatik tut es.

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
Programme wie curl senden keinen `Origin` und sind nicht betroffen.

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
  config.yaml            Add-on-Definition: Optionen, Ingress, Ports
  Dockerfile, start.py   Image und Start (Optionen -> Umgebungsvariablen)
  DOCS.md, CHANGELOG.md  im Add-on angezeigte Dokumentation
  app/                   der Dienst (FastAPI + OpenCV)
    erkennung.py         Aufbereitung, Template Matching
    vorlagen.py          Vorlagen speichern, deduplizieren, neu aufbauen
    lernbilder.py        Archiv aller Lernbilder
    modell.py            Modell-Export/-Import (ZIP)
    verwaltung.py        /admin, verwaltungsseite.py ihr HTML
    lernseite.py         Lernseite, debugbild.py /debug.png
    automatik.py         Ablesen im Intervall, Plausibilität, nach HA schreiben
    ha.py, kamera.py     REST-API von Home Assistant (Zustände, Dienste, Kamera)
    schutz.py            Ursprungsprüfung, Größenlimits, Sicherheits-Header
    server.py            Hauptport + optional HTTP/HTTPS in einem Prozess
    main.py              Endpunkte, Logging
  modell/                initiales Modell: lernbilder/ (nur Zählwerk, PNG), vorlagen/
tests/                   pytest; Testbilder bis auf das Zählwerk geschwärzt
docker-compose.yml       eigenständiger Betrieb
```

**Neue Version veröffentlichen:** Version in `wasseruhr_cv/config.yaml`,
`wasseruhr_cv/app/__init__.py` und `pyproject.toml` erhöhen (ein Test prüft,
dass alle gleich sind), Eintrag in `wasseruhr_cv/CHANGELOG.md`, auf `main`
pushen. Home Assistant bietet das Update dann im Add-on an.

## Lizenz

[MIT](LICENSE)
