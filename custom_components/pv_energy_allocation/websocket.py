"""WebSocket API for WattWer dashboards and configuration."""
from __future__ import annotations

from copy import deepcopy
import math
import os
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.recorder import get_instance as get_recorder_instance
from homeassistant.core import HomeAssistant, callback

from .backfill import BackfillArchive, async_run_backfill
from .const import (
    CONF_ADAPTIVE_FRESHNESS,
    CONF_ADAPTIVE_HARD_TIMEOUT,
    CONF_BACKGROUND_LOADS,
    CONF_BATTERY_CHARGE,
    CONF_BATTERY_DISCHARGE,
    CONF_CONSUMERS,
    ENERGY_MODES,
    ENERGY_MODE_AUTO,
    CONF_DEADBAND,
    CONF_GENERATORS,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_GRID_TARIFFS,
    CONF_BATTERY_TARIFFS,
    CONF_CURRENCY,
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
    GENERATOR_FALLBACK_POLARITIES,
    GENERATOR_FALLBACK_POLARITY_SAME,
    GENERATOR_POLARITIES,
    GENERATOR_POLARITY_POSITIVE,
    DEFAULTS,
    DOMAIN,
    GENERATOR_ROLE_DIRECT_CONSUMER,
    GENERATOR_ROLE_MAIN_BUS,
    GENERATOR_ROLES,
    STORAGE_SAVE_INTERVAL,
    VERSION,
)
from .controller import PVAllocationController
from .pricing import normalize_tariffs
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
    websocket_api.async_register_command(hass, ws_storage_status)
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
    CONF_GRID_TARIFFS,
    CONF_BATTERY_TARIFFS,
    CONF_CURRENCY,
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
                    CONF_SYNC_ENABLED,
                    CONF_SYNC_DELAY,
                    CONF_SYNC_BUFFER,
                    CONF_SYNC_MAX_SAMPLE_AGE,
                    CONF_ADAPTIVE_FRESHNESS,
                    CONF_ADAPTIVE_HARD_TIMEOUT,
                    CONF_GRID_TARIFFS,
                    CONF_BATTERY_TARIFFS,
                    CONF_CURRENCY,
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
                "energy_entity_id": str(raw.get("energy_entity_id") or "").strip() or None,
                "energy_mode": (
                    str(raw.get("energy_mode") or ENERGY_MODE_AUTO)
                    if str(raw.get("energy_mode") or ENERGY_MODE_AUTO) in ENERGY_MODES
                    else ENERGY_MODE_AUTO
                ),
                "tariffs": normalize_tariffs(raw.get("tariffs")),
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
        polarity = str(raw.get("polarity") or GENERATOR_POLARITY_POSITIVE)
        if polarity not in GENERATOR_POLARITIES:
            polarity = GENERATOR_POLARITY_POSITIVE
        fallback_polarity = str(
            raw.get("fallback_polarity") or GENERATOR_FALLBACK_POLARITY_SAME
        )
        if fallback_polarity not in GENERATOR_FALLBACK_POLARITIES:
            fallback_polarity = GENERATOR_FALLBACK_POLARITY_SAME
        result.append(
            {
                "id": gid,
                "entity_id": entity_id,
                "fallback_entity_id": str(raw.get("fallback_entity_id") or "").strip() or None,
                "polarity": polarity,
                "fallback_polarity": fallback_polarity,
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
                "energy_entity_id": str(raw.get("energy_entity_id") or "").strip() or None,
                "energy_mode": (
                    str(raw.get("energy_mode") or ENERGY_MODE_AUTO)
                    if str(raw.get("energy_mode") or ENERGY_MODE_AUTO) in ENERGY_MODES
                    else ENERGY_MODE_AUTO
                ),
                "tariffs": normalize_tariffs(raw.get("tariffs")),
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
    energy_entities = [
        str(x.get("energy_entity_id") or "")
        for x in consumers
        if x.get("enabled", True) and x.get("energy_entity_id")
    ]
    if len(energy_entities) != len(set(energy_entities)):
        connection.send_error(msg["id"], "consumer_energy_duplicate", "Energy counter assigned to multiple consumers")
        return
    if overlap := set(energy_entities) & active_consumer_entities:
        connection.send_error(msg["id"], "consumer_energy_power_duplicate", ", ".join(sorted(overlap)))
        return
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
    generator_energy_entities = [
        str(item.get("energy_entity_id") or "")
        for item in generators
        if item.get("enabled", True) and item.get("energy_entity_id")
    ]
    if len(generator_energy_entities) != len(set(generator_energy_entities)):
        connection.send_error(msg["id"], "generator_energy_duplicate", "PV energy counter assigned to multiple generators")
        return
    if overlap := generator_entities & active_consumer_entities:
        connection.send_error(msg["id"], "generator_consumer_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := generator_entities & backgrounds:
        connection.send_error(msg["id"], "generator_background_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(energy_entities) & generator_entities:
        connection.send_error(msg["id"], "consumer_energy_generator_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(generator_energy_entities) & generator_entities:
        connection.send_error(msg["id"], "generator_energy_power_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(generator_energy_entities) & active_consumer_entities:
        connection.send_error(msg["id"], "generator_energy_consumer_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(generator_energy_entities) & set(energy_entities):
        connection.send_error(msg["id"], "generator_consumer_energy_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(energy_entities) & backgrounds:
        connection.send_error(msg["id"], "consumer_energy_background_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(generator_energy_entities) & backgrounds:
        connection.send_error(msg["id"], "generator_energy_background_duplicate", ", ".join(sorted(overlap)))
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
    if overlap := set(energy_entities) & grid_entities:
        connection.send_error(msg["id"], "consumer_energy_grid_duplicate", ", ".join(sorted(overlap)))
        return
    if overlap := set(generator_energy_entities) & grid_entities:
        connection.send_error(msg["id"], "generator_energy_grid_duplicate", ", ".join(sorted(overlap)))
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


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/storage/status"})
@websocket_api.async_response
async def ws_storage_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return lightweight storage/statistics diagnostics for the dashboard."""
    controller = _controller(hass)
    if controller is None:
        connection.send_error(msg["id"], "not_loaded", "WattWer is not loaded")
        return

    archive = _archive(controller)
    runtime_path = hass.config.path(".storage", f"{DOMAIN}.{controller.entry.entry_id}")
    backfill_path = hass.config.path(".storage", f"{DOMAIN}.backfill.{controller.entry.entry_id}")

    def _size_sync(path: str) -> int:
        try:
            return max(0, int(os.path.getsize(path)))
        except OSError:
            return 0

    def _edge(records: dict[str, Any], newest: bool = False) -> int | None:
        if not records:
            return None
        try:
            values = [int(key) for key in records]
        except (TypeError, ValueError):
            return None
        return max(values) if newest else min(values)

    consumer_count = len(controller.consumer_labels)
    active_consumer_count = len(controller.consumers)
    source_count = 4 if controller.battery_visible else 3
    share_count = source_count - 1
    # Mirrors sensor.py: two energy sensors per source, one share sensor for
    # each non-total source, plus four integration-wide diagnostic sensors.
    entity_count = consumer_count * (2 * source_count + share_count) + 4
    # Long-term statistics are produced by lifetime energy sensors plus the
    # monotonically increasing lifetime coverage sensor.
    lts_series_count = consumer_count * source_count + 1

    runtime_bytes = await hass.async_add_executor_job(_size_sync, runtime_path)
    backfill_bytes = await hass.async_add_executor_job(_size_sync, backfill_path)
    periodic_saves_per_day = math.ceil(86400 / max(1, STORAGE_SAVE_INTERVAL))
    quarter_saves_per_day = 96
    max_runtime_saves_per_day = periodic_saves_per_day + quarter_saves_per_day

    try:
        recorder_keep_days = int(get_recorder_instance(hass).keep_days)
    except Exception:  # pragma: no cover - recorder may be unavailable during startup
        recorder_keep_days = None

    records = archive.records
    connection.send_result(
        msg["id"],
        {
            "runtime_storage_bytes": runtime_bytes,
            "backfill_storage_bytes": backfill_bytes,
            "total_storage_bytes": runtime_bytes + backfill_bytes,
            "storage_save_interval_seconds": STORAGE_SAVE_INTERVAL,
            "periodic_saves_per_day": periodic_saves_per_day,
            "quarter_saves_per_day": quarter_saves_per_day,
            "max_runtime_saves_per_day": max_runtime_saves_per_day,
            "estimated_runtime_write_bytes_per_day_upper": runtime_bytes * max_runtime_saves_per_day,
            "consumer_count": consumer_count,
            "active_consumer_count": active_consumer_count,
            "generator_count": len(controller.all_generators),
            "active_generator_count": len(controller.generators),
            "group_count": len(controller.groups),
            "entity_count": entity_count,
            "lts_series_count": lts_series_count,
            "recorder_keep_days": recorder_keep_days,
            "quarter_retention_days": controller.q_retention_days,
            "hour_retention_days": controller.h_retention_days,
            "backfill": {
                "counts": {resolution: len(values) for resolution, values in records.items()},
                "oldest": {resolution: _edge(values) for resolution, values in records.items()},
                "newest": {resolution: _edge(values, True) for resolution, values in records.items()},
                "revision_count": len(archive.config_revisions),
            },
            "policy": {
                "periodic_minutes": STORAGE_SAVE_INTERVAL / 60,
                "save_on_quarter_close": True,
                "save_on_shutdown": True,
                "five_second_samples_persisted": False,
            },
        },
    )


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
    settings[CONF_GRID_TARIFFS] = normalize_tariffs(raw.get(CONF_GRID_TARIFFS))
    settings[CONF_BATTERY_TARIFFS] = normalize_tariffs(raw.get(CONF_BATTERY_TARIFFS))
    settings[CONF_CURRENCY] = str(raw.get(CONF_CURRENCY) or DEFAULTS[CONF_CURRENCY]).strip().upper() or "EUR"
    if len(settings[CONF_CURRENCY]) > 8:
        return None, "invalid_currency"
    try:
        settings[CONF_SAMPLE_INTERVAL] = int(raw.get(CONF_SAMPLE_INTERVAL, DEFAULTS[CONF_SAMPLE_INTERVAL]))
        settings[CONF_MAX_AGE] = float(raw.get(CONF_MAX_AGE, DEFAULTS[CONF_MAX_AGE]))
        settings[CONF_DEADBAND] = float(raw.get(CONF_DEADBAND, DEFAULTS[CONF_DEADBAND]))
        settings[CONF_QUARTER_RETENTION_DAYS] = int(raw.get(CONF_QUARTER_RETENTION_DAYS, DEFAULTS[CONF_QUARTER_RETENTION_DAYS]))
        settings[CONF_HOUR_RETENTION_DAYS] = int(raw.get(CONF_HOUR_RETENTION_DAYS, DEFAULTS[CONF_HOUR_RETENTION_DAYS]))
        settings[CONF_SYNC_ENABLED] = bool(raw.get(CONF_SYNC_ENABLED, DEFAULTS[CONF_SYNC_ENABLED]))
        settings[CONF_SYNC_DELAY] = float(raw.get(CONF_SYNC_DELAY, DEFAULTS[CONF_SYNC_DELAY]))
        settings[CONF_SYNC_BUFFER] = float(raw.get(CONF_SYNC_BUFFER, DEFAULTS[CONF_SYNC_BUFFER]))
        settings[CONF_SYNC_MAX_SAMPLE_AGE] = float(raw.get(CONF_SYNC_MAX_SAMPLE_AGE, DEFAULTS[CONF_SYNC_MAX_SAMPLE_AGE]))
        settings[CONF_ADAPTIVE_FRESHNESS] = bool(raw.get(CONF_ADAPTIVE_FRESHNESS, DEFAULTS[CONF_ADAPTIVE_FRESHNESS]))
        settings[CONF_ADAPTIVE_HARD_TIMEOUT] = float(raw.get(CONF_ADAPTIVE_HARD_TIMEOUT, DEFAULTS[CONF_ADAPTIVE_HARD_TIMEOUT]))
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
    if not 0 <= settings[CONF_SYNC_DELAY] <= 30:
        return None, "invalid_sync_delay"
    if not 10 <= settings[CONF_SYNC_BUFFER] <= 300:
        return None, "invalid_sync_buffer"
    if not 2 <= settings[CONF_SYNC_MAX_SAMPLE_AGE] <= 120:
        return None, "invalid_sync_max_sample_age"
    if not 15 <= settings[CONF_ADAPTIVE_HARD_TIMEOUT] <= 600:
        return None, "invalid_adaptive_hard_timeout"
    if (
        settings[CONF_SYNC_ENABLED]
        and not settings[CONF_ADAPTIVE_FRESHNESS]
        and settings[CONF_SYNC_BUFFER] < settings[CONF_SYNC_DELAY] + settings[CONF_SYNC_MAX_SAMPLE_AGE]
    ):
        return None, "sync_buffer_too_small"
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
