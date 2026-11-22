# Wasseruhr-CV

**English** below · **Deutsch:** siehe weiter unten [„Deutsch“](#deutsch)

Reads the roller counter of a water meter with a camera and classic computer
vision (OpenCV template matching, no LLM, no cloud) and writes the checked
meter reading to Home Assistant. The add-on works on its own, it needs no
other tools.

## Setup

1. **Start:** on the Info tab, turn on "Show in sidebar" and "Watchdog" →
   **Start**. **Wasseruhr** appears in the sidebar.
2. **Select the camera:** sidebar → Wasseruhr → **Admin** → card Auto-reading
   → pick the camera from the list. The preview shows whether it is the right
   one → **Apply**. The add-on stores the choice in its configuration and
   restarts. Alternatively enter the entity ID under `kamera` on the
   Configuration tab, e.g. `camera.water_meter`.
3. **Check the image:** sidebar → Wasseruhr → **Read camera now**. The wheels
   are drawn into the image as rectangles, below them the digits as the add-on
   sees them. Every digit must be fully visible and centred, otherwise set the
   option `rois` (see [ROIs](#rois)).
4. **Model:** the add-on ships an **initial model** (the training images and
   templates of the meter it was developed for). It is installed on first
   start. If your meter looks different, use **Reset model** on the admin
   page and teach it again on the training page (see [Training](#training)),
   or import your own model as a ZIP.
5. **Done.** From now on the add-on reads every 5 minutes and writes the
   meter reading to the sensor `sensor.wasseruhr_cv_zaehlerstand`.

**Energy dashboard:** Settings → Dashboards → Energy → add water consumption
→ select `sensor.wasseruhr_cv_zaehlerstand`. The sensor has the unit m³, the
device class water and is total increasing.

## Language

The training page, the admin page and all messages exist in **English and
German**. The pages follow your browser language; the **DE / EN** switch at
the top right of every page changes it and is remembered. The log and the
sensor (name and reason) follow the language of Home Assistant. The option
`sprache` sets one language for everything: `auto` (default), `de` or `en`.

## Automatic reading

Every `intervall_minuten` the add-on fetches the camera image, reads it and
checks the value. Only what is **certain and plausible** is written:

| Check | Result if it fails |
|---|---|
| Every wheel recognised unambiguously (`min_score`, `min_abstand`) | rejected: "uncertain …" with the affected wheels |
| There is a template for every digit 0–9 (`alle_ziffern_gelernt`) | rejected: "no templates yet for digit …" |
| The meter only counts forward | rejected: "lower than the previous reading" (deviations up to `toleranz_m3` are silently ignored) |
| At most `max_m3_pro_stunde` since the last confirmation | rejected: "… is implausible" |

The first certain value is accepted without comparison. After that it is
compared with the last confirmed reading, which survives restarts and
updates.

**Where it is written:**

- **Sensor** (option `sensor`, default `sensor.wasseruhr_cv_zaehlerstand`):
  the meter reading in m³. The sensor does not need to exist beforehand, the
  add-on creates it. If you enter the name of an **existing** sensor, its
  value is overwritten, e.g. to continue an existing sensor. Attributes:
  `status` (`accepted`, `unchanged`, `rejected`, `error`, `set`), `reason`
  (text in the Home Assistant language), `recognized` (the last value read)
  and `last_check`. After a Home Assistant restart the sensor is back at the
  latest after the next interval.
- **Helper** (option `input_number`, optional): a number helper, e.g.
  `input_number.water_meter`, is set with every new reading. The helper
  **must already exist** (Settings → Devices & services → Helpers → Number;
  maximum at least 100000, step 0.001). If it is missing, the admin page
  reports "… does not exist in Home Assistant".

**Correcting**, e.g. after replacing the meter or if "lower than the previous
reading" is reported permanently: admin page → Auto-reading → **Set the meter
reading by hand**. If a helper is configured, a value set there by hand also
counts as a correction.

**Read & send now** on the admin page runs a check immediately and shows the
result. The Log tab shows the history as well.

## Access: sidebar, HTTP and HTTPS

| Way | Turn on | Port | Encrypted | Login |
|---|---|---|---|---|
| **Sidebar** (also in the HA app) | always on | – | like Home Assistant | Home Assistant user |
| **HTTP in the local network** | option `http` | `8080/tcp`, default **8099** | no | none |
| **HTTPS in the local network** | option `https` | `8443/tcp`, default **8100** | yes | none |

HTTP and HTTPS can be turned on separately or together. Both are off by
default. The sidebar is all you need for daily use.

**Changing a port:** Configuration tab → section **Network** → enter any free
port number at the desired entry → Save. An empty field closes the port
completely. The option decides whether anything answers there; the network
field decides on which number.

Example: `http` on and under Network `8080/tcp` = `8099` gives
`http://<IP-of-Home-Assistant>:8099/`.

**HTTPS certificate:** the add-on reads certificate and key from the `/ssl`
folder of Home Assistant, by default `fullchain.pem` and `privkey.pem`. This
is where e.g. the Let's Encrypt and DuckDNS add-ons put them. Other file names
are set with the options `zertifikat` and `schluessel`. If the files are
missing, the add-on creates a **self-signed certificate** once. The
connection is then encrypted, but the browser warns on the first visit.

**Security:** HTTP and HTTPS in the local network have **no password**, HTTPS
only encrypts. So never set up a port forwarding in your router. For access on
the go there is the sidebar in the Home Assistant app. Deleting, import and
export are only possible through the sidebar by default
(`admin_nur_ueber_ingress`). Websites you visit in the browser cannot teach
the add-on anything (origin check). Images are limited to 10 MB and 25
megapixels, model imports to 300 MB.

## Training

**Sidebar → Wasseruhr → Training** shows the latest reading with the wheels
drawn in (green = certain, red = uncertain). If it is wrong or uncertain:
enter the correct meter reading → **Learn from this image**. **Read camera
now** fetches a fresh image right away.

Teaching from scratch: repeat until the training page shows "all digits 0–9
learned". The quickest way is via the rear wheels, which turn all the time.
Learn images in different light. If the last wheel sits between two digits,
enter the one that fills more of the window.

## Admin page

**Sidebar → Wasseruhr → Admin**:

- **Auto-reading**: status, current meter reading, last check, set the meter
  reading by hand, "Read & send now".
- **Templates**: all learned digits, row by row. If a tile does not fit its
  row, it comes from a wrongly learned image. Tapping it jumps to the
  training image.
- **Training images**: every image with a crop of the counter. **Correct the
  value** or **delete** it. With learning on, the templates are rebuilt right
  away.
- **Learn your own image**: upload a JPEG or PNG with a known meter reading.
- **Export / import model** (ZIP, *merge* or *replace*) and **Reset model**
  (delete all training images and templates to teach a different meter).

## Options

| Option | Default | Meaning |
|---|---|---|
| `kamera` | – | camera entity that is read (easier: select it on the admin page) |
| `intervall_minuten` | 5 | interval of automatic reading, 0 = off |
| `sensor` | `sensor.wasseruhr_cv_zaehlerstand` | target for the meter reading, created or overwritten; empty = no sensor |
| `input_number` | – | optionally also an existing number helper |
| `max_m3_pro_stunde` | 3 | faster increase = reading error |
| `toleranz_m3` | 0.002 | ignore small backward deviations |
| `alle_ziffern_gelernt` | on | only write once 0–9 are all learned |
| `http` | off | HTTP in the local network, port under Network (`8080/tcp`) |
| `https` | off | HTTPS in the local network, port under Network (`8443/tcp`) |
| `zertifikat` | `fullchain.pem` | certificate in `/ssl` for HTTPS |
| `schluessel` | `privkey.pem` | key in `/ssl` for HTTPS |
| `lerneffekt` | on | on: what is learned becomes a template right away. off: templates frozen |
| `min_score` | 0.70 | minimum score of the best digit for "certain" |
| `min_abstand` | 0.08 | minimum margin to the second-best digit |
| `max_vorlagen_pro_ziffer` | 30 | older templates are dropped, training images stay |
| `verschiebung` | 3 | search range of the template matching in px (±) |
| `rois` | default | position of the wheels in the image, see below |
| `admin_nur_ueber_ingress` | on | delete, import, export only through the sidebar |
| `sprache` | auto | language: `auto`, `de` or `en` (see [Language](#language)) |
| `log_level` | INFO | DEBUG additionally shows skipped duplicates |

Saving the configuration restarts the add-on.

### ROIs

Each wheel is a rectangle `[x1, y1, x2, y2]` in pixels of the camera image,
from left (highest digit) to right. The **last 3 wheels are the decimals**
(litres). Without a value, defaults for a 640×480 image with 8 wheels apply:

```
[[130,144,162,196],[173,144,205,196],[216,144,248,196],[260,144,292,196],[304,144,336,196],[347,144,379,196],[391,144,423,196],[435,144,467,196]]
```

Read the coordinates for your own camera in an image editor. The rectangle
may be slightly larger than the digit, 3 px are cut off on the left and
right. With learning on, the templates are regenerated from the training
images with the new ROIs on restart.

## Data, backups and updates

- Everything learned and the confirmed meter reading live in the add-on's
  data directory and are part of every **Home Assistant backup**.
- **Updates** appear under Settings → Updates like for any add-on. What was
  learned is kept, the initial model is never installed again.
- **Careful when uninstalling:** this deletes the data directory. Export on
  the admin page first.
- Exports contain the full camera images of your meter, so do not share them
  publicly.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| Add-on does not start, log: "Invalid configuration: …" | Correct the option, e.g. `rois` (valid JSON) or ports used twice |
| Add-on does not start: port already in use | Enter a different port number under Network or clear the field |
| Auto-reading: "error – … HTTP 404 (unknown entity)" | Camera entity misspelled: select it again on the admin page |
| Add-on does not start: "KAMERA='…': expected an entity like camera.water_meter" | Enter the entity ID under `kamera`, not the display name – or clear the field and select it on the admin page |
| Camera selection: "Could not save the configuration …" | Enter the displayed entity ID under `kamera` on the Configuration tab |
| Auto-reading: "error – … HTTP 500 (camera returns no image)" | Camera currently offline |
| Auto-reading: "rejected – uncertain …" | Check the image on the training page and train it |
| Auto-reading: permanently "lower than the previous reading" | Set the meter reading by hand on the admin page |
| Admin page shows "input_number… does not exist in Home Assistant" | Create the helper (Settings → Devices & services → Helpers → Number) or clear the option `input_number` |
| Admin page shows "Sending failed: input_number…" | Maximum or step of the helper do not fit (maximum ≥ 100000, step 0.001) |
| `http://<ha>:8099/` not reachable | Turn on the option `http` and check the port under Network |
| HTTPS: browser warns about the certificate | Self-signed certificate. Put your own in `/ssl` (options `zertifikat`, `schluessel`) |
| "ROI of wheel … is outside the image" | The camera delivers a different resolution: adjust `rois` |
| Request answers 403 "Request from a foreign website rejected" | A website sent something to the add-on in your browser. Open the training page directly via its own address |
| `/admin` answers 403 in the local network | Intended: use the admin page through the sidebar (option `admin_nur_ueber_ingress`) |
| Pages in the wrong language | Use the DE / EN switch at the top right, or set the option `sprache` |

---

# Deutsch

Liest das Rollenzählwerk einer Wasseruhr per Kamera und klassischem Computer
Vision ab (OpenCV Template Matching, kein LLM, keine Cloud) und schreibt den
geprüften Zählerstand nach Home Assistant. Das Add-on arbeitet eigenständig, es
braucht keine weiteren Werkzeuge.

## Einrichtung

1. **Starten:** Im Reiter Info „In der Seitenleiste anzeigen“ und „Watchdog“
   einschalten → **Starten**. In der Seitenleiste erscheint **Wasseruhr**.
2. **Kamera auswählen:** Seitenleiste → Wasseruhr → **Verwaltung** → Karte
   Automatik → Kamera aus der Liste wählen. Das Vorschaubild zeigt, ob es die
   richtige ist → **Übernehmen**. Das Add-on speichert die Wahl in seiner
   Konfiguration und startet neu. Alternativ im Reiter Konfiguration die
   Entitäts-ID bei `kamera` eintragen, z. B. `camera.wasseruhr`.
3. **Bild prüfen:** Seitenleiste → Wasseruhr → **Kamera jetzt ablesen**. Im
   Bild sind die Rollen als Rechtecke eingezeichnet, darunter stehen die Ziffern
   so, wie das Add-on sie sieht. Jede Ziffer muss vollständig und mittig zu
   sehen sein, sonst die Option `rois` setzen (siehe ROIs unten).
4. **Modell:** Das Add-on bringt ein **initiales Modell** mit (die Lernbilder
   und Vorlagen der Uhr, für die es entwickelt wurde). Es wird beim ersten Start
   übernommen. Gleicht deine Uhr dieser nicht, in der Verwaltung **Modell
   zurücksetzen** und auf der Lernseite neu anlernen (siehe Nachlernen unten)
   oder ein eigenes Modell als ZIP importieren.
5. **Fertig.** Ab jetzt liest das Add-on alle 5 Minuten ab und schreibt den
   Zählerstand in den Sensor `sensor.wasseruhr_cv_zaehlerstand`.

**Energie-Dashboard:** Einstellungen → Dashboards → Energie → Wasserverbrauch
hinzufügen → `sensor.wasseruhr_cv_zaehlerstand` auswählen. Der Sensor hat die
Einheit m³, die Geräteklasse Wasser und ist fortlaufend steigend.

## Sprache

Lernseite, Verwaltung und alle Meldungen gibt es auf **Deutsch und Englisch**.
Die Seiten folgen der Sprache des Browsers; der Umschalter **DE / EN** oben
rechts auf jeder Seite wechselt sie und merkt sich die Wahl. Protokoll und
Sensor (Name und Begründung) folgen der Sprache von Home Assistant. Die Option
`sprache` legt eine Sprache für alles fest: `auto` (Standard), `de` oder `en`.

## Automatische Ablesung

Alle `intervall_minuten` holt das Add-on das Bild der Kamera, liest es ab und
prüft den Wert. Geschrieben wird nur, was **sicher und plausibel** ist:

| Prüfung | Ergebnis, wenn sie nicht passt |
|---|---|
| Jede Rolle eindeutig erkannt (`min_score`, `min_abstand`) | verworfen: „unsicher …“ mit den betroffenen Rollen |
| Für jede Ziffer 0–9 gibt es eine Vorlage (`alle_ziffern_gelernt`) | verworfen: „noch keine Vorlagen für Ziffer …“ |
| Der Zähler läuft nur vorwärts | verworfen: „kleiner als der bisherige Stand“ (Abweichungen bis `toleranz_m3` werden still ignoriert) |
| Höchstens `max_m3_pro_stunde` seit der letzten Bestätigung | verworfen: „… ist unplausibel“ |

Der erste sichere Wert wird ohne Vergleich übernommen. Danach wird mit dem
zuletzt bestätigten Stand verglichen. Er bleibt bei Neustarts und Updates
erhalten.

**Wohin geschrieben wird:**

- **Sensor** (Option `sensor`, Standard `sensor.wasseruhr_cv_zaehlerstand`):
  der Zählerstand in m³. Den Sensor muss es vorher nicht geben, das Add-on
  legt ihn an. Trägst du den Namen eines **vorhandenen** Sensors ein, wird
  dessen Wert überschrieben, z. B. um einen bisherigen Sensor weiterzuführen.
  Attribute: `status` (`accepted` = übernommen, `unchanged` = unverändert,
  `rejected` = verworfen, `error` = Fehler, `set` = von Hand gesetzt),
  `reason` (Begründung in der Sprache von Home Assistant), `recognized` (der
  zuletzt abgelesene Wert) und `last_check`. Die Namen sind sprachneutral,
  damit Automationen in jeder Sprache funktionieren. Nach einem Neustart von
  Home Assistant ist der Sensor spätestens nach dem nächsten Intervall wieder
  da.
- **Helfer** (Option `input_number`, optional): Ein Zahlen-Helfer, z. B.
  `input_number.wasserzaehler`, wird bei jedem neuen Stand mitgesetzt. Den
  Helfer **muss es schon geben** (Einstellungen → Geräte & Dienste → Helfer →
  Nummer; Maximum mindestens 100000, Schrittweite 0.001). Fehlt er, meldet die
  Verwaltung „… gibt es in Home Assistant nicht“.

**Korrigieren**, z. B. nach einem Zählertausch oder wenn dauerhaft „kleiner als
der bisherige Stand“ gemeldet wird: Verwaltung → Automatik → **Zählerstand von
Hand setzen**. Ist ein Helfer eingestellt, wirkt auch ein dort von Hand
gesetzter Wert als Korrektur.

**Jetzt ablesen & übertragen** in der Verwaltung führt sofort einen Durchlauf
aus und zeigt das Ergebnis. Den Verlauf zeigt auch der Reiter Protokoll.

## Erreichbarkeit: Seitenleiste, HTTP und HTTPS

| Weg | Einschalten | Port | Verschlüsselt | Anmeldung |
|---|---|---|---|---|
| **Seitenleiste** (auch in der HA-App) | immer an | – | wie Home Assistant | Home-Assistant-Benutzer |
| **HTTP im Heimnetz** | Option `http` | `8080/tcp`, Standard **8099** | nein | keine |
| **HTTPS im Heimnetz** | Option `https` | `8443/tcp`, Standard **8100** | ja | keine |

HTTP und HTTPS lassen sich einzeln oder zusammen einschalten. Beide sind
standardmäßig aus. Für die Bedienung genügt die Seitenleiste.

**Port ändern:** Reiter Konfiguration → Abschnitt **Netzwerk** → beim
gewünschten Eintrag eine beliebige freie Port-Nummer eintragen → Speichern. Ein
leeres Feld schließt den Port ganz. Die Option schaltet, ob dort etwas antwortet;
das Netzwerk-Feld legt fest, unter welcher Nummer.

Beispiel: `http` an und unter Netzwerk `8080/tcp` = `8099` ergibt
`http://<IP-von-Home-Assistant>:8099/`.

**HTTPS-Zertifikat:** Das Add-on liest Zertifikat und Schlüssel aus dem Ordner
`/ssl` von Home Assistant, standardmäßig `fullchain.pem` und `privkey.pem`. So
legen sie z. B. die Add-ons Let's Encrypt und DuckDNS ab. Andere Dateinamen
stellst du mit den Optionen `zertifikat` und `schluessel` ein. Fehlen die
Dateien, erzeugt das Add-on einmalig ein **selbstsigniertes Zertifikat**. Die
Verbindung ist damit verschlüsselt, der Browser warnt aber beim ersten Aufruf.

**Sicherheit:** HTTP und HTTPS im Heimnetz haben **kein Passwort**, HTTPS
verschlüsselt nur. Deshalb nie eine Portfreigabe im Router einrichten. Für den
Zugriff von unterwegs gibt es die Seitenleiste in der Home-Assistant-App.
Löschen, Import und Export sind standardmäßig nur über die Seitenleiste möglich
(`admin_nur_ueber_ingress`). Webseiten, die du im Browser besuchst, können dem
Add-on nichts beibringen (Ursprungsprüfung). Bilder sind auf 10 MB und
25 Megapixel begrenzt, Modell-Importe auf 300 MB.

## Nachlernen

**Seitenleiste → Wasseruhr → Nachlernen** zeigt die letzte Ablesung mit
eingezeichneten Rollen (grün = sicher, rot = unsicher). Ist sie falsch oder
unsicher: richtigen Zählerstand eintragen → **Mit diesem Bild lernen**.
**Kamera jetzt ablesen** holt sofort ein frisches Bild.

Neu anlernen: wiederholen, bis die Lernseite „alle Ziffern 0–9 gelernt“ zeigt.
Am schnellsten geht das über die hinteren Rollen, die sich ständig drehen.
Bilder bei verschiedenem Licht lernen. Steht die letzte Rolle zwischen zwei
Ziffern, die eintragen, die mehr vom Fenster einnimmt.

## Verwaltung

**Seitenleiste → Wasseruhr → Verwaltung**:

- **Automatik**: Status, aktueller Zählerstand, letzte Prüfung, Zählerstand
  von Hand setzen, „Jetzt ablesen & übertragen“.
- **Vorlagen**: alle gelernten Ziffern, Zeile für Zeile. Passt eine Kachel
  nicht in ihre Zeile, stammt sie aus einem falsch gelernten Bild. Antippen
  springt zum zugehörigen Lernbild.
- **Lernbilder**: jedes Bild mit Ausschnitt des Zählwerks. **Wert korrigieren**
  oder **löschen**. Mit Lerneffekt werden die Vorlagen sofort neu aufgebaut.
- **Eigenes Bild lernen**: ein JPEG oder PNG mit bekanntem Zählerstand hochladen.
- **Modell exportieren / importieren** (ZIP, *ergänzen* oder *ersetzen*) und
  **Modell zurücksetzen** (alle Lernbilder und Vorlagen löschen, um für eine
  andere Uhr neu anzulernen).

## Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `kamera` | – | Kamera-Entität, die abgelesen wird (bequemer: Auswahl in der Verwaltung) |
| `intervall_minuten` | 5 | Abstand der automatischen Ablesung, 0 = aus |
| `sensor` | `sensor.wasseruhr_cv_zaehlerstand` | Ziel für den Zählerstand, wird angelegt bzw. überschrieben; leer = kein Sensor |
| `input_number` | – | optional zusätzlich ein vorhandener Zahlen-Helfer |
| `max_m3_pro_stunde` | 3 | schnellerer Anstieg = Lesefehler |
| `toleranz_m3` | 0.002 | kleine Rückwärts-Abweichung ignorieren |
| `alle_ziffern_gelernt` | an | erst schreiben, wenn 0–9 alle gelernt sind |
| `http` | aus | HTTP im Heimnetz, Port unter Netzwerk (`8080/tcp`) |
| `https` | aus | HTTPS im Heimnetz, Port unter Netzwerk (`8443/tcp`) |
| `zertifikat` | `fullchain.pem` | Zertifikat in `/ssl` für HTTPS |
| `schluessel` | `privkey.pem` | Schlüssel in `/ssl` für HTTPS |
| `lerneffekt` | an | an: Gelerntes wird sofort zur Vorlage. aus: Vorlagen eingefroren |
| `min_score` | 0.70 | Mindest-Score der besten Ziffer für „sicher“ |
| `min_abstand` | 0.08 | Mindestabstand zur zweitbesten Ziffer |
| `max_vorlagen_pro_ziffer` | 30 | ältere Vorlagen fallen heraus, Lernbilder bleiben |
| `verschiebung` | 3 | Suchbereich des Template Matchings in px (±) |
| `rois` | Standard | Lage der Rollen im Bild, siehe unten |
| `admin_nur_ueber_ingress` | an | Löschen, Import, Export nur über die Seitenleiste |
| `sprache` | auto | Sprache: `auto`, `de` oder `en` (siehe Sprache oben) |
| `log_level` | INFO | DEBUG zeigt zusätzlich übersprungene Duplikate |

Beim Speichern der Konfiguration startet das Add-on neu.

### ROIs (Deutsch)

Jede Rolle ist ein Rechteck `[x1, y1, x2, y2]` in Pixeln des Kamerabildes,
von links (höchste Stelle) nach rechts. Die **letzten 3 Rollen sind die
Nachkommastellen** (Liter). Ohne Angabe gelten Standardwerte für ein
640×480-Bild mit 8 Rollen:

```
[[130,144,162,196],[173,144,205,196],[216,144,248,196],[260,144,292,196],[304,144,336,196],[347,144,379,196],[391,144,423,196],[435,144,467,196]]
```

Die Koordinaten für die eigene Kamera liest du in einem Bildprogramm ab. Das
Rechteck darf etwas größer als die Ziffer sein, links und rechts werden je
3 px abgeschnitten. Mit Lerneffekt werden die Vorlagen beim Neustart aus den
Lernbildern mit den neuen ROIs neu erzeugt.

## Daten, Sicherung und Updates

- Alles Gelernte und der bestätigte Zählerstand liegen im Datenverzeichnis des
  Add-ons und sind in jeder **Home-Assistant-Datensicherung** enthalten.
- **Updates** erscheinen wie bei jedem Add-on unter Einstellungen → Updates.
  Gelerntes bleibt erhalten, das initiale Modell wird nie erneut eingespielt.
- **Achtung beim Deinstallieren:** Das löscht das Datenverzeichnis. Vorher in
  der Verwaltung exportieren.
- Exporte enthalten die vollständigen Kamerabilder deiner Uhr, deshalb nicht
  öffentlich teilen.

## Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| Add-on startet nicht, Protokoll: „Konfiguration ungültig: …“ | Option korrigieren, z. B. `rois` (gültiges JSON) oder doppelt vergebene Ports |
| Add-on startet nicht: Port schon belegt | Unter Netzwerk eine andere Port-Nummer eintragen oder das Feld leeren |
| Automatik: „fehler – … HTTP 404 (Entität unbekannt)“ | Kamera-Entität falsch geschrieben: in der Verwaltung neu auswählen |
| Add-on startet nicht: „KAMERA='…': erwartet eine Entität wie camera.wasseruhr“ | Bei `kamera` die Entitäts-ID eintragen, nicht den Anzeigenamen – oder das Feld leeren und in der Verwaltung auswählen |
| Kamera-Auswahl: „Konnte die Konfiguration nicht speichern …“ | Die angezeigte Entitäts-ID im Reiter Konfiguration bei `kamera` eintragen |
| Automatik: „fehler – … HTTP 500 (Kamera liefert kein Bild)“ | Kamera gerade offline |
| Automatik: „verworfen – unsicher …“ | Bild auf der Lernseite prüfen und nachlernen |
| Automatik: dauerhaft „kleiner als der bisherige Stand“ | Zählerstand in der Verwaltung von Hand setzen |
| Verwaltung zeigt „input_number… gibt es in Home Assistant nicht“ | Helfer anlegen (Einstellungen → Geräte & Dienste → Helfer → Nummer) oder Option `input_number` leeren |
| Verwaltung zeigt „Übertragen fehlgeschlagen: input_number…“ | Maximum bzw. Schrittweite des Helfers passen nicht (Maximum ≥ 100000, Schritt 0.001) |
| `http://<ha>:8099/` nicht erreichbar | Option `http` einschalten und unter Netzwerk den Port prüfen |
| HTTPS: Browser warnt vor dem Zertifikat | Selbstsigniertes Zertifikat. Eigenes in `/ssl` ablegen (Optionen `zertifikat`, `schluessel`) |
| „ROI der Rolle … liegt außerhalb des Bildes“ | Kamera liefert eine andere Auflösung: `rois` anpassen |
| Anfrage antwortet 403 „von fremder Webseite abgelehnt“ | Eine Webseite hat im Browser an das Add-on geschickt. Die Lernseite direkt über ihre eigene Adresse öffnen |
| `/admin` antwortet im Heimnetz 403 | So gewollt: Verwaltung über die Seitenleiste (Option `admin_nur_ueber_ingress`) |
| Seiten in der falschen Sprache | Umschalter DE / EN oben rechts nutzen oder die Option `sprache` setzen |
| Automationen prüften `status: übernommen` oder `grund` (vor 1.5.0) | Seit 1.5.0 sprachneutral: `status: accepted`, Attribut `reason` statt `grund` (siehe CHANGELOG) |
