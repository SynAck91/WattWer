"""Backfill archive and historical reconstruction from Recorder raw state history."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import partial
import logging
import math
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BACKFILL_STORAGE_VERSION,
    DOMAIN,
    MAX_BACKFILL_DAYS_PER_RUN,
    SOURCES,
)
from .controller import PVAllocationController

_LOGGER = logging.getLogger(__name__)


def _empty_values(consumer_ids) -> dict[str, dict[str, float]]:
    return {cid: {source: 0.0 for source in SOURCES} for cid in consumer_ids}


def _empty_record(start_ms: int, duration: int, consumer_ids) -> dict[str, Any]:
    return {
        "start": int(start_ms),
        "duration": int(duration),
        "coverage": 0.0,
        "values": _empty_values(consumer_ids),
        "backfill": True,
        "freshness_reconstructable": False,
    }


def _state_ts(state: Any) -> float | None:
    dt = getattr(state, "last_updated", None) or getattr(state, "last_changed", None)
    if dt is None:
        return None
    return dt_util.as_utc(dt).timestamp()


def _state_float(state: Any) -> float | None:
    try:
        value = float(state.state)
    except (TypeError, ValueError, AttributeError):
        return None
    return value if math.isfinite(value) else None


class BackfillArchive:
    """Small aggregate archive for pre-installation reconstructed history.

    Live data keeps using native entities/Recorder/LTS. Only historical data that
    predates the integration is stored here, already reduced to 15m/hour/day.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store[dict[str, Any]](
            hass,
            BACKFILL_STORAGE_VERSION,
            f"{DOMAIN}.backfill.{entry_id}",
        )
        self.records: dict[str, dict[str, dict[str, Any]]] = {
            "15m": {},
            "hour": {},
            "day": {},
        }
        self.last_status: dict[str, Any] | None = None
        self.config_revisions: list[dict[str, Any]] = []

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if not isinstance(raw, dict):
            return
        for resolution in self.records:
            records = raw.get("records", {}).get(resolution, {})
            if isinstance(records, dict):
                self.records[resolution] = records
        if isinstance(raw.get("last_status"), dict):
            self.last_status = raw["last_status"]
        if isinstance(raw.get("config_revisions"), list):
            self.config_revisions = raw["config_revisions"]

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "records": self.records,
                "last_status": self.last_status,
                "config_revisions": self.config_revisions[-100:],
            }
        )

    async def async_remove(self) -> None:
        await self._store.async_remove()

    async def async_record_revision(self, cfg: dict[str, Any]) -> None:
        """Persist a configuration revision for auditability of later edits."""
        stamp = int(datetime.now(UTC).timestamp() * 1000)
        snapshot = {
            "effective_from": stamp,
            "consumers": deepcopy(cfg.get("consumers", [])),
            "groups": deepcopy(cfg.get("groups", [])),
            "generators": deepcopy(cfg.get("generators", [])),
        }
        if (
            self.config_revisions
            and self.config_revisions[-1].get("consumers") == snapshot["consumers"]
            and self.config_revisions[-1].get("groups") == snapshot["groups"]
            and self.config_revisions[-1].get("generators", []) == snapshot["generators"]
        ):
            return
        self.config_revisions.append(snapshot)
        await self.async_save()

    async def async_upsert(self, resolution: str, records: list[dict[str, Any]]) -> None:
        target = self.records[resolution]
        for record in records:
            target[str(int(record["start"]))] = deepcopy(record)
        self._prune()
        await self.async_save()

    def _prune(self) -> None:
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        q_cutoff = now_ms - 31 * 86400 * 1000
        # Exact quarter-hours are useful for recent backfills, but the requested
        # long-term policy is hourly for two years and daily thereafter.
        self.records["15m"] = {
            key: rec for key, rec in self.records["15m"].items() if int(key) >= q_cutoff
        }
        h_cutoff = now_ms - 730 * 86400 * 1000
        self.records["hour"] = {
            key: rec for key, rec in self.records["hour"].items() if int(key) >= h_cutoff
        }

    def get_records(self, resolution: str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
        return [
            deepcopy(rec)
            for key, rec in sorted(self.records.get(resolution, {}).items(), key=lambda x: int(x[0]))
            if start_ms <= int(key) < end_ms
        ]

    def status(self) -> dict[str, Any]:
        return {
            "last": deepcopy(self.last_status),
            "counts": {resolution: len(records) for resolution, records in self.records.items()},
            "revision_count": len(self.config_revisions),
            "max_days_per_run": MAX_BACKFILL_DAYS_PER_RUN,
        }


def _aggregate_fixed(
    records: list[dict[str, Any]],
    consumer_ids,
    resolution: str,
    controller: PVAllocationController,
) -> list[dict[str, Any]]:
    grouped: dict[int, dict[str, Any]] = {}
    for record in records:
        start_ms = int(record["start"])
        ts = start_ms / 1000
        if resolution == "hour":
            bucket_start = int(math.floor(ts / 3600.0) * 3600 * 1000)
            duration = 3600
        else:
            bucket_start = int(controller._day_start(ts) * 1000)  # same local-day rule as live
            next_start = controller._next_day_start(bucket_start / 1000)
            duration = int(round(next_start - bucket_start / 1000))
        out = grouped.setdefault(bucket_start, _empty_record(bucket_start, duration, consumer_ids))
        covered_seconds = float(record.get("coverage", 0.0)) * float(record.get("duration", 0))
        out.setdefault("_covered", 0.0)
        out["_covered"] += covered_seconds
        for cid in consumer_ids:
            for source in SOURCES:
                out["values"][cid][source] += float(record.get("values", {}).get(cid, {}).get(source, 0.0))
    result = []
    for key in sorted(grouped):
        rec = grouped[key]
        covered = float(rec.pop("_covered", 0.0))
        rec["coverage"] = min(max(covered / max(1, rec["duration"]), 0.0), 1.0)
        result.append(rec)
    return result


async def _async_raw_states(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_dt: datetime,
    end_dt: datetime,
) -> dict[str, list[Any]]:
    query = partial(
        get_significant_states,
        hass,
        start_dt,
        end_dt,
        entity_ids=entity_ids,
        include_start_time_state=True,
        significant_changes_only=False,
        minimal_response=False,
        no_attributes=True,
    )
    return await get_instance(hass).async_add_executor_job(query)


async def async_run_backfill(
    hass: HomeAssistant,
    controller: PVAllocationController,
    archive: BackfillArchive,
    start_ms: int,
    end_ms: int,
) -> dict[str, Any]:
    """Reconstruct pre-installation energy from Recorder raw power states."""
    if end_ms <= start_ms:
        raise ValueError("invalid_range")
    span_days = (end_ms - start_ms) / 86_400_000
    if span_days > MAX_BACKFILL_DAYS_PER_RUN + 0.01:
        raise ValueError("range_too_large")

    # Never backfill the currently-running quarter. This prevents overlap with
    # live integration and makes repeated backfill runs idempotent by key.
    current_q_ms = int(controller._quarter_start(datetime.now(UTC).timestamp()) * 1000)
    end_ms = min(end_ms, current_q_ms)
    if end_ms <= start_ms:
        raise ValueError("range_not_in_past")

    entity_ids = controller.required_history_entities()
    if not entity_ids:
        raise ValueError("no_entities")

    consumer_ids = list(controller.all_consumers)
    all_quarters: list[dict[str, Any]] = []
    raw_counts = {eid: 0 for eid in entity_ids}

    cursor_dt = datetime.fromtimestamp(start_ms / 1000, UTC)
    end_dt_all = datetime.fromtimestamp(end_ms / 1000, UTC)
    sample = max(2, int(controller.sample_interval))

    while cursor_dt < end_dt_all:
        chunk_end = min(cursor_dt + timedelta(days=1), end_dt_all)
        states_by_entity = await _async_raw_states(hass, entity_ids, cursor_dt, chunk_end)

        series: dict[str, list[tuple[float, float]]] = {}
        for eid in entity_ids:
            rows: list[tuple[float, float]] = []
            for state in states_by_entity.get(eid, []):
                ts = _state_ts(state)
                value = _state_float(state)
                if ts is None or value is None:
                    continue
                rows.append((ts, value))
            rows.sort(key=lambda x: x[0])
            series[eid] = rows
            raw_counts[eid] += len(rows)

        pointers = {eid: -1 for eid in entity_ids}
        current: dict[str, float] = {}
        chunk_start_ts = cursor_dt.timestamp()
        chunk_end_ts = chunk_end.timestamp()
        # First sample is aligned to the configured live sampling cadence.
        t = math.ceil(chunk_start_ts / sample) * sample
        quarter_records: dict[int, dict[str, Any]] = {}

        while t < chunk_end_ts - 1e-9:
            for eid in entity_ids:
                rows = series[eid]
                idx = pointers[eid]
                while idx + 1 < len(rows) and rows[idx + 1][0] <= t + 1e-9:
                    idx += 1
                    current[eid] = rows[idx][1]
                pointers[eid] = idx

            dt_s = min(float(sample), chunk_end_ts - t)
            allocation, _diag = controller.allocation_from_entity_values(current)
            q_start_ms = int(controller._quarter_start(t) * 1000)
            rec = quarter_records.setdefault(q_start_ms, _empty_record(q_start_ms, 900, consumer_ids))
            if allocation is not None and dt_s > 0:
                rec.setdefault("_covered", 0.0)
                rec["_covered"] += dt_s
                for cid in consumer_ids:
                    for source in SOURCES:
                        rec["values"][cid][source] += float(allocation[cid][source]) * dt_s / 3_600_000.0
            t += sample

        for key in sorted(quarter_records):
            rec = quarter_records[key]
            rec["coverage"] = min(max(float(rec.pop("_covered", 0.0)) / 900.0, 0.0), 1.0)
            all_quarters.append(rec)
        cursor_dt = chunk_end

    if not all_quarters:
        raise ValueError("no_history")

    hours = _aggregate_fixed(all_quarters, consumer_ids, "hour", controller)
    days = _aggregate_fixed(all_quarters, consumer_ids, "day", controller)
    await archive.async_upsert("15m", all_quarters)
    await archive.async_upsert("hour", hours)
    await archive.async_upsert("day", days)

    total_duration = sum(float(x["duration"]) for x in all_quarters)
    total_covered = sum(float(x["duration"]) * float(x["coverage"]) for x in all_quarters)
    status = {
        "start": start_ms,
        "end": end_ms,
        "completed_at": int(datetime.now(UTC).timestamp() * 1000),
        "quarters": len(all_quarters),
        "hours": len(hours),
        "days": len(days),
        "coverage": total_covered / total_duration if total_duration else 0.0,
        "raw_state_counts": raw_counts,
        "freshness_reconstructable": False,
        "note": "Recorder does not preserve proof of repeated identical reports; historical freshness cannot be reconstructed exactly.",
    }
    archive.last_status = status
    await archive.async_save()
    return status
