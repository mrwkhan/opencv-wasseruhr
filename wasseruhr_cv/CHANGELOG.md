# Changelog

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
