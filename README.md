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
- synchronisierte Live-Zuordnung asynchron meldender Sensoren über zeitgestempelten Messwertpuffer und Sample-and-Hold
- adaptive Frischebewertung pro Netz-, Verbraucher-, Batterie- und PV-Sensor anhand seines gelernten Meldeintervalls
- Diagnose von typischem Meldeintervall, aktuellem Alter, Warnschwelle und hartem Timeout je Sensor
- feste 15-Minuten-Auswertung
- Home-Assistant Long-Term Statistics über kumulative Energie-Sensoren
- historischer Backfill aus noch vorhandenen Recorder-Rohdaten
- eigenes WattWer-Dashboard und eigenes Konfigurationspanel
- vorbereitet für Batteriespeicher mit getrennten Lade-/Entlade-Leistungssensoren
- optionaler Hardware-Energiezähler je Verbraucher zur Kalibrierung der integrierten Gesamt-kWh
- Hybridmodus auch im historischen Backfill
- optionale kumulative PV-Energiezähler je Erzeuger zur Kalibrierung/Prüfung der erzeugten kWh
- exakte energiebasierte Kostenabrechnung mit historischen Netz-, PV- und optional Batterie-Tarifen
- eigener Preisverlauf je PV-Erzeuger mit `Gültig ab`-Datum
- einstellbares Zahlenformat; Standard Deutsch `1.000,00`

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

## Optionale Energiezähler / Hybridmessung

Zusätzlich zum verpflichtenden Leistungssensor kann jedem Verbraucher optional ein **kumulativer Energiezähler** zugeordnet werden, z. B. ein Shelly-Sensor mit `device_class: energy` und `state_class: total_increasing`. WattWer ersetzt die Leistungsmessung dadurch **nicht**: Die Watt-Werte bleiben notwendig, um den zeitgleichen Quellenmix aus PV, Netz und Batterie zu bestimmen.

Bei einem abgeschlossenen 15-Minuten-Fenster vergleicht WattWer die integrierte Leistung mit dem Delta des Hardware-Energiezählers. Ist der Zähler plausibel, gilt dessen Delta als Gesamtenergie des Verbrauchers. Die aus den Leistungssamples bestimmten Quellenanteile werden anschließend proportional auf diesen Gesamtwert normiert:

```text
Gesamt-kWh = Hardware-Zählerdelta
PV-/Netz-/Batterie-Anteile = aus zeitgleichen Leistungssamples
PV-kWh + Netz-kWh + Batterie-kWh = Gesamt-kWh
```

Im Verbraucher-Editor stehen drei Modi zur Verfügung:

- **Automatisch (empfohlen):** WattWer verwendet einen als Energie-/Total-Zähler erkannten Sensor, sofern sein Delta plausibel ist.
- **Energiezähler bevorzugen:** Der konfigurierte kumulative Zähler wird bevorzugt verwendet; Sicherheitsprüfungen gegen Rücksprünge und ausbleibenden Zählerfortschritt bleiben aktiv.
- **Nur Leistungsintegration:** Verhalten wie vor 0.6.0; der optionale Energiezähler wird ignoriert.

Bei `unknown`/`unavailable`, Zählerreset, Rücksprung oder einem Zähler, der trotz klar gemessener Last nicht fortschreitet, fällt WattWer für das betroffene Intervall automatisch auf die Leistungsintegration zurück. Unterstützte Energieeinheiten sind Wh, kWh, MWh, J, kJ und MJ.

**Backfill:** Historische Energiezähler werden ebenfalls berücksichtigt. Wenn die kumulativen Zählerstände im Recorder für Start und Ende eines Viertelstundenfensters vorhanden sind, kalibriert WattWer den rückwirkenden Gesamtverbrauch mit dem historischen Zählerdelta und verwendet die historischen Leistungswerte weiterhin für PV-/Netz-/Batterieanteile. Fehlen die Zählerstände, bleibt dieses einzelne Intervall beim Power-Fallback.

### PV-Energiezähler

Auch jedem PV-Erzeuger kann optional ein kumulativer Energiezähler zugeordnet werden. WattWer vergleicht dessen Delta pro abgeschlossenem 15-Minuten-Fenster mit der aus der PV-Leistung integrierten Erzeugungsenergie. Bei plausiblen Daten wird das Hardware-Zählerdelta als kalibrierter Erzeugungswert des PV-Erzeugers geführt; bei fehlendem, zurückgesetztem oder unplausiblem Zähler bleibt die Leistungsintegration aktiv. Dieselbe Auswertung wird beim Backfill auf historische Zählerstände angewendet.

