# Wasseruhr-CV

Liest das Rollenzählwerk einer Wasseruhr per klassischem Computer Vision ab
(OpenCV Template Matching, kein LLM, keine Cloud). Das Add-on lernt die Ziffern
aus Kamerabildern mit bekanntem Zählerstand und erkennt sie danach selbst.

## Einrichtung

1. **Starten:** Im Reiter Info „In der Seitenleiste anzeigen“ und „Watchdog“
   einschalten → **Starten**. In der Seitenleiste erscheint **Wasseruhr**.
2. **Kamera eintragen:** Reiter Konfiguration → Option `kamera`, z. B.
   `camera.wasseruhr` → Speichern (das Add-on startet neu).
3. **ROIs prüfen:** Seitenleiste → Wasseruhr → **Kamera jetzt ablesen**. Im
   Bild sind die Rollen als Rechtecke eingezeichnet, darunter stehen die Ziffern
   so, wie der Matcher sie sieht. Jede Ziffer muss vollständig und mittig zu
   sehen sein. Sonst die Option `rois` setzen, siehe [ROIs](#rois).
4. **Modell bereitstellen**, einer von zwei Wegen:
   - **Vorhandenes Modell importieren** (z. B. aus einem bisherigen
     Docker-Dienst): Verwaltung → Sichern & übertragen → ZIP auswählen →
     *ersetzen* → Importieren. Passend ist ein Export aus der Verwaltung oder
     ein ZIP mit den Ordnern `lernbilder/` und `vorlagen/` (z. B. der
     `data`-Ordner).
   - **Neu anlernen:** Lernseite → richtigen Zählerstand eintragen → **Mit
     diesem Bild lernen**. Wiederholen, bis die Lernseite „alle Ziffern 0–9
     gelernt“ zeigt. Am schnellsten geht das über die hinteren Rollen, die sich
     ständig drehen. Bilder bei verschiedenem Licht lernen.
5. **Anbinden**, z. B. mit dem Node-RED-Flow aus dem Repository (siehe unten).

## Node-RED

Den Flow `node-red/wasseruhr-cv-flow.json` aus dem
[Repository](https://github.com/mrwkhan/opencv-wasseruhr/tree/main/node-red)
importieren. Er liest alle 5 Minuten ab und schreibt nur **sichere und
plausible** Werte nach `input_number.wasserzaehler`. Die Anleitung liegt
daneben.

Die Adresse des Add-ons trägst du im Node **CV: ablesen vorbereiten** ein:

```js
const CV_URL = "http://1938f1d6-wasseruhr-cv:8099";
```

`1938f1d6-wasseruhr-cv` ist der interne Hostname, wenn das Repository als
`https://github.com/mrwkhan/opencv-wasseruhr` hinzugefügt wurde. Er steht auch
auf der Info-Seite des Add-ons unter **Hostname**. Ein Node-RED-Add-on erreicht
ihn direkt. Läuft Node-RED woanders, nimm `http://<IP-von-Home-Assistant>:8099`.

## Nachlernen

**Seitenleiste → Wasseruhr → Nachlernen** zeigt die letzte Ablesung mit
eingezeichneten Rollen (grün = sicher, rot = unsicher). Ist sie falsch oder
unsicher: richtigen Zählerstand eintragen → **Mit diesem Bild lernen**.
**Kamera jetzt ablesen** holt sofort ein frisches Bild, ohne auf den nächsten
Node-RED-Durchlauf zu warten.

Im Heimnetz ist die Lernseite auch unter `http://<IP-von-Home-Assistant>:8099/`
erreichbar, z. B. am Handy, dort aber ohne Verwaltung.

## Verwaltung

**Seitenleiste → Wasseruhr → Verwaltung**:

- **Vorlagen**: alle gelernten Ziffern, Zeile für Zeile. Passt eine Kachel
  nicht in ihre Zeile (z. B. eine 3 bei den 8en), stammt sie aus einem falsch
  gelernten Bild. Kachel antippen springt zum zugehörigen Lernbild.
- **Lernbilder**: jedes gelernte Bild mit Ausschnitt des Zählwerks. **Wert
  korrigieren** oder **löschen** (zweimal tippen). Mit Lerneffekt werden die
  Vorlagen sofort neu aufgebaut.
- **Vorlagen neu aufbauen**: alle Vorlagen aus den Lernbildern neu erzeugen,
  z. B. nach einer Änderung der ROIs.
- **Eigenes Bild lernen**: ein JPEG mit bekanntem Zählerstand hochladen.
- **Letzte Ablesungen**: die letzten 20 seit dem Start.
- **Modell exportieren / importieren** (ZIP):
  - *ergänzen*: übernimmt nur Lernbilder mit unbekanntem Zeitstempel,
    korrigierte Werte bleiben erhalten.
  - *ersetzen*: löscht alles Vorhandene und übernimmt das ZIP.

## Optionen

| Option | Standard | Bedeutung |
|---|---|---|
| `kamera` | – | Kamera-Entität für „Kamera jetzt ablesen“ |
| `lerneffekt` | an | an: Gelerntes wird sofort zur Vorlage, beim Start werden alle Vorlagen aus den Lernbildern neu aufgebaut. aus: Vorlagen eingefroren, Lernbilder werden nur gesammelt |
| `min_score` | 0.70 | Mindest-Score der besten Ziffer für „sicher“ |
| `min_abstand` | 0.08 | Mindestabstand zur zweitbesten Ziffer |
| `max_vorlagen_pro_ziffer` | 30 | ältere Vorlagen fallen heraus, Lernbilder bleiben |
| `verschiebung` | 3 | Suchbereich des Template Matchings in px (±) |
| `rois` | Standard | Lage der Rollen im Bild, siehe unten |
| `admin_nur_ueber_ingress` | an | Verwaltung nur über die Seitenleiste (angemeldete Benutzer) |
| `log_level` | INFO | DEBUG zeigt zusätzlich übersprungene Duplikate |

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
Lernbildern mit den neuen ROIs neu erzeugt, du musst nichts neu anlernen.

## Daten, Sicherung und Updates

- Alles Gelernte liegt im Datenverzeichnis des Add-ons und ist in jeder
  **Home-Assistant-Datensicherung** enthalten, die das Add-on einschließt.
- **Updates** erscheinen wie bei jedem Add-on unter Einstellungen → Updates.
  Gelerntes bleibt dabei erhalten.
- **Achtung beim Deinstallieren:** Das löscht das Datenverzeichnis. Vorher in
  der Verwaltung exportieren.
- Lernbilder zeigen die eigene Wasseruhr samt Zählerständen. Exporte deshalb
  nicht öffentlich teilen.

## Sicherheit

- Port 8099 (API und Lernseite) ist im Heimnetz **ohne Passwort** erreichbar.
  Keine Portfreigabe im Router einrichten. Wer ihn nicht braucht, leert unter
  Konfiguration → Netzwerk das Feld für 8099. Ein Node-RED-Add-on arbeitet über
  den internen Hostnamen trotzdem weiter.
- Löschen, Import und Export gehen standardmäßig nur über die Seitenleiste,
  also nur für in Home Assistant angemeldete Benutzer.

## Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| Add-on startet nicht, Protokoll: „Konfiguration ungültig: …“ | Option korrigieren, meist `rois` (gültiges JSON, mindestens 4 Rollen) |
| „ROI der Rolle … liegt außerhalb des Bildes“ | Kamera liefert eine andere Auflösung: `rois` anpassen |
| Node-RED: `ENOTFOUND …-wasseruhr-cv` / `ECONNREFUSED` | Add-on läuft nicht, oder der Hostname weicht ab (Info-Seite) |
| „Kamera jetzt ablesen“: HTTP 404 | Kamera-Entität falsch geschrieben (Option `kamera`) |
| „Kamera jetzt ablesen“: HTTP 500 | Kamera liefert gerade kein Bild (offline?) |
| `http://<ha>:8099/admin` antwortet 403 | So gewollt, die Verwaltung ist über die Seitenleiste erreichbar (Option `admin_nur_ueber_ingress`) |
| Ständig `unsicher` mit niedrigen Scores | Kamera verrutscht oder Licht verändert: Vorlagen prüfen, ein paar Bilder nachlernen |
