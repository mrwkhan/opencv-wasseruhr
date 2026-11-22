# Changelog

## 2.0.0

**English**

- **English names everywhere, no more mix of languages:** add-on options,
  environment variables, API paths and fields, data folders and the code are
  English; German is a complete translation of all texts. This removes the
  German leftovers of 1.5.0 in the English version (option names in messages
  and docs, links such as `?sprache=`, the values `an`/`aus`).
- **Automatic update from 1.x:** the options (`kamera` → `camera`,
  `lerneffekt` → `learning` …) are taken over and saved, the data folders
  renamed (`lernbilder/` → `images/`, `vorlagen/` → `templates/`), the
  confirmed meter reading kept. Installations keep writing to their sensor
  `sensor.wasseruhr_cv_zaehlerstand`, so the Energy dashboard history
  continues; new installations use `sensor.wasseruhr_cv_meter_reading`.
- **Docker:** the variables are English (`CAMERA`, `LEARNING` …), switches take
  `true`/`false`. The German names and `an`/`aus` keep working.
- **API:** `POST /read`, `/learn?value=`, `/read-camera` with English answers
  (`value`, `certain`, `digits` …). The paths of 1.x (`/ablesen`,
  `/lernen?wert=`, `/kamera-ablesen`) keep working with their old answers. The
  admin API (`/admin/images` …) and `/status` use the new names – please adjust
  own integrations.
- The sidebar title is now **Wasseruhr-CV** (Home Assistant cannot translate
  it). The language switch uses `?lang=en|de`.
- Documentation: switches are described as switches (on/off), no more in-page
  links in the add-on documentation (Home Assistant does not support them).

**Deutsch**

- **Englische Namen überall, kein Sprachmix mehr:** Add-on-Optionen,
  Umgebungsvariablen, API-Pfade und -Felder, Datenordner und der Code sind
  englisch; Deutsch ist eine vollständige Übersetzung aller Texte. Damit sind
  die deutschen Reste von 1.5.0 in der englischen Fassung weg (Optionsnamen in
  Meldungen und Doku, Links wie `?sprache=`, die Werte `an`/`aus`).
- **Automatisches Update von 1.x:** Die Optionen (`kamera` → `camera`,
  `lerneffekt` → `learning` …) werden übernommen und gespeichert, die
  Datenordner umbenannt (`lernbilder/` → `images/`, `vorlagen/` →
  `templates/`), der bestätigte Zählerstand bleibt. Bestehende Installationen
  schreiben weiter in ihren Sensor `sensor.wasseruhr_cv_zaehlerstand`, damit
  der Verlauf im Energie-Dashboard weiterläuft; neue Installationen nutzen
  `sensor.wasseruhr_cv_meter_reading`.
- **Docker:** Die Variablen sind englisch (`CAMERA`, `LEARNING` …), Schalter
  nehmen `true`/`false`. Die deutschen Namen und `an`/`aus` funktionieren
  weiter.
- **API:** `POST /read`, `/learn?value=`, `/read-camera` mit englischen
  Antworten (`value`, `certain`, `digits` …). Die Pfade von 1.x (`/ablesen`,
  `/lernen?wert=`, `/kamera-ablesen`) funktionieren weiter mit ihren alten
  Antworten. Die Verwaltungs-API (`/admin/images` …) und `/status` nutzen die
  neuen Namen – eigene Anbindungen bitte anpassen.
- Der Titel in der Seitenleiste heißt jetzt **Wasseruhr-CV** (Home Assistant
  kann ihn nicht übersetzen). Der Sprachumschalter nutzt `?lang=en|de`.
- Dokumentation: Schalter sind als Schalter beschrieben (an/aus), keine
  Sprunglinks mehr in der Add-on-Dokumentation (Home Assistant unterstützt sie
  nicht).

## 1.5.0

**English**

- **English and German** for everything you see: training page, admin page,
  API error messages, log, sensor and the debug image. The pages follow the
  browser language; a **DE / EN** switch at the top right changes it and is
  remembered. Log and sensor follow the Home Assistant language.
- New option `sprache` (`auto`, `de`, `en`) to set one language for
  everything. Docker: variable `SPRACHE`.
- **Breaking:** the sensor attributes are now language-neutral so that
  automations work in every language: `last_check`, `reason`, `recognized`,
  `source` instead of `letzte_pruefung`, `grund`, `erkannt`, `quelle`, and
  `status` is `accepted`, `unchanged`, `rejected`, `error` or `set` instead of
  `übernommen`, `unverändert`, `verworfen`, `fehler`, `gesetzt`. Please adjust
  automations that use these attributes. The sensor itself and its value stay
  the same.