Der PV-Energiezähler skaliert **nicht** pauschal die PV-kWh einzelner Verbraucher. Das wäre physikalisch falsch, weil erzeugte PV-Energie auch ins Netz eingespeist oder in eine Batterie geladen werden kann. Die Verbraucherzuordnung bleibt daher zeitgleich auf Leistungs-/Netzbilanz und elektrischer Topologie basiert; der PV-kWh-Zähler verbessert die Erzeugungsdiagnose und Plausibilisierung.

## Kostenabrechnung und Tarifhistorie

WattWer kann die Kosten **energiebasiert je Abrechnungsintervall** berechnen. Die Preise werden nicht als einzelner überschreibbarer Wert gespeichert, sondern als Tarifhistorie mit einem lokalen `Gültig ab`-Datum. Dadurch kann z. B. ein neuer Stromtarif ab `01.01.2027` ergänzt werden, ohne die Kosten aus 2026 zu verändern.

Konfigurierbar sind:

- zentraler Netzbezugspreis pro kWh mit beliebig vielen Preisperioden,
- eigener PV-Kostenpreis pro kWh **für jeden PV-Erzeuger** mit eigener Historie,
- optional ein Batterie-Kostenpreis pro kWh bei aktivierter Batterie,
- Währung.

Für Verbraucher `i` wird innerhalb eines Zeitfensters gerechnet:

```text
Kosten_i = Netz_kWh_i × Netzpreis
         + Summe(PV_kWh_i,Erzeuger × PV-Preis_Erzeuger)
         + Batterie_kWh_i × Batteriepreis
```

WattWer führt dafür die PV-Zuordnung zusätzlich je physischem Erzeuger. Die Kosten sind damit exakt **innerhalb der in WattWer definierten zeitgleichen Zuordnungsregel**. Ist die Herkunft eines PV-Anteils wegen fehlender Erzeugermessungen nicht eindeutig, wird dieser Anteil bewusst als **ungepreist** ausgewiesen und nicht mit einem geratenen Durchschnittspreis bewertet. Die Kostenabdeckung zeigt, welcher Anteil der verbrauchten Energie tatsächlich mit einem gültigen Tarif bepreist werden konnte.

Beim Backfill wird ebenfalls der Tarif verwendet, der am historischen Zeitstempel gültig war. Eine spätere Tarifperiode verändert ältere Intervalle daher nicht. Wird ein bereits vorhandener alter Tarif bewusst bearbeitet, wird die historische Kostenberechnung entsprechend dieser korrigierten Tarifhistorie neu ausgewertet.

Das Dashboard zeigt Kosten in den Verbraucher-/Gruppenkarten und im Diagramm-Tooltip. Der CSV-Export enthält Gesamt-, PV-, Netz- und Batteriekosten sowie Kostenabdeckung und Währung.

Unter **Anzeige → Zahlenformat** kann die Darstellung browserlokal gewählt werden:

- **Deutsch `1.000,00`** (Standard)
- **Englisch `1,000.00`**
- **ohne Tausendertrennzeichen `1000,00`**

Intern rechnet WattWer weiterhin mit ungerundeten numerischen Werten; die Formatierung erfolgt nur bei der Anzeige.

## Messwert-Synchronisierung

Netzzähler, Shellys und Wechselrichter melden ihre Werte in Home Assistant nicht zwingend im selben Moment. WattWer kann die Live-Messwerte deshalb zeitlich ausrichten. Jeder gemeldete Wert wird zusammen mit seinem Home-Assistant-Zeitstempel gepuffert; die Berechnung läuft standardmäßig **5 Sekunden hinter der Echtzeit** und verwendet für den gemeinsamen Zielzeitpunkt jeweils den letzten gemeldeten Wert **vor oder genau an diesem Zeitpunkt**.

Diese Sample-and-Hold-Methode vermeidet insbesondere, dass ein neuer Netzleistungswert mit einem erst später eintreffenden Verbraucherwert vermischt oder ein zukünftiger Lastsprung rückwirkend vorgezogen wird.

