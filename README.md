# WattWer

WattWer ist eine Custom Integration für Home Assistant zur zeitgleichen Aufteilung elektrischer Verbraucher auf **PV**, **Netz** und optional **Batterie**.

Die Berechnung erfolgt auf Basis der aktuellen Leistungswerte in kurzen Intervallen (standardmäßig 5 s) und wird anschließend zu Energie in kWh integriert. Dadurch bleibt die zeitliche Korrelation zwischen Verbrauch und lokaler Erzeugung erhalten.

## Funktionen

- beliebig viele Verbraucher
- frei änderbare Anzeigenamen und MDI-Icons
- stabile interne Verbraucher-IDs für Statistik-Kontinuität
- Verbrauchergruppen als reine Summenansicht
- beliebig viele editierbare PV-Erzeuger
- PV-Erzeuger am gemeinsamen Hauptbus oder lokal einem Verbraucher zugeordnet
- optionaler Fallback-Leistungssensor je PV-Erzeuger
- konfigurierbare Sensor-Frische je PV-Erzeuger
- optionaler Nacht-Fallback auf 0 W
- getrennte PV-/Netz-/Batterie-Energie
- feste 15-Minuten-Auswertung
- Home-Assistant Long-Term Statistics über kumulative Energie-Sensoren
- historischer Backfill aus noch vorhandenen Recorder-Rohdaten
- eigenes WattWer-Dashboard und eigenes Konfigurationspanel
- vorbereitet für Batteriespeicher mit getrennten Lade-/Entlade-Leistungssensoren

## Berechnungsprinzip

Für alle Verbraucher am gemeinsamen AC-Bus wird der zeitgleiche Quellenmix proportional angewendet. Ein Verbraucher mit doppelter Leistung erhält damit absolut doppelt so viel PV-Energie, aber denselben momentanen PV-Prozentsatz.

Ein lokal zugeordneter PV-Erzeuger ist eine Ausnahme: Seine Leistung deckt zuerst den elektrisch verknüpften Verbraucher. Nur der Überschuss fließt in den gemeinsamen Quellenmix. Diese Option sollte nur verwendet werden, wenn die Messpunkt-Topologie das tatsächlich hergibt.

Ohne Batterie gilt für jeden Verbraucher:

```text
Gesamtenergie = PV-Energie + Netzenergie
```

Mit Batterie:

```text
Gesamtenergie = PV-Energie + Netzenergie + Batterieenergie
```

## Installation über HACS

Dieses Repository erfüllt die HACS-Struktur für eine Custom Integration:

```text
custom_components/pv_energy_allocation/
hacs.json
README.md
```

### Benutzerdefiniertes Repository

1. HACS öffnen.
2. Menü → **Benutzerdefinierte Repositories**.
3. `https://github.com/SynAck91/WattWer` eintragen.
4. Kategorie **Integration** wählen.
5. WattWer installieren.
6. Home Assistant neu starten.
7. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **WattWer** suchen.

## Ersteinrichtung

Für eine neue Installation werden nur generische Messquellen verlangt:

- Netzbezug-Leistung
- Netzeinspeisung-Leistung
- mindestens ein Verbraucher-Leistungssensor

Optional können bereits PV-Erzeuger, Hintergrundlasten, ein Diagnose-Summensensor und Batterie-Leistungssensoren gewählt werden. Weitere Verbraucher und PV-Erzeuger lassen sich anschließend über das WattWer-Zahnrad konfigurieren.

## PV-Erzeuger

Jeder PV-Erzeuger besitzt eine stabile interne ID und kann unabhängig bearbeitet werden:

- Anzeigename
- primärer Leistungssensor
- optionaler Fallback-Sensor
- aktiv/deaktiviert
- MDI-Icon
- maximales Sensoralter
- Nacht-Fallback auf 0 W
- Einbindung am **gemeinsamen Hauptbus** oder **lokal bei einem Verbraucher**

Beim Wechsel eines Wechselrichters sollte der bestehende PV-Erzeuger bearbeitet und nur seine Entity geändert werden. Dadurch bleibt die Konfigurationshistorie konsistent.

## Update von WattWer 0.1–0.4

WattWer 0.5.0 enthält eine automatische Migration.

**Wichtig: Die bestehende Integration vor dem Update nicht löschen.**

Beim Upgrade bleiben erhalten:

- Domain `pv_energy_allocation`
- bestehender Config Entry
- bestehende Verbraucher-IDs
- bestehende Entity `unique_id`s
- Lifetime-Energiezähler
- Recorder-Historie
- Long-Term Statistics
- Gruppen
- Backfill-Archiv

Die bisherige feste PV-Konfiguration wird automatisch in das neue allgemeine Erzeuger-Modell übernommen. Alte Konfigurationsfelder bleiben intern als Rollback-Kompatibilität gespeichert, werden aber von der neuen Logik nicht mehr als Defaults verwendet.

## Datensicherheit bei Änderungen

Verbraucher werden nicht hart gelöscht, sondern können deaktiviert werden. Name, Icon und Mess-Entity können geändert werden, ohne die stabile interne Verbraucher-ID zu ändern.

Gruppen erzeugen keine neuen Messwerte und buchen keine Historie um. Gruppenwerte sind Summen ihrer Mitglieder.

## Backfill

WattWer kann historische Leistungsmessungen aus dem Home-Assistant-Recorder nachträglich integrieren. Die Genauigkeit hängt davon ab, welche Rohzustände noch vorhanden sind. Historische Recorder-Daten können insbesondere nicht immer rekonstruieren, ob ein Sensor bei unverändertem Wert regelmäßig erneut berichtet hat.

Backfill-Daten werden deshalb separat gekennzeichnet und nicht als künstlicher Sprung in die aktuellen Lifetime-Zähler geschrieben.

## Batterie

Für die Batteriezuordnung müssen Lade- und Entladeleistung gemeinsam konfiguriert sein. Batterieentladung wird als eigene Quelle geführt und nicht automatisch als PV umetikettiert.

Sobald Batteriebetrieb aktiv ist, wird die PV-Erzeugungsmessung für die saubere Trennung von PV und Batterie deutlich wichtiger. Fehlende Erzeugermessungen werden daher im Batteriemodus konservativer behandelt.

## Support

Fehler und Feature-Wünsche: https://github.com/SynAck91/WattWer/issues

## Lizenz

MIT
