# Node-RED-Flow für Wasseruhr-CV

Ergebnis: **`input_number.wasserzaehler`** in Home Assistant enthält den
Zählerstand in m³. Der Flow liest alle 5 Minuten ab und schreibt nur, was
**sicher und plausibel** ist.

```
alle 5 min → Zählerstand in HA → Kamera → Bild-URL → GET Kamerabild
           → CV: ablesen vorbereiten → POST /ablesen → CV: prüfen & plausibilisieren
                                                       ├→ input_number.wasserzaehler setzen
                                                       └→ Verworfen (Debug)
```

Voraussetzungen: Node-RED als Home-Assistant-Add-on (oder mit
`node-red-contrib-home-assistant-websocket`) und ein laufendes Wasseruhr-CV.
Getestet mit Node-RED 4.1, node-red-contrib-home-assistant-websocket 0.83 und
Home Assistant 2026.11.

## 1. Helfer `input_number.wasserzaehler` anlegen

Einstellungen → Geräte & Dienste → **Helfer** → Helfer erstellen → **Nummer**,
Name `wasserzaehler`:

| Feld | Wert |
|---|---|
| Minimum | `0` |
| Maximum | `100000`. Wichtig, der Standardwert 100 ist zu klein, dann lehnt HA jeden Wert ab |
| Schrittweite | `0.001`, sonst fehlen die Liter |
| Anzeigemodus | Eingabefeld |
| Maßeinheit | `m³` |

## 2. Flow importieren

1. Node-RED → Menü (☰) → **Importieren** → `wasseruhr-cv-flow.json` → **Importieren**.
   Es erscheint der Tab **„Wasseruhr (CV)“**.
2. Node **Kamera** (Doppelklick): die eigene Kamera-Entität auswählen.
3. Node **CV: ablesen vorbereiten**, oben die Adresse von Wasseruhr-CV:

   ```js
   const CV_URL = "http://1938f1d6-wasseruhr-cv:8099";
   ```

   Das ist der interne Hostname des Add-ons, wenn das Repository als
   `https://github.com/mrwkhan/opencv-wasseruhr` hinzugefügt wurde. Er steht
   auf der Info-Seite des Add-ons unter **Hostname**. Läuft Node-RED nicht
   als Add-on, im Add-on unter Konfiguration → Netzwerk den Port `8099`
   eintragen und `http://<IP-von-Home-Assistant>:8099` nehmen. Für einen
   Docker-Dienst auf einem anderen Rechner: `http://<IP>:8099`.
4. **Übernahme (Deploy).** 20 Sekunden später läuft die erste Ablesung, danach
   alle 5 Minuten. Mit dem Knopf am Node **alle 5 Minuten** löst du sofort eine aus.

Der Flow bringt eine eigene Server-Verbindung **„Home Assistant (Wasseruhr)“**
im Add-on-Modus mit und braucht deshalb kein Token. Wer nur eine Verbindung
möchte, wählt in den drei HA-Nodes die bestehende aus und löscht die
mitgebrachte unter Menü → Konfigurations-Nodes.

Läuft vorher ein anderer Flow, der ebenfalls `input_number.wasserzaehler`
beschreibt, diesen Tab deaktivieren.

## 3. Was du nach dem Deploy siehst

| Status unter „CV: prüfen & plausibilisieren“ | Bedeutung |
|---|---|
| 🟢 Punkt `506.616 m³` | in `input_number.wasserzaehler` geschrieben |
| 🟢 Ring `(unverändert)` | gleicher Wert wie in HA, nichts geschrieben |
| 🟡 Ring `unsicher …` / `nicht übernommen …` | Erkennung unsicher bzw. Vorlagen fehlen → nachlernen |
| 🔴 Ring `unplausibel` / `kleiner als …` / `HTTP …` | passt nicht zum Wert in HA, oder der Dienst meldet einen Fehler |

Solange nicht jede Ziffer 0–9 gelernt ist, schreibt der Flow absichtlich
nichts. Eine nie gelernte Ziffer könnte sonst als ähnliche erkannt werden.

## 4. Einstellungen und Plausibilität

Node **CV: prüfen & plausibilisieren**, oben:

```js
const MAX_M3_PRO_STUNDE = 3;        // schnellerer Anstieg = Lesefehler
const TOLERANZ_M3 = 0.002;          // kleine Rückwärts-Abweichung still ignorieren
const ALLE_ZIFFERN_GELERNT = true;  // erst schreiben, wenn 0–9 alle gelernt sind
```

- Verglichen wird mit dem **aktuellen Wert von `input_number.wasserzaehler`**.
  Der Zähler darf nur steigen, und höchstens so schnell, wie Wasser fließen kann.
- Steht der Helfer auf `0` (frisch angelegt), wird der erste sichere Wert ohne
  Vergleich übernommen.
- **Korrigieren** heißt: `input_number.wasserzaehler` in HA von Hand auf den
  richtigen Stand setzen, z. B. nach einem Zählertausch oder wenn dauerhaft
  „kleiner als der Wert in Home Assistant“ gemeldet wird.

Das Intervall stellst du per Doppelklick auf **alle 5 Minuten** → „Wiederholen“ ein.

## 5. Fehlersuche

| Meldung | Ursache und Lösung |
|---|---|
| **Fehler**: `ENOTFOUND`, `ECONNREFUSED`, `ETIMEDOUT` | Wasseruhr-CV nicht erreichbar: Add-on gestartet? Hostname bzw. IP in `CV_URL` prüfen |
| **Bild-URL**: „kein entity_picture“ | Kamera offline bzw. nicht verfügbar |
| **Fehler**: „Kamerabild nicht geladen (HTTP 401/404)“ | Abruf über `http://homeassistant:8123` klappt nicht. Läuft Node-RED nicht als HA-Add-on, im Node **Bild-URL** die HA-Adresse anpassen |
| **Fehler** aus „input_number.wasserzaehler setzen“: `… range …` | Maximum bzw. Schrittweite des Helfers passen nicht (Schritt 1) |
| HA-Nodes zeigen „Disconnected“ | Server-Verbindung: im Add-on muss „Using the Home Assistant Add-on“ aktiv sein |
| „CV-Dienst antwortet HTTP 400: ROI … außerhalb des Bildes“ | Kameraauflösung geändert → ROIs anpassen |
| Ständig `unsicher` mit niedrigen Scores | Kamera verrutscht oder Licht verändert: ein paar Bilder nachlernen |