Ab **0.5.6** bewertet WattWer die Frische nicht mehr mit einer einzigen starren Zeitgrenze. Für **jeden** Netz-, Verbraucher-, Batterie- und PV-Sensor werden die letzten Meldeintervalle beobachtet. Aus Median und robustem Jitter (MAD) lernt WattWer, wie schnell dieser Sensor normalerweise berichtet. Erst wenn das aktuelle Alter für genau diesen Sensor ungewöhnlich groß wird, erscheint der Status **verzögert**. Der zuletzt gültige Messwert wird dabei weiter per Sample-and-Hold verwendet. Ein separater harter Timeout verhindert, dass ein ausgefallener Sensor unbegrenzt fortgeschrieben wird: normale Sensoren standardmäßig nach **60 s**, PV-Erzeuger nach ihrem jeweils konfigurierten **maximalen Sensoralter**. Ein PV-Sensor, der typischerweise nur alle 60 s meldet, wird damit nicht mehr wie ein 5-s-Shelly behandelt.

Nach mindestens sechs gelernten Intervallen wird die Warnschwelle adaptiv bestimmt. Während der Lernphase gilt der Sensor als **lernt**, ohne die Energieerfassung unnötig zu blockieren. Lange Offline-/Nachtpausen werden nicht als normales Meldeintervall angelernt. Bei PV-Erzeugern mit aktiviertem Nacht-Fallback bleibt die sichere Regel **nachts ohne Messung = 0 W** erhalten. Primär- und Fallback-Sensor eines PV-Erzeugers lernen ihre Meldeintervalle unabhängig voneinander.

Im Dashboard zeigt der aufklappbare Bereich **Sensor-Timing** pro Entity das typische Meldeintervall, das aktuelle Sample-Alter, die adaptive Warnschwelle, den harten Timeout und den Lernstatus. Die absolute Messwertspreizung bleibt als Diagnose sichtbar, entscheidet aber nicht mehr allein darüber, ob ein Snapshot gültig ist. Eine echte Hardware-Zeitsynchronisation kann WattWer weiterhin nicht erzeugen; die zeitliche Zuordnung in Home Assistant wird jedoch deutlich robuster.

Das Verlaufsdiagramm bietet außerdem ein interaktives Tooltip beim Überfahren eines Balkens mit Zeitfenster, Datenabdeckung, Gesamtenergie, PV-/Netz-/Batterieenergie und den jeweiligen Anteilen.

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

### Vorzeichen von PV-Messungen

Nicht alle Messgeräte verwenden dieselbe Konvention. Ein Wechselrichter liefert Erzeugung häufig als **positiven** Wert, ein bidirektionaler Unterzähler kann Einspeisung dagegen als **negativen** Wert melden. WattWer 0.5.8 erlaubt deshalb pro PV-Erzeuger die Auswahl **+W = Erzeugung** oder **−W = Erzeugung**. Für den Fallback-Sensor kann unabhängig davon dieselbe oder eine abweichende Vorzeichenregel gewählt werden. Die Einstellung wird auch beim Backfill angewendet, sodass ein Zeitraum nach einer Korrektur der Vorzeichenkonfiguration erneut rekonstruiert werden kann. Ein neu ausgeführter Backfill ist dabei ausdrücklich ein **Korrektur-Backfill**: Bei gleicher oder besserer Datenabdeckung darf er einen alten Live-Datensatz für dasselbe Zeitfenster in der WattWer-Auswertung ersetzen. Die ursprüngliche Home-Assistant-Recorder-Historie wird dabei nicht gelöscht oder manipuliert.

## Update von WattWer 0.1–0.4

WattWer 0.5.8 enthält weiterhin die automatische Migration aus älteren WattWer-Versionen.

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

## Speicher & Schreiblast

WattWer berechnet intern weiterhin in kurzen Abständen (standardmäßig 5 s), schreibt diese Zwischensamples aber **nicht** als eigene 5-Sekunden-Zeitreihe auf die Festplatte.

Der kleine interne Runtime-Zustand wird ab 0.5.4 nur noch:

- alle **5 Minuten**, sofern sich Daten geändert haben,
- sofort nach dem Abschluss einer **15-Minuten-Abrechnungsperiode**,
- und beim Herunterfahren von Home Assistant

gespeichert. Dadurch sinkt die Schreiblast gegenüber älteren Versionen deutlich, ohne die 15-Minuten-Abrechnung zu gefährden.

