# PV-Energiezuordnung für Home Assistant

Custom Integration für die zeitgleiche Zuordnung von PV-, Netz- und zukünftig Batterieenergie zu mehreren Verbrauchern.

## Für diese Installation voreingestellte Sensoren

- Netzbezug: `sensor.sunny_home_manager_2_metering_power_absorbed`
- Netzeinspeisung: `sensor.sunny_home_manager_2_metering_power_supplied`
- große PV: `sensor.sunny_tripower_x_20_pv_power`
- Balkonkraftwerk: `sensor.fw_bkw_switch_0_power`
- Kontrollwert BKW: `sensor.dtu_ac_leistung`
- bestehender Netto-Haussensor: `sensor.strom_gesamt` (nur Diagnose)
- AOR: `sensor.aor_total_active_power`
- Wärmepumpe: `sensor.waermepumpe_total_active_power`
- Allgemeinstrom: `sensor.allgemeinstrom_total_active_power`
- Fachwerkhaus Bruttoverbrauch: `sensor.fw_shellypro3em_total_active_power`
- weiterer Shelly: `sensor.shellypro3em_2cbcbbb187a4_total_active_power`
- Garage: `sensor.garage_leistung` (nur Hintergrundlast im Quellenmix)

## Berechnungsmodell

Die Integration liest die jeweils zuletzt gemeldeten Leistungssensoren in einem gemeinsamen Snapshot (Standard 5 s). Nur ausreichend frische numerische Zustände werden verwendet.

### FW / Balkonkraftwerk

Der FW-Shelly misst den Bruttoverbrauch. Das BKW liegt topologisch im FW-Zweig. Daher ist

`BKW_direkt_FW = min(BKW_Leistung, FW_Bruttoverbrauch)`

physikalisch innerhalb dieses Zweiges bestimmbar. Die verbleibende FW-Last nimmt am gemeinsamen Quellenmix des Hauptbusses teil; ein BKW-Überschuss wird zur PV-Quelle am Hauptbus.

### Hauptbus ohne Batterie

`Netzanteil = Netto-Netzbezug / Hauptbus-Senkenleistung`, begrenzt auf 0…1.

Der verbleibende Anteil wird als lokale PV-Deckung behandelt. Die Zuordnung erfolgt pro Snapshot und wird erst danach zeitlich integriert.

### Mit Sunny Island

Sobald sowohl Lade- als auch Entladeleistung konfiguriert sind, wird Batterieentladung als eigene Quelle geführt. Die Herkunft der vorher geladenen Energie wird absichtlich nicht rückwirkend als PV oder Netz umetikettiert.

## Speicherung

- interne Integration mit Left-Hold über das Zeitintervall zwischen zwei Snapshots
- feste Viertelstunden (UTC-Ausrichtung entspricht in Deutschland den lokalen Viertelstunden)
- laufender Viertelstunden-/Tagesbucket und Lifetime-Zähler werden minütlich in einer kleinen `.storage`-Datei gesichert
- die Integration schreibt **keine 5-Sekunden-Leistungszustände** in den Recorder
- abgeschlossene 15-Minuten-Sensoren ändern sich nur viermal pro Stunde; ihre Detailhistorie folgt der normalen Recorder-Retention
- kumulative kWh-Sensoren erzeugen native Home-Assistant Long-Term Statistics; das Dashboard fragt daraus Stunden- und Tageswerte ab
- Auto-Auflösung: 15 Minuten für kurze aktuelle Bereiche, Stunden für mittlere Bereiche bis standardmäßig 730 Tage, ansonsten Tage; Stunden können im Dashboard für die letzten zwei Jahre explizit gewählt werden
- bei HA-Ausfall wird keine Energie erfunden; die Datenabdeckung des Zeitfensters sinkt entsprechend

Die kumulativen Energie-Sensoren haben `device_class: energy` und `state_class: total_increasing`. Home Assistant erzeugt daraus die langfristigen Statistikreihen. Die stündlichen LTS selbst werden von Home Assistant dauerhaft gehalten; für sehr alte Ansichten verwendet das mitgelieferte Dashboard standardmäßig Tagesaggregation.

## Installation auf Home Assistant OS

1. Ordner `custom_components/pv_energy_allocation` nach `/config/custom_components/pv_energy_allocation` kopieren.
2. Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen** öffnen.
4. Nach **PV-Energiezuordnung** suchen und hinzufügen.
5. Die vorausgefüllten Entitäten kontrollieren und speichern.
6. In der Sidebar erscheint automatisch **PV-Verteilung**.

Es sind keine YAML-Helper, Utility Meter, Automationen, HACS-Karten oder Recorder-Ausschlüsse erforderlich.

## Nach der Installation prüfen

- nachts ohne PV: Netzanteil nahe 100 %
- bei sicherer Netzeinspeisung ohne Batterie: Netzanteil 0 %
- `Energiebilanzfehler Ø letzte 15 min` sollte langfristig um 0 W liegen
- `strom_gesamt Abweichung Ø letzte 15 min` sollte um 0 W liegen; dieser Wert überprüft die bestehende Template-Summe gegen die direkt gesampelten Rohverbraucher
- Datenabdeckung sollte möglichst nahe 100 % liegen

## Wichtige Einschränkung

Die Aufteilung paralleler Verbraucher auf gemeinsame Quellen ist außerhalb des lokal messbaren FW/BKW-Zweiges keine physikalisch eindeutige Elektronenzuordnung. Die Integration verwendet deshalb den zeitgleichen Quellenmix als neutrale Zuordnungsregel.

## Historische Daten vor Installation

Die Integration beginnt beim ersten Start mit der eigenen Zeitreihe. Ein automatisches Rückrechnen alter 5-Sekunden-Leistungswerte aus dem Recorder ist in Version 0.1.0 nicht enthalten.
