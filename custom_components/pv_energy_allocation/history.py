"""Recorder-backed history for the PV Energy Allocation dashboard."""
from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SOURCES
from .controller import PVAllocationController
from .backfill import BackfillArchive


def _entity_id(hass: HomeAssistant, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id)


def _energy_unique(entry_id: str, cid: str, source: str, suffix: str) -> str:
    return f"{entry_id}_{cid}_{source}_energy_{suffix}"


def _empty_record(start_ms: int, duration: int, consumer_ids) -> dict[str, Any]:
    return {
        "start": start_ms,
        "duration": duration,
        "coverage": 0.0,
        "values": {
            cid: {source: 0.0 for source in SOURCES}
            for cid in consumer_ids
        },
    }


async def async_get_history(
    hass: HomeAssistant,
    controller: PVAllocationController,
    archive: BackfillArchive,
    start_ms: int,
    end_ms: int,
    resolution: str,
) -> dict[str, Any]:
    """Get recent quarter-hours from Recorder and long range from LTS."""
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    span_ms = max(0, end_ms - start_ms)
    requested_auto = resolution == "auto"

    if requested_auto:
        q_cutoff = now_ms - controller.q_retention_days * 86400 * 1000
        h_cutoff = now_ms - controller.h_retention_days * 86400 * 1000
        if start_ms >= q_cutoff and span_ms <= 7 * 86400 * 1000:
            resolution = "15m"
        elif start_ms >= h_cutoff and span_ms <= 90 * 86400 * 1000:
            resolution = "hour"
        else:
            resolution = "day"

    if resolution == "15m":
        records = await _async_recent_quarters(hass, controller, start_ms, end_ms)
        if requested_auto and not records and start_ms < now_ms - 86400 * 1000:
            resolution = "hour"
            records = await _async_statistics(hass, controller, start_ms, end_ms, "hour")
    elif resolution == "day":
        records = await _async_statistics(hass, controller, start_ms, end_ms, "day")
    else:
        resolution = "hour"
        records = await _async_statistics(hass, controller, start_ms, end_ms, "hour")

    archived = archive.get_records(resolution, start_ms, end_ms)
    if archived:
        merged = {int(rec["start"]): rec for rec in archived}
        # For overlapping intervals prefer the record with the better data
        # coverage. This matters after a degraded/invalid live interval: native
        # quarter sensors may legitimately contain a 0 kWh / 0 % coverage row,
        # while a later Recorder backfill can reconstruct the same interval with
        # much better coverage. Native data still wins when coverage is equal or
        # better, so verified live measurements remain authoritative.
        for rec in records:
            key = int(rec["start"])
            existing = merged.get(key)
            native_coverage = float(rec.get("coverage", 0.0) or 0.0)
            archived_coverage = (
                float(existing.get("coverage", 0.0) or 0.0)
                if existing is not None
                else -1.0
            )
            if existing is None or native_coverage >= archived_coverage:
                merged[key] = rec
        records = [merged[key] for key in sorted(merged)]

    return {
        "resolution": resolution,
        "records": records,
        "consumers": controller.consumer_labels,
        "consumer_metadata": controller.consumer_metadata,
        "groups": controller.groups,
        "battery_enabled": controller.battery_enabled,
        "battery_visible": controller.battery_visible,
        "policy": {
            "quarter_auto_days": controller.q_retention_days,
            "hour_auto_days": controller.h_retention_days,
            "note": "15-minute data uses Recorder state history; hour/day use Long-Term Statistics.",
        },
    }


async def _async_recent_quarters(
    hass: HomeAssistant,
    controller: PVAllocationController,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    mapping: dict[str, tuple[str, str]] = {}
    sources = ["total", "pv", "grid"] + (["battery"] if controller.battery_visible else [])
    for cid in controller.all_consumers:
        for source in sources:
            uid = _energy_unique(controller.entry.entry_id, cid, source, "last_15m")
            if eid := _entity_id(hass, uid):
                mapping[eid] = (cid, source)
    if not mapping:
        return []

    start_dt = datetime.fromtimestamp(start_ms / 1000, UTC)
    end_dt = datetime.fromtimestamp(end_ms / 1000, UTC)
    query = partial(
        get_significant_states,
        hass,
        start_dt,
        end_dt,
        entity_ids=list(mapping),
        include_start_time_state=False,
        significant_changes_only=False,
        minimal_response=False,
        no_attributes=False,
    )
    states_by_entity = await get_instance(hass).async_add_executor_job(query)

    grouped: dict[int, dict[str, Any]] = {}
    for eid, states in states_by_entity.items():
        target = mapping.get(eid)
        if target is None:
            continue
        cid, source = target
        for state in states:
            if not isinstance(state, State):
                # LazyState implements the same properties but is not guaranteed
                # to be an actual State instance across HA releases.
                pass
            try:
                value = float(state.state)
                window_start = int(state.attributes.get("fenster_start_ms"))
                window_end = int(state.attributes.get("fenster_ende_ms"))
            except (TypeError, ValueError, AttributeError):
                continue
            if window_start < start_ms or window_start >= end_ms:
                continue
            duration = max(1, int(round((window_end - window_start) / 1000)))
            rec = grouped.setdefault(window_start, _empty_record(window_start, duration, controller.all_consumers))
            rec["values"][cid][source] = max(0.0, value)
            try:
                rec["coverage"] = max(
                    rec["coverage"],
                    min(max(float(state.attributes.get("datenabdeckung_prozent", 0)) / 100.0, 0.0), 1.0),
                )
            except (TypeError, ValueError):
                pass

    return [grouped[key] for key in sorted(grouped)]


async def _async_statistics(
    hass: HomeAssistant,
    controller: PVAllocationController,
    start_ms: int,
    end_ms: int,
    period: str,
) -> list[dict[str, Any]]:
    mapping: dict[str, tuple[str, str]] = {}
    sources = ["total", "pv", "grid"] + (["battery"] if controller.battery_visible else [])
    for cid in controller.all_consumers:
        for source in sources:
            uid = _energy_unique(controller.entry.entry_id, cid, source, "lifetime")
            if eid := _entity_id(hass, uid):
                mapping[eid] = (cid, source)

    coverage_eid = _entity_id(hass, f"{controller.entry.entry_id}_coverage_lifetime")
    statistic_ids = set(mapping)
    if coverage_eid:
        statistic_ids.add(coverage_eid)
    if not statistic_ids:
        return []

    start_dt = datetime.fromtimestamp(start_ms / 1000, UTC)
    end_dt = datetime.fromtimestamp(end_ms / 1000, UTC)
    result = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start_dt,
        end_dt,
        statistic_ids,
        period,
        None,
        {"change"},
    )

    grouped: dict[int, dict[str, Any]] = {}
    for eid, rows in result.items():
        for row in rows:
            row_start = int(round(float(row["start"]) * 1000))
            row_end = int(round(float(row["end"]) * 1000))
            if row_start < start_ms or row_start >= end_ms:
                continue
            duration = max(1, int(round((row_end - row_start) / 1000)))
            rec = grouped.setdefault(row_start, _empty_record(row_start, duration, controller.all_consumers))
            change = row.get("change")
            try:
                change_f = float(change) if change is not None else 0.0
            except (TypeError, ValueError):
                change_f = 0.0
            if eid == coverage_eid:
                rec["coverage"] = min(max(change_f / duration, 0.0), 1.0)
            elif eid in mapping:
                cid, source = mapping[eid]
                rec["values"][cid][source] = max(0.0, change_f)

    return [grouped[key] for key in sorted(grouped)]