Im WattWer-Dashboard gibt es außerdem den **einklappbaren** Bereich **Speicher & Statistik**. Sein offener/geschlossener Zustand bleibt bei Live-Refreshes und Seitenreloads browserlokal erhalten. Dort werden unter anderem angezeigt:

- tatsächliche Größe der WattWer-Runtime- und Backfill-Dateien,
- konservativ geschätztes logisches Runtime-Schreibvolumen pro Tag,
- Recorder-Aufbewahrungsdauer,
- Anzahl WattWer-Entitäten und Long-Term-Statistics-Serien,
- Anzahl und ältester Backfill-Datensatz für 15 Minuten, Stunden und Tage.

Die normalen Home-Assistant-Rohsensoren werden von WattWer nur gelesen. Deren Recorder-Schreiblast wird durch WattWer nicht erzeugt.

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
- synchronized live allocation for asynchronously reporting sensors using a timestamped buffer and sample-and-hold
- adaptive freshness learning per grid, consumer, battery, and PV sensor based on its own reporting cadence
- per-sensor diagnostics for typical reporting interval, current age, warning threshold, and hard timeout
- fixed 15-minute evaluation windows
- Home Assistant Long-Term Statistics through cumulative energy sensors
- historical backfill from raw Recorder data that is still available
- dedicated WattWer dashboard and configuration panel
- prepared for battery storage using separate charge and discharge power sensors
- optional cumulative hardware energy meter per consumer for total-kWh calibration
- the same hybrid method is available during historical backfill
- optional cumulative PV energy meter for each PV generator
- exact energy-based cost accounting with historical grid, PV, and optional battery tariffs
- an independent tariff history for every PV generator
- configurable number format; German `1.000,00` is the default

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

## Optional energy meters / hybrid measurement

Each consumer can optionally be assigned a **cumulative energy meter** in addition to its required power sensor, for example a Shelly entity with `device_class: energy` and `state_class: total_increasing`. The power sensor is **not replaced**: Watt values are still required to determine the time-correlated PV/grid/battery source mix.

When a 15-minute interval closes, WattWer compares the power integration with the hardware energy-counter delta. If the counter is plausible, its delta becomes the consumer's total energy. The source shares derived from the synchronized power samples are then normalized to that total:

```text
Total kWh = hardware meter delta
PV/grid/battery shares = derived from synchronized power samples
PV kWh + grid kWh + battery kWh = total kWh
```

Three modes are available in the consumer editor:

- **Automatic (recommended):** use a recognized energy/total counter when its delta is plausible.
- **Prefer energy meter:** prefer the configured cumulative counter while retaining safety checks for resets/backward jumps and a counter that does not advance.
- **Power integration only:** legacy behavior; ignore the optional energy counter.

If the counter is unavailable, resets, moves backwards, or does not advance despite clearly measured consumption, WattWer automatically falls back to power integration for that interval. Supported units are Wh, kWh, MWh, J, kJ and MJ.

**Backfill:** historical cumulative energy-counter states are used as well. When Recorder contains suitable counter values around a quarter-hour boundary, WattWer calibrates the reconstructed total energy from the historical counter delta while historical power samples continue to determine the PV/grid/battery shares. Missing or invalid counter history only affects that interval, which falls back to power integration.

### PV energy meters

Each PV generator may also have an optional cumulative energy counter. WattWer compares its interval delta with the PV power integration and uses it for generation diagnostics/calibration when plausible. This also works during backfill. A PV generation counter does **not** blindly scale consumer PV energy, because generation may also be exported to the grid or charge a battery.

## Cost accounting and tariff history

WattWer can calculate costs **from the allocated energy of each billing interval**. Prices are stored as dated tariff histories instead of one overwriteable value. Adding a new electricity price effective `2027-01-01`, for example, leaves all 2026 intervals on their historical tariff.

Configurable tariff histories include:

- grid import price per kWh,
- an individual PV cost per kWh for **every PV generator**,
- an optional battery discharge cost per kWh,
- currency.

For consumer `i` the accounting rule is:

```text
Cost_i = grid_kWh_i × grid_price
       + sum(PV_kWh_i,generator × PV_price_generator)
       + battery_kWh_i × battery_price
```

