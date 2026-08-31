# Changelog

## 0.6.2

- Exakte energiebasierte Kostenabrechnung je 15-Minuten-Fenster auf Basis der tatsächlich zugeordneten kWh.
- Zeitabhängige **Netztarife** mit `Gültig ab`-Datum; neue Preisperioden überschreiben historische Preise nicht.
- Eigene zeitabhängige **PV-Kostenpreise je Erzeuger**. WattWer führt dafür die einem Verbraucher zugeordnete PV-Energie zusätzlich je physischem PV-Erzeuger.
- Optionaler zeitabhängiger Batterie-Kostenpreis bei aktivierter Batterie.
- Historische Kosten und Backfill verwenden immer den zum jeweiligen Intervall gültigen Tarif statt des aktuellsten Preises.
- Gruppen summieren die Kosten ihrer Mitglieder ohne historische Einzelwerte umzubuchen.
- Dashboard-Summenkarten und Diagramm-Tooltip zeigen Gesamt-, PV-, Netz- und ggf. Batteriekosten sowie die Kostenabdeckung. Nicht eindeutig einem bepreisten PV-Erzeuger zuordenbare Energie wird als **ungepreist** markiert statt geschätzt.
- CSV-Export enthält Kosten je Quelle, Kostenabdeckung und Währung.
- Zahlenformat ist browserlokal wählbar: **Deutsch `1.000,00` (Standard)**, Englisch `1,000.00` oder ohne Tausendertrennzeichen `1000,00`.
- Fix: PV-Tarifhistorien bleiben beim Speichern eines Erzeugers erhalten.
- Fix: Das Speichern allgemeiner WattWer-Einstellungen löscht bestehende Netz-/Batterie-Tarifhistorien oder die Währung nicht.
- Enthält außerdem die 0.6.1-Erweiterungen für optionale PV-Energiezähler und den einklappbaren Bereich „Speicher & Statistik“.
- Keine Änderung an Domain, Config Entry, bestehenden Verbraucher-/Erzeuger-/Gruppen-IDs oder bisherigen Statistik-Unique-IDs.

## 0.6.1

- Optionaler kumulativer **PV-Energiezähler pro Erzeuger** (Wh/kWh/MWh/J/kJ/MJ).
- PV-Leistung bleibt für die zeitliche Quellenzuordnung maßgeblich; der Hardware-kWh-Zähler kalibriert/prüft die tatsächlich erzeugte Energie eines abgeschlossenen 15-Minuten-Fensters.
- PV-Energiezähler werden auch beim Backfill aus der Recorder-Historie ausgewertet. Fehlende, zurückgesetzte oder unplausible Zähler fallen automatisch auf die Leistungsintegration des Erzeugers zurück.
- Der PV-Energiezähler verändert Verbraucher-PV-kWh nicht blind: Erzeugte PV kann auch eingespeist oder in eine Batterie geladen werden. Dadurch bleibt die Verbraucherbilanz physikalisch konsistent.
- Neuer aufklappbarer Dashboard-Bereich **PV-Energiezähler** mit Zählerdelta, Leistungsintegration, verwendetem Erzeugungswert und Abweichung.
- **Speicher & Statistik** ist jetzt einklappbar; der offene/geschlossene Zustand bleibt bei Live-Refresh und Seitenreload browserlokal erhalten.
- Keine Änderung an Domain, Config Entry, bestehenden Verbraucher-/Erzeuger-/Gruppen-IDs oder Statistik-Unique-IDs.


## 0.6.0

- Optionaler kumulativer **Energiezähler pro Verbraucher** (z. B. Shelly total/total_increasing in Wh/kWh).
- Neue Energiemodi: **Automatisch**, **Energiezähler bevorzugen** und **Nur Leistungsintegration**.
- Hybridberechnung: Die zeitgleichen Leistungssamples bestimmen weiterhin ausschließlich den PV-/Netz-/Batterie-Mix; der Hardware-Energiezähler kalibriert den Gesamtverbrauch eines abgeschlossenen 15-Minuten-Fensters.
- PV-, Netz- und Batterie-kWh werden proportional auf das gemessene Hardware-Zählerdelta normiert, sodass ihre Summe exakt dem kalibrierten Gesamtverbrauch entspricht.
- Automatischer Power-Fallback bei fehlendem/veraltetem Energiezähler, Zählerreset/Rücksprung, ausbleibendem Zählerfortschritt oder unplausiblem Delta.
- Energiezähler werden auf kWh normalisiert; unterstützt werden Wh, kWh, MWh, J, kJ und MJ.
- Viertelstunden-Lifetime-Zähler werden erst nach Abschluss des Intervalls committed. Dadurch bleiben `total_increasing`-Sensoren monoton, obwohl das Intervall vor dem Commit noch kalibriert werden kann.
- Migrationssicher von 0.5.x: Der beim Upgrade bereits in Lifetime enthaltene Anteil des laufenden Viertels wird nicht doppelt gezählt; das erste Übergangsviertel bleibt bewusst Power-only, ab dem nächsten vollständigen Viertel greift die Hybridkalibrierung.
- Backfill verwendet dieselbe Hybridlogik: Historische kumulative Energiezähler kalibrieren rekonstruierte 15-Minuten-Gesamtwerte, während historische Leistungswerte die Quellenanteile bestimmen.
- Backfill fällt intervallweise automatisch auf Leistungsintegration zurück, wenn historische Zählerwerte fehlen oder einen Reset/Rücksprung enthalten.
- Im Verbraucher-Editor kann der Energiezähler über einen eigenen Energy-Sensor-Browser gewählt werden.
- Dashboard-Diagnose **Energiezähler** zeigt für das letzte Viertel Zählerdelta, Leistungsintegration, Abweichung und verwendeten Fallbackstatus.
- Keine Änderung an Domain, Config Entry, Verbraucher-/Erzeuger-/Gruppen-IDs oder bestehenden Statistik-Unique-IDs.


