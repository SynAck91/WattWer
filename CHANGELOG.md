# Changelog

## 0.5.2

- Backfill-/Recorder-Zusammenführung korrigiert: Bei überlappenden Intervallen gewinnt jetzt der Datensatz mit der höheren Datenabdeckung.
- Native Live-Daten bleiben bei gleicher oder besserer Abdeckung bevorzugt.
- Behebt leere historische Viertelstunden, wenn zuvor 0-%-Live-Intervalle einen erfolgreich rekonstruierten Backfill überdeckt haben.
- Backfill-Dialog schließt standardmäßig auch den heutigen Tag ein; das laufende Viertel wird weiterhin automatisch ausgeschlossen.
- Keine Änderung an Domain, Config Entry, Verbraucher-IDs oder Statistik-Unique-IDs.

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
