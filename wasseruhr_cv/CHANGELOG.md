# Changelog

## 1.4.3

- Der `input_number`-Helfer wird auch dann auf den bestätigten Zählerstand
  gebracht, wenn sich der Wert nicht ändert – z. B. wenn er nach der Umstellung
  noch den Wert eines früheren Werkzeugs enthält. Vorher hinkte er bis zum
  nächsten neuen Wert hinterher. Eine Korrektur von Hand im Helfer wird
  weiterhin übernommen.

## 1.4.2

- **Kamera auswählen** in der Verwaltung: Liste aller Kameras aus Home
  Assistant mit Vorschaubild. „Übernehmen“ speichert die Wahl in der
  Add-on-Konfiguration und startet das Add-on neu.
- `kamera` und `input_number` stehen immer im Konfigurationsformular, auch
  solange sie leer sind (vorher unter den ausgeblendeten optionalen Optionen).
- Ohne Kamera verweisen Lernseite, Verwaltung und Protokoll auf die Auswahl.

## 1.4.1

- Fehlt der eingestellte `input_number`-Helfer in Home Assistant, meldet die
  Verwaltung das jetzt klar („… gibt es in Home Assistant nicht“). Vorher stand
  dort „ok“, obwohl nichts geschrieben wurde. Home Assistant meldet diesen Fall
  selbst nicht als Fehler.
- Doku: Der Sensor wird angelegt, falls er fehlt; ein vorhandener Sensor mit
  dem eingestellten Namen wird bewusst überschrieben.

## 1.4.0

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
