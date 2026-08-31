"""WebSocket API for WattWer dashboards and configuration."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .backfill import BackfillArchive, async_run_backfill
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
    DEFAULT_GENERATOR_MAX_AGE,
    DEFAULTS,
    DOMAIN,
    GENERATOR_ROLE_DIRECT_CONSUMER,
    GENERATOR_ROLE_MAIN_BUS,
    GENERATOR_ROLES,
    VERSION,
)
from .controller import PVAllocationController
from .history import async_get_history
from .model import (
    new_consumer_id,
    new_generator_id,
    new_group_id,
    validate_consumer_config,
    validate_generator_config,
)


def _controller(hass: HomeAssistant) -> PVAllocationController | None:
    for key, value in hass.data.get(DOMAIN, {}).items():
        if not key.startswith("_") and isinstance(value, PVAllocationController):
            return value
    return None


def _archive(controller: PVAllocationController) -> BackfillArchive:
    return controller.archive  # type: ignore[attr-defined]


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_summary)
    websocket_api.async_register_command(hass, ws_history)
    websocket_api.async_register_command(hass, ws_config)
    websocket_api.async_register_command(hass, ws_update_config)
    websocket_api.async_register_command(hass, ws_update_settings)
    websocket_api.async_register_command(hass, ws_backfill_status)
    websocket_api.async_register_command(hass, ws_backfill)


@callback
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/summary"})
def ws_summary(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return
    connection.send_result(msg["id"], controller.get_summary())


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/history",
        vol.Required("start"): vol.Coerce(int),
        vol.Required("end"): vol.Coerce(int),
        vol.Optional("resolution", default="auto"): vol.In(["auto", "15m", "hour", "day"]),
    }
)
@websocket_api.async_response
async def ws_history(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return
    result = await async_get_history(
        hass, controller, _archive(controller), msg["start"], msg["end"], msg["resolution"]
    )
    connection.send_result(msg["id"], result)


@callback
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/config"})
def ws_config(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return
    connection.send_result(
        msg["id"],
        {
            "consumers": list(controller.consumer_metadata.values()),
            "groups": deepcopy(controller.groups),
            "generators": list(controller.generator_metadata.values()),
            "background_loads": list(controller.cfg.get(CONF_BACKGROUND_LOADS) or []),
            "settings": {
                key: deepcopy(controller.cfg.get(key, DEFAULTS.get(key)))
                for key in (
                    CONF_GRID_IMPORT,
                    CONF_GRID_EXPORT,
                    CONF_HOUSE_NET,
                    CONF_BACKGROUND_LOADS,
                    CONF_BATTERY_CHARGE,
                    CONF_BATTERY_DISCHARGE,
                    CONF_SAMPLE_INTERVAL,
                    CONF_MAX_AGE,
                    CONF_DEADBAND,
                    CONF_QUARTER_RETENTION_DAYS,
                    CONF_HOUR_RETENTION_DAYS,
                )
            },
            "version": VERSION,
            "can_manage": bool(connection.user and connection.user.is_admin),
        },
    )


def _normalize_consumers(raw_items: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("entity_id") or "").strip()
        cid = str(raw.get("id") or "").strip() or new_consumer_id(entity_id)
        if cid in used_ids:
            cid = new_consumer_id(entity_id)
        used_ids.add(cid)
        result.append(
            {
                "id": cid,
                "entity_id": entity_id,
                "name": str(raw.get("name") or "").strip(),
                "role": str(raw.get("role") or "normal"),
                "enabled": bool(raw.get("enabled", True)),
                "icon": str(raw.get("icon") or "mdi:flash").strip() or "mdi:flash",
                "description": str(raw.get("description") or "").strip(),
            }
        )
    return result


def _normalize_groups(raw_items: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        gid = str(raw.get("id") or "").strip() or new_group_id(name)
        if gid in used_ids:
            gid = new_group_id(name)
        used_ids.add(gid)
        result.append(
            {
                "id": gid,
                "name": name,
                "members": list(dict.fromkeys(str(x) for x in (raw.get("members") or []))),
            }
        )
    return result


def _normalize_generators(raw_items: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        entity_id = str(raw.get("entity_id") or "").strip()
        gid = str(raw.get("id") or "").strip() or new_generator_id(entity_id)
        if gid in used_ids:
            gid = new_generator_id(entity_id)
        used_ids.add(gid)
        role = str(raw.get("role") or GENERATOR_ROLE_MAIN_BUS)
        if role not in GENERATOR_ROLES:
            role = GENERATOR_ROLE_MAIN_BUS
        try:
            max_age = max(5.0, min(3600.0, float(raw.get("max_age", DEFAULT_GENERATOR_MAX_AGE))))
        except (TypeError, ValueError):
            max_age = float(DEFAULT_GENERATOR_MAX_AGE)
        result.append(
            {
                "id": gid,
                "entity_id": entity_id,
                "fallback_entity_id": str(raw.get("fallback_entity_id") or "").strip() or None,
                "name": str(raw.get("name") or "").strip(),
                "role": role,
                "consumer_id": (
                    str(raw.get("consumer_id") or "").strip() or None
                    if role == GENERATOR_ROLE_DIRECT_CONSUMER
                    else None
                ),
                "enabled": bool(raw.get("enabled", True)),
                "night_zero": bool(raw.get("night_zero", True)),
                "max_age": max_age,
                "icon": str(raw.get("icon") or "mdi:solar-power").strip() or "mdi:solar-power",
                "description": str(raw.get("description") or "").strip(),
            }
        )
    return result


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/config/update",
        vol.Required("consumers"): list,
        vol.Optional("groups", default=[]): list,
        vol.Optional("generators"): list,
    }
)
@websocket_api.async_response
async def ws_update_config(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return

    consumers = _normalize_consumers(msg["consumers"])
    groups = _normalize_groups(msg.get("groups") or [])
    generators = (
        _normalize_generators(msg.get("generators") or [])
        if "generators" in msg
        else list(controller.generator_metadata.values())
    )
    if error := validate_consumer_config(consumers, groups):
        connection.send_error(msg["id"], error, error)
        return
    if error := validate_generator_config(generators, consumers):
        connection.send_error(msg["id"], error, error)
        return

    backgrounds = set(str(x) for x in (controller.cfg.get(CONF_BACKGROUND_LOADS) or []))
    active_consumer_entities = {x["entity_id"] for x in consumers if x.get("enabled", True)}
    if overlap := backgrounds & active_consumer_entities:
        connection.send_error(msg["id"], "consumer_background_duplicate", ", ".join(sorted(overlap)))
        return
    generator_entities = {
        eid
        for item in generators
        if item.get("enabled", True)
        for eid in (item.get("entity_id"), item.get("fallback_entity_id"))
        if eid
    }
    if overlap := generator_entities & active_consumer_entities:
        connection.send_error(msg["id"], "generator_consumer_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := generator_entities & backgrounds:
        connection.send_error(msg["id"], "generator_background_duplicate", ", ".join(sorted(overlap)))
        return
    grid_entities = {
        str(controller.cfg.get(CONF_GRID_IMPORT) or ""),
        str(controller.cfg.get(CONF_GRID_EXPORT) or ""),
    }
    grid_entities.discard("")
    if overlap := generator_entities & grid_entities:
        connection.send_error(msg["id"], "generator_grid_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := active_consumer_entities & grid_entities:
        connection.send_error(msg["id"], "consumer_grid_duplicate", ", ".join(sorted(overlap)))
        return

    new_options = {
        **controller.entry.options,
        CONF_CONSUMERS: consumers,
        CONF_GROUPS: groups,
        CONF_GENERATORS: generators,
    }
    await _archive(controller).async_record_revision(
        {"consumers": consumers, "groups": groups, "generators": generators}
    )
    hass.config_entries.async_update_entry(controller.entry, options=new_options)
    connection.send_result(msg["id"], {"ok": True, "reload": True})
    hass.async_create_task(hass.config_entries.async_reload(controller.entry.entry_id))


@callback
@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/backfill/status"})
def ws_backfill_status(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return
    result = _archive(controller).status()
    result["can_run"] = bool(connection.user and connection.user.is_admin)
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/backfill/run",
        vol.Required("start"): vol.Coerce(int),
        vol.Required("end"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def ws_backfill(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return
    try:
        result = await async_run_backfill(hass, controller, _archive(controller), msg["start"], msg["end"])
    except ValueError as err:
        connection.send_error(msg["id"], str(err), str(err))
        return
    connection.send_result(msg["id"], result)


def _clean_optional_entity(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_settings(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    settings: dict[str, Any] = {}
    for key in (CONF_GRID_IMPORT, CONF_GRID_EXPORT):
        value = str(raw.get(key) or "").strip()
        if not value:
            return None, "required_source_missing"
        settings[key] = value
    for key in (CONF_HOUSE_NET, CONF_BATTERY_CHARGE, CONF_BATTERY_DISCHARGE):
        settings[key] = _clean_optional_entity(raw.get(key))
    settings[CONF_BACKGROUND_LOADS] = list(
        dict.fromkeys(str(x).strip() for x in (raw.get(CONF_BACKGROUND_LOADS) or []) if str(x).strip())
    )
    try:
        settings[CONF_SAMPLE_INTERVAL] = int(raw.get(CONF_SAMPLE_INTERVAL, DEFAULTS[CONF_SAMPLE_INTERVAL]))
        settings[CONF_MAX_AGE] = float(raw.get(CONF_MAX_AGE, DEFAULTS[CONF_MAX_AGE]))
        settings[CONF_DEADBAND] = float(raw.get(CONF_DEADBAND, DEFAULTS[CONF_DEADBAND]))
        settings[CONF_QUARTER_RETENTION_DAYS] = int(raw.get(CONF_QUARTER_RETENTION_DAYS, DEFAULTS[CONF_QUARTER_RETENTION_DAYS]))
        settings[CONF_HOUR_RETENTION_DAYS] = int(raw.get(CONF_HOUR_RETENTION_DAYS, DEFAULTS[CONF_HOUR_RETENTION_DAYS]))
    except (TypeError, ValueError):
        return None, "invalid_numeric_setting"
    if not 2 <= settings[CONF_SAMPLE_INTERVAL] <= 30:
        return None, "invalid_sample_interval"
    if not 5 <= settings[CONF_MAX_AGE] <= 300:
        return None, "invalid_max_age"
    if not 0 <= settings[CONF_DEADBAND] <= 100:
        return None, "invalid_deadband"
    if not 1 <= settings[CONF_QUARTER_RETENTION_DAYS] <= 366:
        return None, "invalid_quarter_retention"
    if not 31 <= settings[CONF_HOUR_RETENTION_DAYS] <= 3650:
        return None, "invalid_hour_retention"
    if bool(settings[CONF_BATTERY_CHARGE]) != bool(settings[CONF_BATTERY_DISCHARGE]):
        return None, "battery_pair_required"
    return settings, None


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/config/settings_update",
        vol.Required("settings"): dict,
    }
)
@websocket_api.async_response
async def ws_update_settings(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return
    settings, error = _normalize_settings(msg["settings"])
    if error or settings is None:
        connection.send_error(msg["id"], error or "invalid_settings", error or "invalid_settings")
        return
    if settings[CONF_BATTERY_CHARGE] and not any(x.get("enabled", True) for x in controller.all_generators.values()):
        connection.send_error(msg["id"], "battery_requires_generator", "battery_requires_generator")
        return
    backgrounds = set(settings[CONF_BACKGROUND_LOADS])
    active_entities = {x["entity_id"] for x in controller.all_consumers.values() if x.get("enabled", True)}
    generator_entities = {
        eid
        for item in controller.all_generators.values()
        if item.get("enabled", True)
        for eid in (item.get("entity_id"), item.get("fallback_entity_id"))
        if eid
    }
    grid_entities = {settings[CONF_GRID_IMPORT], settings[CONF_GRID_EXPORT]}
    if len(grid_entities) != 2:
        connection.send_error(msg["id"], "grid_sources_duplicate", "grid_sources_duplicate")
        return
    if overlap := backgrounds & active_entities:
        connection.send_error(msg["id"], "consumer_background_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := generator_entities & (backgrounds | active_entities | grid_entities):
        connection.send_error(msg["id"], "source_overlap", ", ".join(sorted(overlap)))
        return
    if overlap := active_entities & grid_entities:
        connection.send_error(msg["id"], "source_overlap", ", ".join(sorted(overlap)))
        return
    new_options = {**controller.entry.options, **settings}
    hass.config_entries.async_update_entry(controller.entry, options=new_options)
    connection.send_result(msg["id"], {"ok": True, "reload": True})
    hass.async_create_task(hass.config_entries.async_reload(controller.entry.entry_id))
