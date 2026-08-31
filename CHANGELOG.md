# Changelog

## 0.5.5

- Neue optionale Messwert-Synchronisierung für asynchron meldende Netz-, Verbraucher- und PV-Sensoren.
- WattWer puffert Live-Messwerte mit ihrem Home-Assistant-`last_reported`-Zeitstempel und rechnet standardmäßig 5 Sekunden verzögert auf einen gemeinsamen Zielzeitpunkt.
- Sample-and-Hold: Für jeden Zielzeitpunkt wird ausschließlich der letzte gemeldete Messwert vor oder genau am Zielzeitpunkt verwendet; zukünftige Messwerte werden nicht rückwirkend vorgezogen.
- Synchronisierungsparameter (aktiv, Verzögerung, Puffer, maximales Sample-Alter) sind im WattWer-Konfigurationspanel editierbar.
- Neue Live- und 15-Minuten-Diagnosen für Messwertspreizung und Sample-Alter.
- Das Verlaufsdiagramm zeigt beim Überfahren eines Balkens ein WattWer-Tooltip mit Zeitfenster, Datenabdeckung, Gesamt-, PV-, Netz- und Batterieenergie sowie Prozentanteilen.
- Keine Telemetrie oder Entwickler-Tracking hinzugefügt.
- Keine Änderung an Domain, Config Entry, Verbraucher-/Erzeuger-IDs, Gruppen oder bestehenden Statistik-Unique-IDs.

## 0.5.4

- Interner WattWer-Runtime-Zustand wird nur noch alle 5 Minuten gespeichert statt jede Minute.
- Abgeschlossene 15-Minuten-Fenster lösen weiterhin sofort eine persistente Speicherung aus.
- Beim Herunterfahren wird ein noch nicht gespeicherter Runtime-Zustand weiterhin geschrieben.
- Doppelte/unnötige Speichervorgänge werden über Dirty-State und Save-Coalescing vermieden.
- Neuer Dashboard-Bereich **Speicher & Statistik** mit tatsächlichen WattWer-Dateigrößen, konservativer Schreiblast-Schätzung, Recorder-Retention, Entitäts-/LTS-Anzahl sowie Backfill-Anzahl und ältesten Archivzeitpunkten.
- Keine Änderung an Domain, Config Entry, Verbraucher-IDs oder Statistik-Unique-IDs.

## 0.5.3

- Dashboard-Summenkarten verwenden für den heutigen Zeitraum jetzt dieselbe zusammengeführte 15-Minuten-Datenbasis wie der Verlauf.
- Backfill-Werte mit besserer Datenabdeckung fließen dadurch auch in Gesamt-, PV- und Netz-kWh sowie Prozentwerte der Verbraucher und Gruppen ein.
- Das aktuell laufende Viertel wird weiterhin nur einmal aus dem Live-Controller ergänzt.
- Keine Änderung an Config Entry, Verbraucher-IDs oder Statistik-Unique-IDs.

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
