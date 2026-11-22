# Wasseruhr-CV

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
   sehen sein, sonst die Option `rois` setzen (siehe [ROIs](#rois)).
4. **Modell:** Das Add-on bringt ein **initiales Modell** mit (die Lernbilder
   und Vorlagen der Uhr, für die es entwickelt wurde). Es wird beim ersten Start
   übernommen. Gleicht deine Uhr dieser nicht, in der Verwaltung **Modell
   zurücksetzen** und auf der Lernseite neu anlernen (siehe
   [Nachlernen](#nachlernen)) oder ein eigenes Modell als ZIP importieren.
5. **Fertig.** Ab jetzt liest das Add-on alle 5 Minuten ab und schreibt den
   Zählerstand in den Sensor `sensor.wasseruhr_cv_zaehlerstand`.

**Energie-Dashboard:** Einstellungen → Dashboards → Energie → Wasserverbrauch
hinzufügen → `sensor.wasseruhr_cv_zaehlerstand` auswählen. Der Sensor hat die
Einheit m³, die Geräteklasse Wasser und ist fortlaufend steigend.

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
  In den Attributen stehen `status` (übernommen, unverändert, verworfen,
  fehler), `grund`, `erkannt` (der zuletzt abgelesene Wert) und
  `letzte_pruefung`. Nach einem Neustart von Home Assistant ist der Sensor
  spätestens nach dem nächsten Intervall wieder da.
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
| `log_level` | INFO | DEBUG zeigt zusätzlich übersprungene Duplikate |

Beim Speichern der Konfiguration startet das Add-on neu.

### ROIs

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
