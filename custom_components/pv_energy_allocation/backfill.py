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
        "energy_meter": {},
        "generator_energy_meter": {},
        "generator_power_kwh": {},
        "pv_by_generator_kwh": {cid: {} for cid in consumer_ids},
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
            for gid, value in (record.get("pv_by_generator_kwh", {}).get(cid, {}) or {}).items():
                out.setdefault("pv_by_generator_kwh", {}).setdefault(cid, {})[gid] = (
                    out.setdefault("pv_by_generator_kwh", {}).setdefault(cid, {}).get(gid, 0.0) + float(value or 0.0)
                )
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


def _series_counter_at(
    rows: list[tuple[float, float]], target_ts: float
) -> float | None:
    """Return a cumulative counter at a boundary, interpolating monotonic samples."""
    previous: tuple[float, float] | None = None
    following: tuple[float, float] | None = None
    for ts, value in rows:
        if ts <= target_ts + 1e-6:
            previous = (ts, value)
        else:
            following = (ts, value)
            break
    if previous is None:
        return None
    prev_ts, prev_value = previous
    if following is not None:
        next_ts, next_value = following
        gap = next_ts - prev_ts
        if gap > 1e-6 and next_value >= prev_value and prev_ts <= target_ts <= next_ts:
            ratio = (target_ts - prev_ts) / gap
            return prev_value + (next_value - prev_value) * ratio
    return prev_value


