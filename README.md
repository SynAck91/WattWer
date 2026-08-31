<p align="center">
  <img src="custom_components/pv_energy_allocation/brand/icon@2x.png" alt="WattWer Logo" width="180">
</p>

<h1 align="center">WattWer</h1>

<p align="center">
  Zeitgleiche PV-, Netz- und Batterie-Zuordnung für Home Assistant
</p>

---

# Deutsch

WattWer ist eine Custom Integration für Home Assistant zur zeitgleichen Aufteilung elektrischer Verbraucher auf **PV**, **Netz** und optional **Batterie**.

Die Berechnung erfolgt auf Basis der aktuellen Leistungswerte in kurzen Intervallen (standardmäßig 5 s) und wird anschließend zu Energie in kWh integriert. Dadurch bleibt die zeitliche Korrelation zwischen Verbrauch und lokaler Erzeugung erhalten.

## ☕ WattWer unterstützen

Wenn dir WattWer hilft und du die Weiterentwicklung unterstützen möchtest:

[**WattWer auf Buy Me a Coffee unterstützen**](https://www.buymeacoffee.com/SynAck91)

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

WattWer 0.5.1 enthält eine automatische Migration.

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

## Hinweis zur Entstehung

Ich kann selbst leider nicht programmieren. WattWer wurde mit Unterstützung von **ChatGPT** entwickelt. Die Idee, die Anforderungen, die fachliche Ausrichtung und die praktische Erprobung stammen aus meinem Home-Assistant-Projekt; ChatGPT wurde insbesondere für die Umsetzung in Code, die Dokumentation und die Weiterentwicklung der Integration eingesetzt.

Bitte beachte daher, dass es sich um ein privates Community-Projekt handelt. Trotz sorgfältiger Tests können Fehler nicht ausgeschlossen werden. Prüfe insbesondere abrechnungsrelevante Ergebnisse auf Plausibilität und erstelle vor Updates ein Backup deiner Home-Assistant-Installation.

## Support

Fehler und Feature-Wünsche: https://github.com/SynAck91/WattWer/issues

## Lizenz

MIT

---

# English version below

WattWer is a custom integration for Home Assistant that allocates electrical consumption in real time to **solar PV**, **grid**, and optionally **battery** energy.

The calculation uses current power readings at short intervals (5 seconds by default) and integrates them into energy in kWh. This preserves the time correlation between consumption and local generation instead of distributing solar energy only after the fact.

## ☕ Support WattWer

If WattWer is useful to you and you would like to support further development:

[**Support WattWer on Buy Me a Coffee**](https://www.buymeacoffee.com/SynAck91)

## Features

- unlimited configurable consumers
- freely editable display names and MDI icons
- stable internal consumer IDs for statistics continuity
- consumer groups as non-destructive aggregate views
- unlimited editable PV generators
- PV generators connected to the common main bus or locally assigned to a consumer
- optional fallback power sensor for each PV generator
- configurable sensor freshness per PV generator
- optional night fallback to 0 W
- separate PV, grid, and battery energy
- fixed 15-minute evaluation windows
- Home Assistant Long-Term Statistics through cumulative energy sensors
- historical backfill from raw Recorder data that is still available
- dedicated WattWer dashboard and configuration panel
- prepared for battery storage using separate charge and discharge power sensors

## Allocation principle

For consumers connected to the same AC bus, WattWer applies the simultaneous source mix proportionally. A consumer using twice as much power therefore receives twice as much PV energy in absolute terms, while receiving the same instantaneous PV percentage.

A locally assigned PV generator is the exception: its output is allocated to the electrically linked consumer first. Only surplus generation is added to the common source mix. This mode should only be used when the physical metering topology actually supports that relationship.

Without a battery, WattWer maintains:

```text
Total energy = PV energy + grid energy
```

With a battery:

```text
Total energy = PV energy + grid energy + battery energy
```

## Installation via HACS

This repository follows the HACS structure for a custom integration:

```text
custom_components/pv_energy_allocation/
hacs.json
README.md
```

### Custom repository

1. Open HACS.
2. Open the menu → **Custom repositories**.
3. Add `https://github.com/SynAck91/WattWer`.
4. Select **Integration** as the category.
5. Install WattWer.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration** and search for **WattWer**.

## Initial setup

A new installation only requires generic measurement sources:

- grid import power
- grid export power
- at least one consumer power sensor

PV generators, background loads, a diagnostic total-power sensor, and battery power sensors are optional during initial setup. Additional consumers and PV generators can be added later through the WattWer configuration interface.

## PV generators

Each PV generator has a stable internal ID and can be edited independently:

- display name
- primary power sensor
- optional fallback sensor
- enabled/disabled state
- MDI icon
- maximum sensor age
- night fallback to 0 W
- connection to the **common main bus** or **locally to a consumer**

When replacing an inverter or meter, edit the existing PV generator and change only its entity instead of creating a new generator. This keeps the configuration history consistent.

## Updating from WattWer 0.1–0.4

WattWer 0.5.1 includes an automatic migration.

**Important: Do not delete the existing integration before updating.**

The upgrade preserves:

- domain `pv_energy_allocation`
- existing config entry
- existing consumer IDs
- existing entity `unique_id`s
- lifetime energy counters
- Recorder history
- Long-Term Statistics
- groups
- backfill archive

The previous fixed PV configuration is migrated automatically into the generic generator model. Legacy configuration fields are retained internally for rollback compatibility but are no longer used as defaults by the new logic.

## Data safety when editing

Existing consumers are not hard-deleted; they can be disabled. Their name, icon, and measurement entity can be changed without changing the stable internal consumer ID.

Groups do not create duplicate measurements and do not rewrite historical data. Group values are calculated as sums of their members.

## Backfill

WattWer can retrospectively integrate historical power measurements from the Home Assistant Recorder. Accuracy depends on which raw states are still available. Historical Recorder data cannot always determine whether a sensor kept reporting an unchanged value at regular intervals.

Backfilled data is therefore marked separately and is not injected as an artificial jump into current lifetime counters.

## Battery

Both charge and discharge power sensors must be configured for battery allocation. Battery discharge is kept as a separate energy source and is not automatically relabeled as PV energy.

Once battery operation is enabled, reliable PV generation measurements become more important because WattWer must distinguish direct PV generation from battery discharge. Missing generator measurements are therefore handled more conservatively in battery mode.

## Development note

I unfortunately do not know how to program myself. WattWer was developed with the assistance of **ChatGPT**. The idea, requirements, domain-specific decisions, and practical testing come from my Home Assistant project; ChatGPT has been used especially for implementing the code, documentation, and ongoing development of the integration.

Please keep in mind that WattWer is a private community project. Although it is tested carefully, bugs cannot be ruled out. In particular, verify billing-relevant results for plausibility and create a backup of your Home Assistant installation before updating.

## Support

Bugs and feature requests: https://github.com/SynAck91/WattWer/issues

## License

MIT