- English values are accepted as well: `on`/`off` for switches, `off` for "no
  entity", `merge`/`replace` as import mode.
- English README on GitHub (German: `README.de.md`), documentation and
  changelog in both languages.

**Deutsch**

- **Deutsch und Englisch** für alles Sichtbare: Lernseite, Verwaltung,
  Fehlermeldungen der API, Protokoll, Sensor und Debug-Bild. Die Seiten folgen
  der Browsersprache; ein Umschalter **DE / EN** oben rechts wechselt sie und
  merkt sich die Wahl. Protokoll und Sensor folgen der Sprache von Home
  Assistant.
- Neue Option `sprache` (`auto`, `de`, `en`), um eine Sprache für alles
  festzulegen. Docker: Variable `SPRACHE`.
- **Achtung:** Die Attribute des Sensors sind jetzt sprachneutral, damit
  Automationen in jeder Sprache funktionieren: `last_check`, `reason`,
  `recognized`, `source` statt `letzte_pruefung`, `grund`, `erkannt`, `quelle`,
  und `status` ist `accepted`, `unchanged`, `rejected`, `error` oder `set`
  statt `übernommen`, `unverändert`, `verworfen`, `fehler`, `gesetzt`.
  Automationen, die diese Attribute nutzen, bitte anpassen. Der Sensor selbst
  und sein Wert bleiben gleich.
- Englische Werte werden ebenfalls angenommen: `on`/`off` für Schalter, `off`
  für „keine Entität“, `merge`/`replace` als Importmodus.
- Englische README auf GitHub (deutsch: `README.de.md`), Dokumentation und
  Changelog in beiden Sprachen.

## 1.4.3

**English**

- The `input_number` helper is brought to the confirmed meter reading even if
  the value does not change – e.g. if it still contains the value of an
  earlier tool after switching over. Before, it lagged behind until the next
  new value. A correction made by hand in the helper is still accepted.

**Deutsch**

- Der `input_number`-Helfer wird auch dann auf den bestätigten Zählerstand
  gebracht, wenn sich der Wert nicht ändert – z. B. wenn er nach der Umstellung
  noch den Wert eines früheren Werkzeugs enthält. Vorher hinkte er bis zum
  nächsten neuen Wert hinterher. Eine Korrektur von Hand im Helfer wird
  weiterhin übernommen.

## 1.4.2

**English**

- **Select the camera** on the admin page: list of all cameras from Home
  Assistant with preview. "Apply" stores the choice in the add-on
  configuration and restarts the add-on.
- `kamera` and `input_number` always appear in the configuration form, even
  while empty (before, they were hidden among the optional options).
- Without a camera, training page, admin page and log point to the selection.

**Deutsch**

- **Kamera auswählen** in der Verwaltung: Liste aller Kameras aus Home
  Assistant mit Vorschaubild. „Übernehmen“ speichert die Wahl in der
  Add-on-Konfiguration und startet das Add-on neu.
- `kamera` und `input_number` stehen immer im Konfigurationsformular, auch
  solange sie leer sind (vorher unter den ausgeblendeten optionalen Optionen).
- Ohne Kamera verweisen Lernseite, Verwaltung und Protokoll auf die Auswahl.

## 1.4.1

**English**

- If the configured `input_number` helper is missing in Home Assistant, the
  admin page now says so clearly ("… does not exist in Home Assistant").
  Before, it showed "ok" although nothing was written. Home Assistant itself
  does not report this case as an error.
- Docs: the sensor is created if it is missing; an existing sensor with the
  configured name is deliberately overwritten.

**Deutsch**

- Fehlt der eingestellte `input_number`-Helfer in Home Assistant, meldet die
  Verwaltung das jetzt klar („… gibt es in Home Assistant nicht“). Vorher stand
  dort „ok“, obwohl nichts geschrieben wurde. Home Assistant meldet diesen Fall
  selbst nicht als Fehler.
- Doku: Der Sensor wird angelegt, falls er fehlt; ein vorhandener Sensor mit
  dem eingestellten Namen wird bewusst überschrieben.

## 1.4.0

**English**

- **Standalone:** the add-on reads the camera itself at fixed intervals
  (option `intervall_minuten`), checks the value (certain only, forward only,
  at most `max_m3_pro_stunde`) and writes it to the sensor
  `sensor.wasseruhr_cv_zaehlerstand` (m³, Energy dashboard) and optionally to
  an `input_number` helper. The Node-RED flow is no longer needed.
- Admin page: auto-reading status, "Read & send now", set the meter reading by
  hand, reset the model.
- The **initial model** is part of the add-on and is installed on first
  start. The training images show only the counter.
