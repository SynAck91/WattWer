"""Config flow for WattWer."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.const import Platform
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_BACKGROUND_LOADS,
    CONF_BATTERY_CHARGE,
    CONF_BATTERY_DISCHARGE,
    CONF_CONSUMERS,
    CONF_DEADBAND,
    CONF_GENERATORS,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_GROUPS,
    CONF_HOUR_RETENTION_DAYS,
    CONF_HOUSE_NET,
    CONF_MAX_AGE,
    CONF_QUARTER_RETENTION_DAYS,
    CONF_SAMPLE_INTERVAL,
    CONF_SYNC_ENABLED,
    CONF_SYNC_DELAY,
    CONF_SYNC_BUFFER,
    CONF_SYNC_MAX_SAMPLE_AGE,
    DEFAULT_GENERATOR_MAX_AGE,
    DEFAULTS,
    DOMAIN,
    GENERATOR_ROLE_MAIN_BUS,
    NAME,
)
from .model import new_consumer_id, new_generator_id

FIELD_FIRST_CONSUMER = "first_consumer"
FIELD_INITIAL_PV = "initial_pv_generators"


def _power_selector(*, multiple: bool = False) -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain=Platform.SENSOR, multiple=multiple))


def _number(minimum: float, maximum: float, step: float) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=step,
            mode=NumberSelectorMode.BOX,
        )
    )


class WattWerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a generic WattWer installation."""

    VERSION = 2

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            if bool(user_input.get(CONF_BATTERY_CHARGE)) != bool(
                user_input.get(CONF_BATTERY_DISCHARGE)
            ):
                errors["base"] = "battery_pair_required"
            elif user_input.get(CONF_BATTERY_CHARGE) and not (user_input.get(FIELD_INITIAL_PV) or []):
                errors["base"] = "battery_requires_generator"
            elif bool(user_input.get(CONF_SYNC_ENABLED, DEFAULTS[CONF_SYNC_ENABLED])) and float(user_input.get(CONF_SYNC_BUFFER, DEFAULTS[CONF_SYNC_BUFFER])) < (
                float(user_input.get(CONF_SYNC_DELAY, DEFAULTS[CONF_SYNC_DELAY]))
                + float(user_input.get(CONF_SYNC_MAX_SAMPLE_AGE, DEFAULTS[CONF_SYNC_MAX_SAMPLE_AGE]))
            ):
                errors["base"] = "sync_buffer_too_small"
            else:
                first_entity = str(user_input[FIELD_FIRST_CONSUMER])
                grid_entities = {str(user_input[CONF_GRID_IMPORT]), str(user_input[CONF_GRID_EXPORT])}
                background_entities = set(str(x) for x in (user_input.get(CONF_BACKGROUND_LOADS) or []))
                pv_entities = set(str(x) for x in (user_input.get(FIELD_INITIAL_PV) or []))
                if len(grid_entities) != 2 or first_entity in grid_entities or first_entity in background_entities or pv_entities & (grid_entities | background_entities | {first_entity}):
                    errors["base"] = "source_overlap"
                    return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)
                first_state = self.hass.states.get(first_entity)
                first_name = (
                    str(first_state.attributes.get("friendly_name"))
                    if first_state and first_state.attributes.get("friendly_name")
                    else first_entity
                )
                first_id = new_consumer_id(first_entity)
                consumers = [
                    {
                        "id": first_id,
                        "entity_id": first_entity,
                        "name": first_name,
                        "role": "normal",
                        "enabled": True,
                        "icon": "mdi:flash",
                        "description": "",
                    }
                ]

                generators: list[dict[str, Any]] = []
                for entity_id in user_input.get(FIELD_INITIAL_PV) or []:
                    state = self.hass.states.get(entity_id)
                    name = (
                        str(state.attributes.get("friendly_name"))
                        if state and state.attributes.get("friendly_name")
                        else entity_id
                    )
                    generators.append(
                        {
                            "id": new_generator_id(entity_id),
                            "entity_id": entity_id,
                            "fallback_entity_id": None,
                            "name": name,
                            "role": GENERATOR_ROLE_MAIN_BUS,
                            "consumer_id": None,
                            "enabled": True,
                            "night_zero": True,
                            "max_age": float(DEFAULT_GENERATOR_MAX_AGE),
                            "icon": "mdi:solar-power",
                            "description": "",
                        }
                    )

                data = {
                    CONF_GRID_IMPORT: user_input[CONF_GRID_IMPORT],
                    CONF_GRID_EXPORT: user_input[CONF_GRID_EXPORT],
                    CONF_HOUSE_NET: user_input.get(CONF_HOUSE_NET),
                    CONF_BACKGROUND_LOADS: list(user_input.get(CONF_BACKGROUND_LOADS) or []),
                    CONF_BATTERY_CHARGE: user_input.get(CONF_BATTERY_CHARGE),
                    CONF_BATTERY_DISCHARGE: user_input.get(CONF_BATTERY_DISCHARGE),
                    CONF_SAMPLE_INTERVAL: int(user_input[CONF_SAMPLE_INTERVAL]),
                    CONF_MAX_AGE: float(user_input[CONF_MAX_AGE]),
                    CONF_DEADBAND: float(user_input[CONF_DEADBAND]),
                    CONF_QUARTER_RETENTION_DAYS: int(user_input[CONF_QUARTER_RETENTION_DAYS]),
                    CONF_HOUR_RETENTION_DAYS: int(user_input[CONF_HOUR_RETENTION_DAYS]),
                    CONF_SYNC_ENABLED: bool(user_input.get(CONF_SYNC_ENABLED, DEFAULTS[CONF_SYNC_ENABLED])),
                    CONF_SYNC_DELAY: float(user_input.get(CONF_SYNC_DELAY, DEFAULTS[CONF_SYNC_DELAY])),
                    CONF_SYNC_BUFFER: float(user_input.get(CONF_SYNC_BUFFER, DEFAULTS[CONF_SYNC_BUFFER])),
                    CONF_SYNC_MAX_SAMPLE_AGE: float(user_input.get(CONF_SYNC_MAX_SAMPLE_AGE, DEFAULTS[CONF_SYNC_MAX_SAMPLE_AGE])),
                    CONF_CONSUMERS: consumers,
                    CONF_GROUPS: [],
                    CONF_GENERATORS: generators,
                }
                return self.async_create_entry(title=NAME, data=data)

        return self.async_show_form(step_id="user", data_schema=self._schema(), errors=errors)

    def _schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_GRID_IMPORT): _power_selector(),
                vol.Required(CONF_GRID_EXPORT): _power_selector(),
                vol.Required(FIELD_FIRST_CONSUMER): _power_selector(),
                vol.Optional(FIELD_INITIAL_PV, default=[]): _power_selector(multiple=True),
                vol.Optional(CONF_HOUSE_NET): _power_selector(),
                vol.Optional(CONF_BACKGROUND_LOADS, default=[]): _power_selector(multiple=True),
                vol.Optional(CONF_BATTERY_CHARGE): _power_selector(),
                vol.Optional(CONF_BATTERY_DISCHARGE): _power_selector(),
                vol.Required(CONF_SAMPLE_INTERVAL, default=DEFAULTS[CONF_SAMPLE_INTERVAL]): _number(2, 30, 1),
                vol.Required(CONF_MAX_AGE, default=DEFAULTS[CONF_MAX_AGE]): _number(5, 300, 1),
                vol.Required(CONF_DEADBAND, default=DEFAULTS[CONF_DEADBAND]): _number(0, 100, 0.5),
                vol.Required(CONF_QUARTER_RETENTION_DAYS, default=DEFAULTS[CONF_QUARTER_RETENTION_DAYS]): _number(1, 366, 1),
                vol.Required(CONF_HOUR_RETENTION_DAYS, default=DEFAULTS[CONF_HOUR_RETENTION_DAYS]): _number(31, 3650, 1),
                vol.Required(CONF_SYNC_ENABLED, default=DEFAULTS[CONF_SYNC_ENABLED]): bool,
                vol.Required(CONF_SYNC_DELAY, default=DEFAULTS[CONF_SYNC_DELAY]): _number(0, 30, 0.5),
                vol.Required(CONF_SYNC_BUFFER, default=DEFAULTS[CONF_SYNC_BUFFER]): _number(10, 300, 1),
                vol.Required(CONF_SYNC_MAX_SAMPLE_AGE, default=DEFAULTS[CONF_SYNC_MAX_SAMPLE_AGE]): _number(2, 120, 1),
            }
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return WattWerOptionsFlow()


class WattWerOptionsFlow(OptionsFlow):
    """Minimal native fallback; normal configuration uses WattWer's rich panel."""

    async def async_step_init(self, user_input=None):
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({}),
            description_placeholders={"path": "/wattwer-config"},
        )
