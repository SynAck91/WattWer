# Changelog

## 0.5.1

### Dokumentation / Support

- Buy Me a Coffee-Link zur README hinzugefügt.
- Versionsnummer auf 0.5.1 aktualisiert.
- Keine Änderungen an Domain, Config Entry, internen Verbraucher-IDs oder Statistik-IDs. Bestehende Messdaten bleiben beim Update erhalten.

## 0.5.0

### Allgemeine öffentliche Version

- Alle installationsspezifischen Entity-IDs aus Defaults, Dokumentation und Übersetzungen entfernt.
- Neuinstallationen starten mit einem generischen Setup statt fest eingebauten Verbrauchern.
- Bestehende Installationen werden automatisch und datenkompatibel migriert.
- Domain und historische Verbraucher-IDs bleiben unverändert, damit bestehende `unique_id`s und Long-Term Statistics weitergeführt werden.

### Universelles PV-Erzeuger-Modell

- Beliebig viele PV-Erzeuger statt fest verdrahteter Haupt-PV/Balkon-PV-Felder.
- Erzeuger frei benennbar und aktivierbar/deaktivierbar.
- Primärer und optionaler Fallback-Leistungssensor.
- Pro Erzeuger einstellbares maximales Sensoralter.
- Pro Erzeuger optionaler Nacht-Fallback auf 0 W.
- Erzeuger können am gemeinsamen Hauptbus oder lokal einem Verbraucher zugeordnet werden.
- Lokale Erzeugung deckt zuerst den zugeordneten Verbraucher; Überschuss fließt zum Hauptbus.
- Mehrere Hauptbus- und lokale PV-Erzeuger werden unterstützt.

### Oberfläche

- Neuer Tab **PV-Erzeugung** im WattWer-Konfigurationspanel.
- Verbraucherlogik von der früheren speziellen Verbraucherrolle entkoppelt.
- Diagnoseanzeige auf generische PV-Erzeugung umgestellt.

### HACS / GitHub

- `manifest.json` um Dokumentation, Issue Tracker und Codeowner ergänzt.
- HACS-Mindestversion von Home Assistant auf 2026.8.0 festgelegt.
- HACS-Validierungsworkflow ergänzt.
- MIT-Lizenz und `.gitignore` ergänzt.
