"""Diagnostics for PV Energy Allocation."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .controller import PVAllocationController


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    controller: PVAllocationController = hass.data[DOMAIN][entry.entry_id]
    return {
        "configuration": {**entry.data, **entry.options},
        "battery_enabled": controller.battery_enabled,
        "battery_visible": controller.battery_visible,
        "coverage_lifetime_s": controller.coverage_lifetime_s,
        "summary": controller.get_summary(),
    }