- **Access:** HTTP and HTTPS in the local network can be switched separately
  (options `http`, `https`), ports freely selectable under Configuration →
  Network (default 8099 and 8100). HTTPS uses the certificate from `/ssl` or a
  self-signed one.

**Deutsch**

- **Eigenständig:** Das Add-on liest die Kamera selbst in festen Abständen ab
  (Option `intervall_minuten`), prüft den Wert (nur sicher, nur vorwärts,
  höchstens `max_m3_pro_stunde`) und schreibt ihn in den Sensor
  `sensor.wasseruhr_cv_zaehlerstand` (m³, Energie-Dashboard) und optional in
  einen `input_number`-Helfer. Der Node-RED-Flow entfällt.
- Verwaltung: Automatik-Status, „Jetzt ablesen & übertragen“, Zählerstand von
  Hand setzen, Modell zurücksetzen.
- **Initiales Modell** ist Teil des Add-ons und wird beim ersten Start
  übernommen. Die Lernbilder zeigen nur das Zählwerk.
- **Erreichbarkeit:** HTTP und HTTPS im Heimnetz einzeln schaltbar (Optionen
  `http`, `https`), Ports unter Konfiguration → Netzwerk frei wählbar
  (Standard 8099 bzw. 8100). HTTPS nutzt das Zertifikat aus `/ssl` oder ein
  selbstsigniertes.

## 1.3.1

**English**

Security:

- Websites in the browser can no longer teach the service values or trigger
  actions (origin check against CSRF). Node-RED, curl and the HA ingress are
  not affected.
- Protection against memory exhaustion: images at most 10 MB and 25
  megapixels (a crafted JPEG of a few hundred bytes could take the service
  down), model import at most 300 MB.
- Port 8099 is closed by default in the add-on. Enter it under Configuration
  → Network if needed.
- "Read camera now" no longer follows redirects, so the HA token never goes
  to another destination; only http(s), response at most 10 MB.
- Security headers (nosniff, frame-ancestors, Referrer-Policy).

Fixes:

- Damaged or encrypted ZIPs on import give a message instead of a server
  error.
- Training page and admin page accept meter readings with more than 5
  integer digits (with more than 8 wheels).

**Deutsch**

Sicherheit:

- Webseiten im Browser können dem Dienst keine Werte mehr beibringen oder
  Aktionen auslösen (Ursprungsprüfung gegen CSRF). Node-RED, curl und der
  HA-Ingress sind nicht betroffen.
- Schutz vor Speicher-Erschöpfung: Bilder höchstens 10 MB und 25 Megapixel
  (ein präpariertes JPEG von wenigen hundert Bytes konnte den Dienst beenden),
  Modell-Import höchstens 300 MB.
- Port 8099 ist im Add-on standardmäßig geschlossen. Bei Bedarf unter
  Konfiguration → Netzwerk eintragen.
- „Kamera jetzt ablesen“ folgt keinen Weiterleitungen mehr, damit der
  HA-Token nie an ein anderes Ziel geht; nur http(s), Antwort höchstens 10 MB.
- Sicherheits-Header (nosniff, frame-ancestors, Referrer-Policy).

Fehler:

- Beschädigte oder verschlüsselte ZIPs beim Import ergeben eine Meldung statt
  eines Serverfehlers.
- Lernseite und Verwaltung akzeptieren Zählerstände mit mehr als 5
  Vorkommastellen (bei mehr als 8 Rollen).

## 1.3.0

**English**

- First version as a Home Assistant add-on (aarch64, amd64), installable via
  the repository.
- Training page and new **admin page** in the sidebar (ingress): view
  templates, correct and delete training images, rebuild templates, learn
  your own image, export and import the model as a ZIP.
- **Read camera now**: fetches the image of the configured camera via the Home
  Assistant API.
- Settings as add-on options. The admin page is only reachable for logged-in
  users by default.
- Same image for Docker Compose: without add-on options the environment
  variables apply.

**Deutsch**

- Erste Version als Home-Assistant-Add-on (aarch64, amd64), installierbar über
  das Repository.
- Lernseite und neue **Verwaltung** in der Seitenleiste (Ingress): Vorlagen
  ansehen, Lernbilder korrigieren und löschen, Vorlagen neu aufbauen, eigenes
  Bild lernen, Modell als ZIP exportieren und importieren.
- **Kamera jetzt ablesen**: holt das Bild der eingestellten Kamera über die
  Home-Assistant-API.
- Einstellungen als Add-on-Optionen. Die Verwaltung ist standardmäßig nur für
  angemeldete Benutzer erreichbar.
- Gleiches Image für Docker Compose: ohne Add-on-Optionen gelten die
  Umgebungsvariablen.