WattWer therefore retains PV allocation by physical generator in addition to aggregate PV energy. Costs are exact **within WattWer's configured simultaneous allocation rule**. If PV origin cannot be attributed to a known generator because source measurements are missing, WattWer leaves that energy **unpriced** instead of guessing an average PV price. Cost coverage indicates how much of the consumed energy had a valid tariff assignment.

Backfill selects the tariff that was valid at the historical interval timestamp. Adding a later tariff does not modify older costs. Deliberately editing an old tariff will, as expected, recalculate history according to the corrected tariff schedule.

Consumer/group cards and chart tooltips show costs, and CSV export includes total, PV, grid and battery cost, cost coverage and currency.

The browser-local **Display → Number format** option supports:

- **German `1.000,00`** (default)
- **English `1,000.00`**
- **no thousands separator `1000,00`**

Internal calculations remain numeric and unrounded; formatting is applied only for display.

## Measurement synchronization

Grid meters, Shelly devices, and inverters do not necessarily report to Home Assistant at exactly the same time. WattWer can therefore align live measurements on a common target timestamp. Each report is buffered together with its Home Assistant timestamp; by default the allocation runs **5 seconds behind wall-clock time** and uses the most recent reported sample **at or before the target timestamp** for every source.

This sample-and-hold approach avoids mixing a fresh grid value with a consumer value that arrives a few seconds later, and it never moves a future load step backwards in time.

Starting with **0.5.6**, WattWer no longer judges every source against one fixed freshness limit. It learns the reporting cadence of **each** grid, consumer, battery, and PV sensor from recent report intervals. A robust median and MAD-based jitter estimate determine when that particular sensor should be considered **delayed**. Its most recent valid sample remains usable during that delay. A separate hard fail-safe prevents indefinite sample hold: normal sensors default to **60 seconds**, while PV generators use their individually configured **maximum sensor age**. A PV sensor that normally reports once per minute is therefore not judged by the same timing expectation as a 5-second Shelly.

After at least six learned intervals, warning thresholds are adaptive. During warm-up the sensor is marked as **learning** instead of unnecessarily invalidating energy allocation. Long offline/night gaps are excluded from cadence learning. PV generators with night-zero enabled retain the safe **missing at night = 0 W** behavior, and primary/fallback PV sensors learn independently.

The dashboard now provides an expandable **Sensor timing** section showing each entity's typical interval, current age, adaptive warning threshold, hard timeout, and learning status. Absolute measurement spread remains visible as a diagnostic but no longer determines validity by itself. WattWer still cannot create true hardware-level clock synchronization, but the temporal allocation inside Home Assistant becomes substantially more robust.

The history chart also provides an interactive hover tooltip showing the time interval, data coverage, total energy, PV/grid/battery energy, and source percentages.

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

WattWer 0.5.8 continues to include automatic migration from older WattWer versions.

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

## Storage & write load

WattWer still calculates internally at short intervals (5 seconds by default), but it does **not** persist those intermediate samples as a dedicated 5-second time series.

Starting with 0.5.4, the small internal runtime state is persisted only:

- every **5 minutes** when data has changed,
- immediately after a completed **15-minute billing interval**,
- and when Home Assistant shuts down.

This significantly reduces unnecessary storage writes while preserving the 15-minute accounting data.

The WattWer dashboard also contains a **collapsible Storage & Statistics** section. Its open/closed state is preserved locally across live refreshes and page reloads. It shows, among other things:

- actual size of the WattWer runtime and backfill files,
- a conservative estimate of logical runtime writes per day,
- Home Assistant Recorder retention,
- number of WattWer entities and Long-Term Statistics series,
- count and oldest backfill record for 15-minute, hourly, and daily archives.

WattWer only reads the normal Home Assistant source sensors. Their Recorder write load is not generated by WattWer.

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


### Dashboard-Liveaktualisierung

Die Live-Aktualisierung kann unter **WattWer → Zahnrad → Anzeige** auf 5, 10, 30 oder 60 Sekunden gestellt werden. Der geöffnete Zustand von **Sensor-Timing** bleibt beim Live-Refresh erhalten und wird browserlokal gespeichert.

### Dashboard live refresh

The live refresh interval can be configured under **WattWer → Settings → Display** to 5, 10, 30 or 60 seconds. The expanded state of **Sensor Timing** is preserved during live refreshes and stored locally in the browser.