## 0.5.9

- Dashboard: Der geöffnete Zustand von „Sensor-Timing“ bleibt bei Live-Refreshes erhalten.
- Der Zustand wird browserlokal gespeichert und bleibt auch nach einem Dashboard-Neuladen erhalten.
- Die vorhandene Einstellung „Anzeige → Live-Aktualisierung“ bleibt unverändert bei 5/10/30/60 Sekunden.
- Keine Änderungen an Config Entry, Verbraucher-/Erzeuger-IDs oder Statistik-IDs.

## 0.5.8

- Fix: PV-Erzeuger-Vorzeichen werden nach einem Reload wieder korrekt an das WattWer-Konfigurationspanel zurückgegeben.
- `polarity` und `fallback_polarity` bleiben beim vollständigen Speichern → Reload → Bearbeiten-Roundtrip erhalten.
- Verhindert, dass die Oberfläche nach einem Neustart fälschlich wieder `Positive Werte = Erzeugung` bzw. `Wie Hauptsensor` anzeigt.
- Keine Änderung an Config Entry, Verbraucher-/Erzeuger-IDs oder Statistik-IDs.

## 0.5.7

- Pro PV-Erzeuger ist das Erzeugungs-Vorzeichen jetzt auswählbar: **positive Werte = Erzeugung** oder **negative Werte = Erzeugung**.
- WattWer normalisiert beide Varianten intern auf positive Erzeugungsleistung, bevor lokale PV-Zuordnung, Hauptbus-Verteilung, Diagnose und Energieintegration berechnet werden.
- Der optionale Fallback-Sensor kann eine eigene Vorzeichenkonvention verwenden (**wie Hauptsensor**, **positiv**, **negativ**). Das unterstützt z. B. einen bidirektionalen Shelly mit negativer Einspeisung und eine DTU mit positiver Erzeugungsleistung.
- Die Vorzeichenregel gilt identisch für Live-Berechnung und historischen Backfill. Ein erneut ausgeführter Backfill kann daher früher falsch interpretierte PV-Zuordnungen korrigieren, solange die Rohdaten noch im Recorder vorhanden sind.
- Neu ausgeführte Backfills werden als **Korrektur-Backfill** markiert und dürfen bei gleicher oder besserer Datenabdeckung einen älteren nativen 15-Minuten-Wert übersteuern. Damit lassen sich auch zuvor mit falscher PV-Vorzeichenregel berechnete 100-%-Intervalle sichtbar korrigieren.
- Bestehende PV-Erzeuger behalten aus Kompatibilitätsgründen zunächst **positive Werte = Erzeugung**, bis die Einstellung geändert wird.
- Keine Änderung an Domain, Config Entry, Verbraucher-/Erzeuger-IDs, Gruppen oder Statistik-Unique-IDs.

## 0.5.6

- Adaptive Sensor-Frische für alle relevanten Netz-, Verbraucher-, Batterie- und PV-Sensoren.
- WattWer lernt pro Entity das typische Meldeintervall aus den letzten Reports (robuster Median + MAD/Jitter) statt alle Sensoren mit derselben starren 10-s-Grenze zu bewerten.
- Nach mindestens sechs Intervallen wird ein sensorabhängiger Warnzeitpunkt berechnet; verspätete Sensoren bleiben bis zum harten Timeout verwendbar und werden zunächst nur als **verzögert** markiert.
- Harter Fail-safe für normale Sensoren standardmäßig 60 s und im WattWer-Konfigurationspanel editierbar.
- PV-Erzeuger und deren Fallback-Sensoren lernen ebenfalls ihr eigenes Meldeverhalten; ihr konfiguriertes maximales Sensoralter bleibt der harte Timeout.
- Nacht-Fallback von PV-Erzeugern bleibt erhalten und lange Nacht-/Offline-Pausen werden nicht als normales Meldeintervall angelernt.
- Kurzzeitiges `unavailable` verwirft nicht sofort das letzte gültige Sample; dieses darf bis zum jeweiligen harten Timeout per Sample-and-Hold weiterverwendet werden.
- Neuer aufklappbarer Dashboard-Bereich **Sensor-Timing** mit typischem Intervall, aktuellem Alter, Warnschwelle, hartem Timeout und Lernstatus je Sensor.
- Die absolute Messwertspreizung bleibt Diagnosewert, entscheidet aber nicht mehr allein über die Synchronitätsqualität.
- Keine Telemetrie oder Entwickler-Tracking. Keine Änderung an Domain, Config Entry, Verbraucher-/Erzeuger-IDs, Gruppen oder Statistik-Unique-IDs.

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
