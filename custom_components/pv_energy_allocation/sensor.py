"""Sensor platform for PV Energy Allocation."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN, NAME, SOURCES, SOURCE_LABELS
from .controller import PVAllocationController


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME,
        manufacturer="WattWer",
        model="Zeitgleiche Quellenzuordnung",
    )


class AllocationBaseSensor(SensorEntity):
    """Base class for low-frequency allocation sensors."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, controller: PVAllocationController) -> None:
        self.entry = entry
        self.controller = controller
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.controller.add_listener(self.async_write_ha_state))


class LifetimeEnergySensor(AllocationBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(
        self,
        entry: ConfigEntry,
        controller: PVAllocationController,
        consumer_id: str,
        consumer_label: str,
        source: str,
    ) -> None:
        super().__init__(entry, controller)
        self.consumer_id = consumer_id
        self.source = source
        self._attr_name = f"{consumer_label} {SOURCE_LABELS[source]} Energie gesamt"
        self._attr_unique_id = f"{entry.entry_id}_{consumer_id}_{source}_energy_lifetime"

    @property
    def native_value(self) -> float:
        return self.controller.lifetime[self.consumer_id][self.source]


class LastQuarterEnergySensor(AllocationBaseSensor):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 4

    def __init__(
        self,
        entry: ConfigEntry,
        controller: PVAllocationController,
        consumer_id: str,
        consumer_label: str,
        source: str,
    ) -> None:
        super().__init__(entry, controller)
        self.consumer_id = consumer_id
        self.source = source
        self._attr_name = f"{consumer_label} {SOURCE_LABELS[source]} letzte 15 min"
        self._attr_unique_id = f"{entry.entry_id}_{consumer_id}_{source}_energy_last_15m"

    @property
    def native_value(self) -> float | None:
        record = self.controller.last_15m
        if not record:
            return None
        return record.get("values", {}).get(self.consumer_id, {}).get(self.source, 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        record = self.controller.last_15m
        if not record:
            return None
        start_ms = int(record["start"])
        return {
            "fenster_start_ms": start_ms,
            "fenster_ende_ms": start_ms + int(record["duration"] * 1000),
            "datenabdeckung_prozent": round(float(record["coverage"]) * 100, 2),
        }


class LastQuarterShareSensor(AllocationBaseSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        entry: ConfigEntry,
        controller: PVAllocationController,
        consumer_id: str,
        consumer_label: str,
        source: str,
    ) -> None:
        super().__init__(entry, controller)
        self.consumer_id = consumer_id
        self.source = source
        self._attr_name = f"{consumer_label} {SOURCE_LABELS[source]} Anteil letzte 15 min"
        self._attr_unique_id = f"{entry.entry_id}_{consumer_id}_{source}_share_last_15m"

    @property
    def native_value(self) -> float | None:
        record = self.controller.last_15m
        if not record:
            return None
        values = record.get("values", {}).get(self.consumer_id, {})
        total = float(values.get("total", 0.0))
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, float(values.get(self.source, 0.0)) / total * 100.0))


class CoverageLifetimeSensor(AllocationBaseSensor):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_suggested_display_precision = 0

    def __init__(self, entry: ConfigEntry, controller: PVAllocationController) -> None:
        super().__init__(entry, controller)
        self._attr_name = "Erfasste Messzeit gesamt"
        self._attr_unique_id = f"{entry.entry_id}_coverage_lifetime"

    @property
    def native_value(self) -> float:
        return self.controller.coverage_lifetime_s


class LastQuarterCoverageSensor(AllocationBaseSensor):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_suggested_display_precision = 1

    def __init__(self, entry: ConfigEntry, controller: PVAllocationController) -> None:
        super().__init__(entry, controller)
        self._attr_name = "Datenabdeckung letzte 15 min"
        self._attr_unique_id = f"{entry.entry_id}_coverage_last_15m"

    @property
    def native_value(self) -> float | None:
        if not self.controller.last_15m:
            return None
        return float(self.controller.last_15m["coverage"]) * 100.0


class LastQuarterDiagnosticSensor(AllocationBaseSensor):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_suggested_display_precision = 1

    def __init__(
        self,
        entry: ConfigEntry,
        controller: PVAllocationController,
        key: str,
        name: str,
    ) -> None:
        super().__init__(entry, controller)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}_last_15m"

    @property
    def native_value(self) -> float | None:
        if not self.controller.last_15m:
            return None
        value = self.controller.last_15m.get(self.key)
        return float(value) if value is not None else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors for a config entry."""
    controller: PVAllocationController = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    enabled_sources = list(SOURCES)
    if not controller.battery_visible:
        enabled_sources.remove("battery")

    for consumer_id, label in controller.consumer_labels.items():
        for source in enabled_sources:
            entities.append(
                LifetimeEnergySensor(entry, controller, consumer_id, label, source)
            )
            entities.append(
                LastQuarterEnergySensor(entry, controller, consumer_id, label, source)
            )
        for source in ("pv", "grid") + (("battery",) if controller.battery_visible else ()):
            entities.append(
                LastQuarterShareSensor(entry, controller, consumer_id, label, source)
            )

    entities.extend(
        [
            CoverageLifetimeSensor(entry, controller),
            LastQuarterCoverageSensor(entry, controller),
            LastQuarterDiagnosticSensor(
                entry,
                controller,
                "balance_error_avg_w",
                "Energiebilanzfehler Ø letzte 15 min",
            ),
            LastQuarterDiagnosticSensor(
                entry,
                controller,
                "house_net_error_avg_w",
                "strom_gesamt Abweichung Ø letzte 15 min",
            ),
        ]
    )
    async_add_entities(entities)
