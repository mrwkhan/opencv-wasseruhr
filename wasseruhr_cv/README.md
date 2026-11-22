# Wasseruhr-CV

Liest eine Wasseruhr per Kamera und OpenCV-Template-Matching ab, ohne LLM und
ohne Cloud, und schreibt den geprüften Zählerstand nach Home Assistant.

- Eigenständig: liest alle paar Minuten selbst ab, schreibt nur sichere und
  plausible Werte in einen Sensor (Energie-Dashboard) und optional einen Helfer
- Initiales Modell eingebaut, Lernseite und Verwaltung in der Seitenleiste zum
  Nachtrainieren
- Optional erreichbar im Heimnetz per HTTP und/oder HTTPS, Port frei wählbar

Einrichtung und Bedienung stehen im Reiter **Dokumentation**.