def _calibrate_backfill_record(
    controller: PVAllocationController,
    record: dict[str, Any],
    series: dict[str, list[tuple[float, float]]],
) -> None:
    """Apply the same optional energy-meter calibration used by live quarters."""
    start_ts = float(record["start"]) / 1000.0
    end_ts = start_ts + float(record.get("duration", 900))
    meter_diag: dict[str, Any] = {}
    for cid, consumer in controller.energy_consumers.items():
        if not controller._energy_meter_eligible(cid):
            continue
        entity_id = str(consumer.get("energy_entity_id") or "")
        rows = series.get(entity_id, [])
        start_value = _series_counter_at(rows, start_ts)
        end_value = _series_counter_at(rows, end_ts)
        values = record.get("values", {}).get(cid, {})
        power_total = max(0.0, float(values.get("total", 0.0)))
        diag = {
            "entity_id": entity_id,
            "mode": consumer.get("energy_mode", "auto"),
            "status": "power_fallback",
            "power_integrated_kwh": power_total,
            "meter_delta_kwh": None,
            "deviation_percent": None,
        }
        if start_value is None or end_value is None:
            diag["reason"] = "counter_history_missing"
            meter_diag[cid] = diag
            continue
        delta = end_value - start_value
        if not math.isfinite(delta) or delta < -1e-9:
            diag["reason"] = "counter_reset_or_backward"
            meter_diag[cid] = diag
            continue
        delta = max(0.0, delta)
        diag["meter_delta_kwh"] = delta
        if power_total > 1e-9:
            diag["deviation_percent"] = (delta - power_total) / power_total * 100.0
        if delta <= 1e-9 and power_total >= 0.002:
            diag["reason"] = "counter_not_advanced"
            meter_diag[cid] = diag
            continue
        if (
            str(consumer.get("energy_mode") or "auto") == "auto"
            and power_total >= 0.01
            and delta > 0
            and not (0.2 <= delta / power_total <= 5.0)
        ):
            diag["reason"] = "counter_delta_implausible"
            meter_diag[cid] = diag
            continue
        source_sum = sum(max(0.0, float(values.get(src, 0.0))) for src in ("pv", "grid", "battery"))
        if delta > 1e-9 and source_sum <= 1e-12:
            diag["reason"] = "source_mix_unavailable"
            meter_diag[cid] = diag
            continue
        old_pv = max(0.0, float(values.get("pv", 0.0)))
        if source_sum <= 1e-12:
            record["values"][cid] = {"total": 0.0, "pv": 0.0, "grid": 0.0, "battery": 0.0}
        else:
            record["values"][cid] = {
                "total": delta,
                "pv": delta * max(0.0, float(values.get("pv", 0.0))) / source_sum,
                "grid": delta * max(0.0, float(values.get("grid", 0.0))) / source_sum,
                "battery": delta * max(0.0, float(values.get("battery", 0.0))) / source_sum,
            }
        new_pv = max(0.0, float(record["values"][cid].get("pv", 0.0)))
        pv_factor = (new_pv / old_pv) if old_pv > 1e-12 else 0.0
        for gid, old_attr in list((record.get("pv_by_generator_kwh", {}).get(cid, {}) or {}).items()):
            record["pv_by_generator_kwh"][cid][gid] = max(0.0, float(old_attr or 0.0)) * pv_factor
        diag["status"] = "energy_meter"
        diag["reason"] = None
        meter_diag[cid] = diag
    record["energy_meter"] = meter_diag

    generator_meter_diag: dict[str, Any] = {}
    for gid, generator in controller.energy_generators.items():
        if not controller._generator_energy_meter_eligible(gid):
            continue
        entity_id = str(generator.get("energy_entity_id") or "")
        rows = series.get(entity_id, [])
        start_value = _series_counter_at(rows, start_ts)
        end_value = _series_counter_at(rows, end_ts)
        power_total = max(0.0, float(record.get("generator_power_kwh", {}).get(gid, 0.0)))
        diag = {
            "entity_id": entity_id,
            "mode": generator.get("energy_mode", "auto"),
            "status": "power_fallback",
            "power_integrated_kwh": power_total,
            "meter_delta_kwh": None,
            "effective_generation_kwh": power_total,
            "deviation_percent": None,
        }
        if start_value is None or end_value is None:
            diag["reason"] = "counter_history_missing"
            generator_meter_diag[gid] = diag
            continue
        delta = end_value - start_value
        if not math.isfinite(delta) or delta < -1e-9:
            diag["reason"] = "counter_reset_or_backward"
            generator_meter_diag[gid] = diag
            continue
        delta = max(0.0, delta)
        diag["meter_delta_kwh"] = delta
        if power_total > 1e-9:
            diag["deviation_percent"] = (delta - power_total) / power_total * 100.0
        if delta <= 1e-9 and power_total >= 0.002:
            diag["reason"] = "counter_not_advanced"
            generator_meter_diag[gid] = diag
            continue
        if (
            str(generator.get("energy_mode") or "auto") == "auto"
            and power_total >= 0.01
            and delta > 0
            and not (0.2 <= delta / power_total <= 5.0)
        ):
            diag["reason"] = "counter_delta_implausible"
            generator_meter_diag[gid] = diag
            continue
        diag["status"] = "energy_meter"
        diag["reason"] = None
        diag["effective_generation_kwh"] = delta
        generator_meter_diag[gid] = diag
    record["generator_energy_meter"] = generator_meter_diag


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
                raw_value = _state_float(state)
                if eid in controller._energy_entity_ids:
                    value = controller._energy_raw_to_kwh(eid, raw_value)
                else:
                    value = raw_value
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
                rec.setdefault("generator_power_kwh", {})
                for gid, power in (_diag.get("generator_power") or {}).items():
                    if power is not None:
                        rec["generator_power_kwh"][gid] = rec["generator_power_kwh"].get(gid, 0.0) + max(0.0, float(power)) * dt_s / 3_600_000.0
                for cid, row in (_diag.get("pv_by_generator_w") or {}).items():
                    for gid, power in (row or {}).items():
                        rec.setdefault("pv_by_generator_kwh", {}).setdefault(cid, {})[gid] = (
                            rec.setdefault("pv_by_generator_kwh", {}).setdefault(cid, {}).get(gid, 0.0)
                            + max(0.0, float(power)) * dt_s / 3_600_000.0
                        )
            t += sample

        for key in sorted(quarter_records):
            rec = quarter_records[key]
            rec["coverage"] = min(max(float(rec.pop("_covered", 0.0)) / 900.0, 0.0), 1.0)
            _calibrate_backfill_record(controller, rec, series)
            all_quarters.append(rec)
        cursor_dt = chunk_end

    if not all_quarters:
        raise ValueError("no_history")

    generated_at_ms = int(datetime.now(UTC).timestamp() * 1000)
    # A manually requested backfill is an explicit reconstruction with the
    # *current* WattWer configuration. Mark it as corrective so a repaired
    # sign/topology setting can replace an older native interval even when both
    # have the same nominal data coverage.
    for rec in all_quarters:
        rec["corrective"] = True
        rec["generated_at"] = generated_at_ms

    hours = _aggregate_fixed(all_quarters, consumer_ids, "hour", controller)
    days = _aggregate_fixed(all_quarters, consumer_ids, "day", controller)
    for rec in hours + days:
        rec["corrective"] = True
        rec["generated_at"] = generated_at_ms
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
        "note": "Recorder does not preserve proof of repeated identical reports; historical freshness cannot be reconstructed exactly. Configured cumulative energy counters are used to calibrate interval totals when their historical states are available.",
    }
    archive.last_status = status
    await archive.async_save()
    return status
