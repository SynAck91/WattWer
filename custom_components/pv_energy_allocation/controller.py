"""Sampling, allocation and persistence for PV Energy Allocation."""
from __future__ import annotations

from collections import deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
import asyncio
import logging
import math
from statistics import median
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_state_report_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CADENCE_MIN_SAMPLES,
    CADENCE_WINDOW,
    CONF_ADAPTIVE_FRESHNESS,
    CONF_ADAPTIVE_HARD_TIMEOUT,
    CONF_BACKGROUND_LOADS,
    CONF_BATTERY_CHARGE,
    CONF_BATTERY_DISCHARGE,
    CONF_DEADBAND,
    CONF_GENERATORS,
    ENERGY_MODE_AUTO,
    ENERGY_MODE_METER_PREFERRED,
    ENERGY_MODE_POWER_ONLY,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_GRID_TARIFFS,
    CONF_BATTERY_TARIFFS,
    CONF_CURRENCY,
    CONF_HOUR_RETENTION_DAYS,
    CONF_HOUSE_NET,
    CONF_MAX_AGE,
    CONF_QUARTER_RETENTION_DAYS,
    CONF_SAMPLE_INTERVAL,
    CONF_SYNC_ENABLED,
    CONF_SYNC_DELAY,
    CONF_SYNC_BUFFER,
    CONF_SYNC_MAX_SAMPLE_AGE,
    DEFAULTS,
    DOMAIN,
    GENERATOR_ROLE_DIRECT_CONSUMER,
    GENERATOR_FALLBACK_POLARITY_SAME,
    GENERATOR_POLARITY_NEGATIVE,
    GENERATOR_POLARITY_POSITIVE,
    GENERATOR_ROLE_MAIN_BUS,
    SOURCES,
    STORAGE_SAVE_INTERVAL,
    STORAGE_VERSION,
)
from .model import normalize_consumers, normalize_generators, normalize_groups
from .pricing import normalize_tariffs, tariff_price_at

_LOGGER = logging.getLogger(__name__)


def _empty_values(consumer_ids) -> dict[str, dict[str, float]]:
    return {cid: {source: 0.0 for source in SOURCES} for cid in consumer_ids}


def _new_bucket(start: float, consumer_ids, generator_ids=()) -> dict[str, Any]:
    return {
        "start": float(start),
        "coverage": 0.0,
        "values": _empty_values(consumer_ids),
        "balance_ws": 0.0,
        "house_net_error_ws": 0.0,
        "diag_coverage": 0.0,
        "sync_spread_ss": 0.0,
        "sync_max_age_ss": 0.0,
        "sync_diag_coverage": 0.0,
        "sync_spread_max_s": 0.0,
        "sync_sample_age_max_s": 0.0,
        # Baseline of optional cumulative hardware energy counters at the
        # interval start. Values are normalized to kWh.
        "energy_start": {cid: None for cid in consumer_ids},
        "energy_meter": {},
        # Optional cumulative PV-generation counters are diagnostic/calibration
        # anchors for the generator itself. They never overwrite the grid-based
        # consumer source balance, because generation also includes export and
        # battery charging.
        "generator_energy_start": {gid: None for gid in generator_ids},
        "generator_energy_meter": {},
        "generator_power_kwh": {gid: 0.0 for gid in generator_ids},
        # PV consumption attributed to each physical generator. This is kept
        # separate from aggregate PV kWh so different PV tariffs can be applied
        # without changing historical energy allocation.
        "pv_by_generator_kwh": {
            cid: {gid: 0.0 for gid in generator_ids} for cid in consumer_ids
        },
        "lifetime_committed": _empty_values(consumer_ids),
        "energy_calibration_allowed": True,
    }


def _finite_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class PVAllocationController:
    """Own the complete allocation calculation and retained time series."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.cfg = {**entry.data, **entry.options}
        self.sample_interval = int(self.cfg.get(CONF_SAMPLE_INTERVAL, DEFAULTS[CONF_SAMPLE_INTERVAL]))
        self.max_age = float(self.cfg.get(CONF_MAX_AGE, DEFAULTS[CONF_MAX_AGE]))
        self.deadband = float(self.cfg.get(CONF_DEADBAND, DEFAULTS[CONF_DEADBAND]))
        self.sync_enabled = bool(self.cfg.get(CONF_SYNC_ENABLED, DEFAULTS[CONF_SYNC_ENABLED]))
        self.sync_delay = max(0.0, float(self.cfg.get(CONF_SYNC_DELAY, DEFAULTS[CONF_SYNC_DELAY])))
        self.sync_buffer = max(10.0, float(self.cfg.get(CONF_SYNC_BUFFER, DEFAULTS[CONF_SYNC_BUFFER])))
        self.sync_max_sample_age = max(2.0, float(self.cfg.get(CONF_SYNC_MAX_SAMPLE_AGE, DEFAULTS[CONF_SYNC_MAX_SAMPLE_AGE])))
        self.adaptive_freshness = bool(self.cfg.get(CONF_ADAPTIVE_FRESHNESS, DEFAULTS[CONF_ADAPTIVE_FRESHNESS]))
        self.adaptive_hard_timeout = max(15.0, float(self.cfg.get(CONF_ADAPTIVE_HARD_TIMEOUT, DEFAULTS[CONF_ADAPTIVE_HARD_TIMEOUT])))
        self.q_retention_days = int(
            self.cfg.get(CONF_QUARTER_RETENTION_DAYS, DEFAULTS[CONF_QUARTER_RETENTION_DAYS])
        )
        self.h_retention_days = int(
            self.cfg.get(CONF_HOUR_RETENTION_DAYS, DEFAULTS[CONF_HOUR_RETENTION_DAYS])
        )
        self.battery_enabled = bool(
            self.cfg.get(CONF_BATTERY_CHARGE) and self.cfg.get(CONF_BATTERY_DISCHARGE)
        )
        self.currency = str(self.cfg.get(CONF_CURRENCY) or DEFAULTS[CONF_CURRENCY] or "EUR").strip().upper() or "EUR"
        self.grid_tariffs = normalize_tariffs(self.cfg.get(CONF_GRID_TARIFFS))
        self.battery_tariffs = normalize_tariffs(self.cfg.get(CONF_BATTERY_TARIFFS))

        # v0.3 separates stable consumer identity from source entity and display
        # name. Existing v0.1 IDs and v0.2 extra-consumer IDs are preserved by
        # normalize_consumers(), so upgrades keep their statistics continuity.
        consumer_list = normalize_consumers(self.cfg)
        self.all_consumers: dict[str, dict[str, Any]] = {
            item["id"]: item for item in consumer_list
        }
        self.consumers: dict[str, dict[str, Any]] = {
            cid: item for cid, item in self.all_consumers.items() if item.get("enabled", True)
        }
        self.energy_consumers: dict[str, dict[str, Any]] = {
            cid: item
            for cid, item in self.consumers.items()
            if item.get("energy_entity_id")
            and str(item.get("energy_mode") or ENERGY_MODE_AUTO) != ENERGY_MODE_POWER_ONLY
        }
        self._energy_entity_to_consumer: dict[str, str] = {
            str(item["energy_entity_id"]): cid
            for cid, item in self.energy_consumers.items()
            if item.get("energy_entity_id")
        }
        self.groups = normalize_groups(self.cfg, set(self.all_consumers))
        generator_list = normalize_generators(self.cfg, set(self.all_consumers))
        self.all_generators: dict[str, dict[str, Any]] = {
            item["id"]: item for item in generator_list
        }
        self.generators: dict[str, dict[str, Any]] = {
            gid: item for gid, item in self.all_generators.items() if item.get("enabled", True)
        }
        self.energy_generators: dict[str, dict[str, Any]] = {
            gid: item
            for gid, item in self.generators.items()
            if item.get("energy_entity_id")
            and str(item.get("energy_mode") or ENERGY_MODE_AUTO) != ENERGY_MODE_POWER_ONLY
        }
        self._energy_entity_to_generator: dict[str, str] = {
            str(item["energy_entity_id"]): gid
            for gid, item in self.energy_generators.items()
            if item.get("energy_entity_id")
        }
        self._energy_entity_ids: set[str] = set(self._energy_entity_to_consumer) | set(self._energy_entity_to_generator)

        # Live measurements are buffered by their Home Assistant report timestamp.
        # The allocation is calculated a few seconds behind wall-clock time and
        # uses only the latest sample at or before that target timestamp. This
        # prevents a fast SHM update from being mixed with a later Shelly update.
        self._measurement_buffer: dict[str, deque[tuple[float, float | None]]] = {}
        self._cadence_intervals: dict[str, deque[float]] = {}
        self._cadence_last_valid_report: dict[str, float] = {}
        generator_ages = [
            float(item.get("max_age", 180.0))
            for item in self.generators.values()
            if item.get("enabled", True)
        ]
        self._buffer_retention = max(
            self.sync_buffer,
            self.max_age,
            self.sync_max_sample_age,
            self.adaptive_hard_timeout,
            *(generator_ages or [0.0]),
        ) + self.sync_delay + max(5.0, float(self.sample_interval))

        self._store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}",
        )
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []
        self._save_lock = asyncio.Lock()
        self._save_task: asyncio.Task[None] | None = None
        self._dirty = False
        self._last_sample_ts: float | None = None
        self._last_allocation: dict[str, dict[str, float]] | None = None
        self._last_diag: dict[str, Any] = {
            "valid": False,
            "quality": "invalid",
            "quality_notes": [],
            "stale_entities": [],
            "balance_error_w": None,
            "house_net_error_w": None,
            "dtu_bkw_error_w": None,
            "grid_fraction": None,
            "pv_fraction": None,
            "battery_fraction": None,
            "gross_load_w": None,
            "main_bus_sink_w": None,
            "direct_bkw_fw_w": None,
            "grid_net_w": None,
            "sync_enabled": self.sync_enabled,
            "sync_delay_s": self.sync_delay,
            "sync_method": "last_reported_sample_hold" if self.sync_enabled else "current_state",
            "sync_target_ms": None,
            "sync_spread_s": None,
            "sync_max_sample_age_s": None,
            "sync_sample_count": 0,
            "sync_quality": "warming_up" if self.sync_enabled else "disabled",
            "adaptive_freshness": self.adaptive_freshness,
            "adaptive_hard_timeout_s": self.adaptive_hard_timeout,
            "sensor_timing": {},
            "delayed_entities": [],
        }

        self.lifetime = _empty_values(self.all_consumers)
        self.pv_generator_lifetime = {
            cid: {gid: 0.0 for gid in self.all_generators} for cid in self.all_consumers
        }
        self.last_15m: dict[str, Any] | None = None
        self.coverage_lifetime_s = 0.0
        now = datetime.now(UTC).timestamp() - (self.sync_delay if self.sync_enabled else 0.0)
        self.bucket_15m = _new_bucket(self._quarter_start(now), self.all_consumers, self.all_generators)
        self.bucket_hour = _new_bucket(self._hour_start(now), self.all_consumers, self.all_generators)
        self.bucket_day = _new_bucket(self._day_start(now), self.all_consumers, self.all_generators)

    @callback
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe an entity to low-frequency state updates."""
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _serialize(self) -> dict[str, Any]:
        return {
            "lifetime": deepcopy(self.lifetime),
            "pv_generator_lifetime": deepcopy(self.pv_generator_lifetime),
            "last_15m": deepcopy(self.last_15m),
            "coverage_lifetime_s": self.coverage_lifetime_s,
            "bucket_15m": deepcopy(self.bucket_15m),
            "bucket_hour": deepcopy(self.bucket_hour),
            "bucket_day": deepcopy(self.bucket_day),
            "last_sample_ts": self._last_sample_ts,
            "cadence_intervals": {eid: list(values) for eid, values in self._cadence_intervals.items()},
            "accounting_mode": "quarter_commit",
        }

    @callback
    def _tracked_live_entities(self) -> list[str]:
        """Return entities whose reports are buffered for synchronized live sampling."""
        ids = self.required_history_entities()
        house_net = str(self.cfg.get(CONF_HOUSE_NET) or "").strip()
        if house_net:
            ids.append(house_net)
        return list(dict.fromkeys(x for x in ids if x))

    def _generator_hard_timeout_for_entity(self, entity_id: str | None) -> float | None:
        """Return a configured PV-generator timeout for a primary/fallback entity."""
        if not entity_id:
            return None
        for generator in self.generators.values():
            if entity_id in {
                str(generator.get("entity_id") or ""),
                str(generator.get("fallback_entity_id") or ""),
                str(generator.get("energy_entity_id") or ""),
            }:
                try:
                    return max(5.0, float(generator.get("max_age", 180.0)))
                except (TypeError, ValueError):
                    return 180.0
        return None

    def _hard_timeout_for_entity(
        self, entity_id: str | None, *, explicit_max_age: float | None = None
    ) -> float:
        """Return the absolute safety timeout for one sensor."""
        if explicit_max_age is not None:
            return max(5.0, float(explicit_max_age))
        generator_timeout = self._generator_hard_timeout_for_entity(entity_id)
        if generator_timeout is not None:
            return generator_timeout
        return self.adaptive_hard_timeout

    def _cadence_profile(
        self, entity_id: str | None, *, explicit_max_age: float | None = None
    ) -> dict[str, Any]:
        """Return robust learned reporting cadence and adaptive freshness limits."""
        hard_timeout = self._hard_timeout_for_entity(
            entity_id, explicit_max_age=explicit_max_age
        )
        intervals = list(self._cadence_intervals.get(str(entity_id or ""), ()))
        learned = len(intervals) >= CADENCE_MIN_SAMPLES
        typical: float | None = None
        mad: float | None = None
        if intervals:
            typical = float(median(intervals))
            deviations = [abs(value - typical) for value in intervals]
            mad = float(median(deviations)) if deviations else 0.0

        if self.adaptive_freshness and learned and typical is not None:
            jitter = max(mad or 0.0, 0.10)
            # Learned cadence controls when WattWer warns that a sensor is late.
            # The value remains usable until the separate hard fail-safe expires.
            warn_after = max(5.0, 2.0 * typical, typical + 3.0 * jitter)
            stale_after = hard_timeout
            warn_after = min(warn_after, max(5.0, stale_after * 0.8))
        elif self.adaptive_freshness:
            # During learning, do not reject a normally slow sensor just because
            # the old fixed 10-second rule would have expired. The hard timeout
            # still guarantees a bounded fail-safe.
            stale_after = hard_timeout
            warn_after = min(max(10.0, hard_timeout * 0.5), stale_after)
        else:
            fixed = (
                float(explicit_max_age)
                if explicit_max_age is not None
                else self.sync_max_sample_age
            )
            stale_after = min(max(2.0, fixed), hard_timeout)
            warn_after = stale_after

        return {
            "entity_id": entity_id,
            "learned": learned,
            "sample_count": len(intervals),
            "typical_interval_s": typical,
            "jitter_mad_s": mad,
            "warn_after_s": warn_after,
            "stale_after_s": stale_after,
            "hard_timeout_s": hard_timeout,
        }

    def _sensor_timing_status(
        self, entity_id: str | None, age: float | None, *, explicit_max_age: float | None = None
    ) -> dict[str, Any]:
        """Return adaptive status for one sensor at the current target time."""
        profile = self._cadence_profile(entity_id, explicit_max_age=explicit_max_age)
        if age is None:
            status = "missing"
        elif age > float(profile["stale_after_s"]):
            status = "stale"
        elif not profile["learned"] and self.adaptive_freshness:
            status = "learning"
        elif age > float(profile["warn_after_s"]):
            status = "delayed"
        else:
            status = "normal"
        return {**profile, "age_s": age, "status": status}

    def _record_report_cadence(
        self, entity_id: str, ts: float, value: float | None
    ) -> None:
        """Learn the reporting interval from valid numeric reports."""
        if value is None or not entity_id:
            return
        previous = self._cadence_last_valid_report.get(entity_id)
        if previous is not None and ts > previous + 1e-3:
            interval = ts - previous
            hard_timeout = self._hard_timeout_for_entity(entity_id)
            # Ignore very long offline/night gaps so they do not teach a false
            # normal cadence. Median/MAD handle ordinary jitter and small outliers.
            if 0.05 <= interval <= max(600.0, hard_timeout * 4.0):
                queue = self._cadence_intervals.setdefault(
                    entity_id, deque(maxlen=CADENCE_WINDOW)
                )
                queue.append(float(interval))
        if previous is None or ts > previous:
            self._cadence_last_valid_report[entity_id] = ts

    def _energy_unit_factor(self, entity_id: str) -> float | None:
        """Return the current HA unit conversion factor to kWh."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        unit = str(state.attributes.get("unit_of_measurement") or "").strip().lower()
        return {
            "wh": 0.001,
            "kwh": 1.0,
            "mwh": 1000.0,
            "j": 1.0 / 3_600_000.0,
            "kj": 1.0 / 3600.0,
            "mj": 1.0 / 3.6,
        }.get(unit)

    def _energy_raw_to_kwh(self, entity_id: str, raw: float | None) -> float | None:
        """Normalize a raw cumulative energy value to kWh."""
        if raw is None:
            return None
        factor = self._energy_unit_factor(entity_id)
        if factor is None:
            return None
        return float(raw) * factor

    def _energy_state_to_kwh(self, state: State) -> float | None:
        """Normalize a cumulative energy sensor state to kWh."""
        return self._energy_raw_to_kwh(state.entity_id, _finite_float(state.state))

    def _energy_meter_eligible(self, consumer_id: str) -> bool:
        """Return whether a configured energy sensor may calibrate live data."""
        consumer = self.energy_consumers.get(consumer_id)
        if not consumer:
            return False
        mode = str(consumer.get("energy_mode") or ENERGY_MODE_AUTO)
        if mode == ENERGY_MODE_POWER_ONLY:
            return False
        if mode == ENERGY_MODE_METER_PREFERRED:
            return True
        entity_id = str(consumer.get("energy_entity_id") or "")
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        device_class = str(state.attributes.get("device_class") or "")
        state_class = str(state.attributes.get("state_class") or "")
        unit = str(state.attributes.get("unit_of_measurement") or "").strip().lower()
        return (
            device_class == "energy"
            or state_class in {"total", "total_increasing"}
            or unit in {"wh", "kwh", "mwh", "j", "kj", "mj"}
        )

    def _energy_counter_at(
        self, consumer_id: str, target_ts: float
    ) -> tuple[float | None, dict[str, Any]]:
        """Read/interpolate a consumer cumulative energy counter at a boundary.

        Cumulative energy is safe to interpolate between two monotonic samples.
        This avoids shifting a whole Shelly counter increment into the following
        quarter merely because the report arrived a few seconds after :00/:15.
        """
        consumer = self.energy_consumers.get(consumer_id)
        if not consumer or not self._energy_meter_eligible(consumer_id):
            return None, {"status": "disabled_or_unsupported"}
        entity_id = str(consumer.get("energy_entity_id") or "")
        hard = self._hard_timeout_for_entity(entity_id)
        if self.sync_enabled:
            rows = [
                (ts, value)
                for ts, value in self._measurement_buffer.get(entity_id, ())
                if value is not None
            ]
            previous: tuple[float, float] | None = None
            following: tuple[float, float] | None = None
            for ts, value in rows:
                if ts <= target_ts + 1e-6:
                    previous = (ts, float(value))
                elif following is None:
                    following = (ts, float(value))
                    break
            if previous is None:
                return None, {"status": "missing", "entity_id": entity_id}
            prev_ts, prev_value = previous
            age = max(0.0, target_ts - prev_ts)
            if age > hard:
                return None, {"status": "stale", "entity_id": entity_id, "age_s": age}
            # Interpolate only across a monotonic, reasonably short interval.
            if following is not None:
                next_ts, next_value = following
                gap = next_ts - prev_ts
                if (
                    gap > 1e-6
                    and gap <= max(hard * 2.0, 120.0)
                    and next_value >= prev_value
                    and prev_ts <= target_ts <= next_ts
                ):
                    ratio = (target_ts - prev_ts) / gap
                    value = prev_value + (next_value - prev_value) * ratio
                    return value, {
                        "status": "interpolated",
                        "entity_id": entity_id,
                        "age_s": age,
                        "sample_gap_s": gap,
                    }
            return prev_value, {
                "status": "sample_hold",
                "entity_id": entity_id,
                "age_s": age,
            }

        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None, {"status": "missing", "entity_id": entity_id}
        value = self._energy_state_to_kwh(state)
        if value is None:
            return None, {"status": "unsupported_unit", "entity_id": entity_id}
        sample_ts = dt_util.as_utc(state.last_reported).timestamp()
        age = max(0.0, target_ts - sample_ts)
        if age > hard:
            return None, {"status": "stale", "entity_id": entity_id, "age_s": age}
        return value, {"status": "sample_hold", "entity_id": entity_id, "age_s": age}

    def _generator_energy_meter_eligible(self, generator_id: str) -> bool:
        """Return whether an optional PV cumulative-energy meter is usable."""
        generator = self.energy_generators.get(generator_id)
        if not generator:
            return False
        mode = str(generator.get("energy_mode") or ENERGY_MODE_AUTO)
        if mode == ENERGY_MODE_POWER_ONLY:
            return False
        if mode == ENERGY_MODE_METER_PREFERRED:
            return True
        entity_id = str(generator.get("energy_entity_id") or "")
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        device_class = str(state.attributes.get("device_class") or "")
        state_class = str(state.attributes.get("state_class") or "")
        unit = str(state.attributes.get("unit_of_measurement") or "").strip().lower()
        return (
            device_class == "energy"
            or state_class in {"total", "total_increasing"}
            or unit in {"wh", "kwh", "mwh", "j", "kj", "mj"}
        )

    def _generator_energy_counter_at(
        self, generator_id: str, target_ts: float
    ) -> tuple[float | None, dict[str, Any]]:
        """Read/interpolate one PV generator's cumulative energy counter."""
        generator = self.energy_generators.get(generator_id)
        if not generator or not self._generator_energy_meter_eligible(generator_id):
            return None, {"status": "disabled_or_unsupported"}
        entity_id = str(generator.get("energy_entity_id") or "")
        hard = self._hard_timeout_for_entity(entity_id)
        if self.sync_enabled:
            rows = [
                (ts, value)
                for ts, value in self._measurement_buffer.get(entity_id, ())
                if value is not None
            ]
            previous: tuple[float, float] | None = None
            following: tuple[float, float] | None = None
            for ts, value in rows:
                if ts <= target_ts + 1e-6:
                    previous = (ts, float(value))
                elif following is None:
                    following = (ts, float(value))
                    break
            if previous is None:
                return None, {"status": "missing", "entity_id": entity_id}
            prev_ts, prev_value = previous
            age = max(0.0, target_ts - prev_ts)
            if age > hard:
                return None, {"status": "stale", "entity_id": entity_id, "age_s": age}
            if following is not None:
                next_ts, next_value = following
                gap = next_ts - prev_ts
                if (
                    gap > 1e-6
                    and gap <= max(hard * 2.0, 120.0)
                    and next_value >= prev_value
                    and prev_ts <= target_ts <= next_ts
                ):
                    ratio = (target_ts - prev_ts) / gap
                    value = prev_value + (next_value - prev_value) * ratio
                    return value, {
                        "status": "interpolated",
                        "entity_id": entity_id,
                        "age_s": age,
                        "sample_gap_s": gap,
                    }
            return prev_value, {"status": "sample_hold", "entity_id": entity_id, "age_s": age}

        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None, {"status": "missing", "entity_id": entity_id}
        value = self._energy_state_to_kwh(state)
        if value is None:
            return None, {"status": "unsupported_unit", "entity_id": entity_id}
        sample_ts = dt_util.as_utc(state.last_reported).timestamp()
        age = max(0.0, target_ts - sample_ts)
        if age > hard:
            return None, {"status": "stale", "entity_id": entity_id, "age_s": age}
        return value, {"status": "sample_hold", "entity_id": entity_id, "age_s": age}

    def _calibrate_generator_energy_meters(
        self, bucket: dict[str, Any], end_ts: float
    ) -> dict[str, float | None]:
        """Finalize optional PV generation meters for one completed quarter.

        The hardware counter calibrates the *generator's produced kWh* diagnostic.
        It deliberately does not rescale consumer PV kWh: generated energy can also
        be exported or charge a battery, while consumer source allocation is fixed
        by the grid/load balance and the time-resolved topology.
        """
        end_values: dict[str, float | None] = {gid: None for gid in self.all_generators}
        meter_diag: dict[str, Any] = {}
        for gid, generator in self.energy_generators.items():
            end_value, end_meta = self._generator_energy_counter_at(gid, end_ts)
            end_values[gid] = end_value
            start_value = bucket.get("generator_energy_start", {}).get(gid)
            power_total = max(0.0, float(bucket.get("generator_power_kwh", {}).get(gid, 0.0)))
            diag = {
                "entity_id": generator.get("energy_entity_id"),
                "mode": generator.get("energy_mode", ENERGY_MODE_AUTO),
                "status": "power_fallback",
                "power_integrated_kwh": power_total,
                "meter_delta_kwh": None,
                "effective_generation_kwh": power_total,
                "deviation_percent": None,
                "boundary_status": end_meta.get("status"),
            }
            if start_value is None or end_value is None:
                diag["reason"] = "baseline_missing" if start_value is None else "end_missing"
                meter_diag[gid] = diag
                continue
            try:
                delta = float(end_value) - float(start_value)
            except (TypeError, ValueError):
                diag["reason"] = "invalid_counter"
                meter_diag[gid] = diag
                continue
            if not math.isfinite(delta) or delta < -1e-9:
                diag["reason"] = "counter_reset_or_backward"
                meter_diag[gid] = diag
                continue
            delta = max(0.0, delta)
            diag["meter_delta_kwh"] = delta
            if power_total > 1e-9:
                diag["deviation_percent"] = (delta - power_total) / power_total * 100.0
            if delta <= 1e-9 and power_total >= 0.002:
                diag["reason"] = "counter_not_advanced"
                meter_diag[gid] = diag
                continue
            if (
                str(generator.get("energy_mode") or ENERGY_MODE_AUTO) == ENERGY_MODE_AUTO
                and power_total >= 0.01
                and delta > 0
                and not (0.2 <= delta / power_total <= 5.0)
            ):
                diag["reason"] = "counter_delta_implausible"
                meter_diag[gid] = diag
                continue
            diag["status"] = "energy_meter"
            diag["reason"] = None
            diag["effective_generation_kwh"] = delta
            meter_diag[gid] = diag
        bucket["generator_energy_meter"] = meter_diag
        return end_values

    def _calibrate_quarter_with_energy_meters(
        self, bucket: dict[str, Any], end_ts: float
    ) -> dict[str, float | None]:
        """Calibrate a completed 15-minute bucket from cumulative kWh meters."""
        end_values: dict[str, float | None] = {cid: None for cid in self.all_consumers}
        meter_diag: dict[str, Any] = {}
        for cid, consumer in self.energy_consumers.items():
            end_value, end_meta = self._energy_counter_at(cid, end_ts)
            end_values[cid] = end_value
            start_value = bucket.get("energy_start", {}).get(cid)
            old = dict(bucket["values"].get(cid, {}))
            power_total = max(0.0, float(old.get("total", 0.0)))
            diag = {
                "entity_id": consumer.get("energy_entity_id"),
                "mode": consumer.get("energy_mode", ENERGY_MODE_AUTO),
                "status": "power_fallback",
                "power_integrated_kwh": power_total,
                "meter_delta_kwh": None,
                "deviation_percent": None,
                "boundary_status": end_meta.get("status"),
            }
            if start_value is None or end_value is None:
                diag["reason"] = "baseline_missing" if start_value is None else "end_missing"
                meter_diag[cid] = diag
                continue
            try:
                delta = float(end_value) - float(start_value)
            except (TypeError, ValueError):
                diag["reason"] = "invalid_counter"
                meter_diag[cid] = diag
                continue
            # Counter reset/replacement: never turn a backwards jump into negative energy.
            if not math.isfinite(delta) or delta < -1e-9:
                diag["reason"] = "counter_reset_or_backward"
                meter_diag[cid] = diag
                continue
            delta = max(0.0, delta)
            diag["meter_delta_kwh"] = delta
            if power_total > 1e-9:
                diag["deviation_percent"] = (delta - power_total) / power_total * 100.0
            # A cumulative meter that has not advanced at all while the power
            # integration clearly saw consumption is usually just a stale/coarse
            # counter report. Never erase measured energy in that situation.
            if delta <= 1e-9 and power_total >= 0.002:
                diag["reason"] = "counter_not_advanced"
                meter_diag[cid] = diag
                continue
            if (
                str(consumer.get("energy_mode") or ENERGY_MODE_AUTO) == ENERGY_MODE_AUTO
                and power_total >= 0.01
                and delta > 0
                and not (0.2 <= delta / power_total <= 5.0)
            ):
                diag["reason"] = "counter_delta_implausible"
                meter_diag[cid] = diag
                continue
            source_sum = sum(max(0.0, float(old.get(src, 0.0))) for src in ("pv", "grid", "battery"))
            if delta > 1e-9 and source_sum <= 1e-12:
                diag["reason"] = "source_mix_unavailable"
                meter_diag[cid] = diag
                continue
            if source_sum <= 1e-12:
                calibrated = {"total": 0.0, "pv": 0.0, "grid": 0.0, "battery": 0.0}
            else:
                calibrated = {
                    "total": delta,
                    "pv": delta * max(0.0, float(old.get("pv", 0.0))) / source_sum,
                    "grid": delta * max(0.0, float(old.get("grid", 0.0))) / source_sum,
                    "battery": delta * max(0.0, float(old.get("battery", 0.0))) / source_sum,
                }
            bucket["values"][cid] = calibrated
            old_pv = max(0.0, float(old.get("pv", 0.0)))
            pv_factor = (calibrated["pv"] / old_pv) if old_pv > 1e-12 else 0.0
            for gid, old_attr in list(bucket.get("pv_by_generator_kwh", {}).get(cid, {}).items()):
                old_attr = max(0.0, float(old_attr))
                new_attr = old_attr * pv_factor
                bucket["pv_by_generator_kwh"][cid][gid] = new_attr
                if cid in self.bucket_hour.get("pv_by_generator_kwh", {}) and gid in self.bucket_hour["pv_by_generator_kwh"][cid]:
                    self.bucket_hour["pv_by_generator_kwh"][cid][gid] = max(
                        0.0, self.bucket_hour["pv_by_generator_kwh"][cid][gid] + (new_attr - old_attr)
                    )
                if cid in self.bucket_day.get("pv_by_generator_kwh", {}) and gid in self.bucket_day["pv_by_generator_kwh"][cid]:
                    self.bucket_day["pv_by_generator_kwh"][cid][gid] = max(
                        0.0, self.bucket_day["pv_by_generator_kwh"][cid][gid] + (new_attr - old_attr)
                    )
            # Hour/day have already received the power-integrated quarter; apply
            # only the correction before those larger buckets can close.
            for source in SOURCES:
                correction = calibrated[source] - max(0.0, float(old.get(source, 0.0)))
                self.bucket_hour["values"][cid][source] = max(
                    0.0, self.bucket_hour["values"][cid][source] + correction
                )
                self.bucket_day["values"][cid][source] = max(
                    0.0, self.bucket_day["values"][cid][source] + correction
                )
            diag["status"] = "energy_meter"
            diag["reason"] = None
            meter_diag[cid] = diag
        bucket["energy_meter"] = meter_diag
        return end_values

    @callback
    def _buffer_state(self, entity_id: str, state: State | None, reported_at: datetime | None = None) -> None:
        """Store one reported state, including unavailable markers, by report time."""
        if not self.sync_enabled or not entity_id:
            return
        when = reported_at
        if when is None and state is not None:
            when = state.last_reported
        if when is None:
            when = datetime.now(UTC)
        ts = dt_util.as_utc(when).timestamp()
        value: float | None = None
        if state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            if entity_id in self._energy_entity_ids:
                value = self._energy_state_to_kwh(state)
            else:
                value = _finite_float(state.state)
        self._record_report_cadence(entity_id, ts, value)
        queue = self._measurement_buffer.setdefault(entity_id, deque())
        sample = (ts, value)
        if queue and abs(queue[-1][0] - ts) < 1e-6:
            queue[-1] = sample
        elif not queue or queue[-1][0] < ts:
            queue.append(sample)
        else:
            items = list(queue)
            items.append(sample)
            items.sort(key=lambda item: item[0])
            queue.clear()
            queue.extend(items)
        cutoff = datetime.now(UTC).timestamp() - self._buffer_retention
        while len(queue) > 1 and queue[1][0] < cutoff:
            queue.popleft()

    @callback
    def _async_state_changed(self, event: Event) -> None:
        state = event.data.get("new_state")
        entity_id = str(event.data.get("entity_id") or "")
        reported_at = state.last_reported if state is not None else event.time_fired
        self._buffer_state(entity_id, state, reported_at)

    @callback
    def _async_state_reported(self, event: Event) -> None:
        state = event.data.get("new_state")
        entity_id = str(event.data.get("entity_id") or "")
        reported_at = event.data.get("last_reported")
        self._buffer_state(entity_id, state, reported_at)

    def _seed_measurement_buffer(self) -> None:
        """Seed buffers with the latest known HA states before event tracking starts."""
        if not self.sync_enabled:
            return
        for entity_id in self._tracked_live_entities():
            state = self.hass.states.get(entity_id)
            if state is not None:
                self._buffer_state(entity_id, state, state.last_reported)

    def _buffer_candidate(
        self, entity_id: str | None, target_ts: float, *, max_age: float
    ) -> tuple[float | None, float | None, float | None]:
        """Return latest buffered value at/before target, its age and timestamp."""
        if not entity_id:
            return None, None, None
        queue = self._measurement_buffer.get(entity_id)
        if not queue:
            return None, None, None
        for sample_ts, value in reversed(queue):
            if sample_ts <= target_ts + 1e-6 and value is not None:
                age = max(0.0, target_ts - sample_ts)
                if age > max_age:
                    return None, age, sample_ts
                return value, age, sample_ts
        return None, None, None

    def _latest_sample_meta(
        self, entity_id: str | None, target_ts: float
    ) -> tuple[float | None, float | None, float | None]:
        """Return latest value/age/timestamp at or before target without freshness filtering."""
        if not entity_id:
            return None, None, None
        if self.sync_enabled:
            queue = self._measurement_buffer.get(entity_id)
            if not queue:
                return None, None, None
            for sample_ts, value in reversed(queue):
                if sample_ts <= target_ts + 1e-6 and value is not None:
                    return value, max(0.0, target_ts - sample_ts), sample_ts
            return None, None, None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None, None, None
        sample_ts = dt_util.as_utc(state.last_reported).timestamp()
        value = None
        if state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            value = _finite_float(state.state)
        return value, max(0.0, target_ts - sample_ts), sample_ts

    def _timing_snapshot(self, target_ts: float) -> dict[str, dict[str, Any]]:
        """Build adaptive timing diagnostics for every tracked sensor, including PV."""
        result: dict[str, dict[str, Any]] = {}
        for entity_id in self._tracked_live_entities():
            value, age, _sample_ts = self._latest_sample_meta(entity_id, target_ts)
            generator_timeout = self._generator_hard_timeout_for_entity(entity_id)
            timing = self._sensor_timing_status(
                entity_id, age, explicit_max_age=generator_timeout
            )
            if value is None:
                timing["status"] = "missing"
            result[entity_id] = timing
        return result

    @staticmethod
    def _sync_quality_from_sensors(
        sensor_timing: dict[str, dict[str, Any]], enabled: bool
    ) -> str:
        """Rate synchronization from each sensor's learned cadence, not raw spread."""
        if not enabled:
            return "disabled"
        if not sensor_timing:
            return "warming_up"
        statuses = {str(item.get("status")) for item in sensor_timing.values()}
        if "stale" in statuses or "missing" in statuses:
            return "poor"
        if "delayed" in statuses:
            return "fair"
        if "learning" in statuses:
            return "warming_up"
        return "good"

    async def async_start(self) -> None:
        """Load persisted state and start periodic sampling."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._restore(stored)

        self._seed_measurement_buffer()
        if self.sync_enabled:
            tracked = self._tracked_live_entities()
            self._unsubs.append(
                async_track_state_change_event(self.hass, tracked, self._async_state_changed)
            )
            self._unsubs.append(
                async_track_state_report_event(self.hass, tracked, self._async_state_reported)
            )

        wall_now = datetime.now(UTC)
        target_now = wall_now - timedelta(seconds=self.sync_delay if self.sync_enabled else 0.0)
        target_ts = target_now.timestamp()
        if self._last_sample_ts is not None and target_ts > self._last_sample_ts:
            # Never invent energy for a Home Assistant outage. The synchronized
            # time axis is delayed, so the gap is closed only up to its target time.
            self._advance_interval(self._last_sample_ts, target_ts, None, None)
        self._last_sample_ts = target_ts
        self._last_allocation, self._last_diag = self._calculate_snapshot(target_now)

        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_tick,
                timedelta(seconds=self.sample_interval),
                name="PV energy allocation sampler",
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._async_periodic_save,
                timedelta(seconds=STORAGE_SAVE_INTERVAL),
                name="PV energy allocation storage",
            )
        )
        self._unsubs.append(
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_on_stop)
        )

    def _restore(self, stored: dict[str, Any]) -> None:
        lifetime = stored.get("lifetime")
        if isinstance(lifetime, dict):
            # Preserve inactive/removed additional consumers in storage. If the
            # same entity is added again later, its monotonic lifetime counter
            # can continue instead of restarting from zero.
            for cid, raw_sources in lifetime.items():
                if not isinstance(raw_sources, dict):
                    continue
                self.lifetime.setdefault(cid, {source: 0.0 for source in SOURCES})
                for source in SOURCES:
                    try:
                        self.lifetime[cid][source] = max(
                            0.0, float(raw_sources.get(source, 0.0))
                        )
                    except (TypeError, ValueError):
                        pass
        for cid in self.all_consumers:
            self.lifetime.setdefault(cid, {source: 0.0 for source in SOURCES})
        raw_pv_generator_lifetime = stored.get("pv_generator_lifetime", {})
        if isinstance(raw_pv_generator_lifetime, dict):
            for cid in self.all_consumers:
                row = raw_pv_generator_lifetime.get(cid, {})
                if not isinstance(row, dict):
                    continue
                for gid in self.all_generators:
                    try:
                        self.pv_generator_lifetime[cid][gid] = max(0.0, float(row.get(gid, 0.0)))
                    except (TypeError, ValueError):
                        pass

        self.last_15m = stored.get("last_15m") if isinstance(stored.get("last_15m"), dict) else None
        try:
            self.coverage_lifetime_s = max(0.0, float(stored.get("coverage_lifetime_s", 0.0)))
        except (TypeError, ValueError):
            self.coverage_lifetime_s = 0.0

        now_ts = datetime.now(UTC).timestamp() - (self.sync_delay if self.sync_enabled else 0.0)
        self.bucket_15m = self._restore_bucket(stored.get("bucket_15m"), self._quarter_start(now_ts))
        self.bucket_hour = self._restore_bucket(stored.get("bucket_hour"), self._hour_start(now_ts))
        self.bucket_day = self._restore_bucket(stored.get("bucket_day"), self._day_start(now_ts))
        # WattWer <=0.5.x incremented lifetime counters continuously while the
        # current quarter was still open. Never decrease TOTAL_INCREASING values
        # during migration. Instead remember the already-committed portion and
        # add only the remainder when this one transition quarter closes. Meter
        # calibration starts with the next complete quarter.
        if stored.get("accounting_mode") != "quarter_commit":
            self.bucket_15m["lifetime_committed"] = deepcopy(self.bucket_15m["values"])
            self.bucket_15m["energy_calibration_allowed"] = False
        last_ts = stored.get("last_sample_ts")
        try:
            self._last_sample_ts = float(last_ts) if last_ts is not None else None
        except (TypeError, ValueError):
            self._last_sample_ts = None

        raw_cadence = stored.get("cadence_intervals")
        if isinstance(raw_cadence, dict):
            for entity_id, raw_values in raw_cadence.items():
                if not isinstance(raw_values, list):
                    continue
                values: deque[float] = deque(maxlen=CADENCE_WINDOW)
                for raw_value in raw_values[-CADENCE_WINDOW:]:
                    try:
                        value = float(raw_value)
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(value) and value > 0:
                        values.append(value)
                if values:
                    self._cadence_intervals[str(entity_id)] = values

    def _restore_bucket(self, raw: Any, fallback_start: float) -> dict[str, Any]:
        if not isinstance(raw, dict) or "start" not in raw:
            return _new_bucket(fallback_start, self.all_consumers, self.all_generators)
        bucket = _new_bucket(float(raw.get("start", fallback_start)), self.all_consumers, self.all_generators)
        bucket["coverage"] = max(0.0, float(raw.get("coverage", 0.0)))
        bucket["balance_ws"] = float(raw.get("balance_ws", 0.0))
        bucket["house_net_error_ws"] = float(raw.get("house_net_error_ws", 0.0))
        bucket["diag_coverage"] = max(0.0, float(raw.get("diag_coverage", 0.0)))
        bucket["sync_spread_ss"] = float(raw.get("sync_spread_ss", 0.0))
        bucket["sync_max_age_ss"] = float(raw.get("sync_max_age_ss", 0.0))
        bucket["sync_diag_coverage"] = max(0.0, float(raw.get("sync_diag_coverage", 0.0)))
        bucket["sync_spread_max_s"] = max(0.0, float(raw.get("sync_spread_max_s", 0.0)))
        bucket["sync_sample_age_max_s"] = max(0.0, float(raw.get("sync_sample_age_max_s", 0.0)))
        raw_energy_start = raw.get("energy_start", {})
        if isinstance(raw_energy_start, dict):
            for cid in self.all_consumers:
                value = raw_energy_start.get(cid)
                try:
                    bucket["energy_start"][cid] = float(value) if value is not None else None
                except (TypeError, ValueError):
                    bucket["energy_start"][cid] = None
        if isinstance(raw.get("energy_meter"), dict):
            bucket["energy_meter"] = deepcopy(raw.get("energy_meter"))
        raw_generator_energy_start = raw.get("generator_energy_start", {})
        if isinstance(raw_generator_energy_start, dict):
            for gid in self.all_generators:
                value = raw_generator_energy_start.get(gid)
                try:
                    bucket["generator_energy_start"][gid] = float(value) if value is not None else None
                except (TypeError, ValueError):
                    bucket["generator_energy_start"][gid] = None
        if isinstance(raw.get("generator_energy_meter"), dict):
            bucket["generator_energy_meter"] = deepcopy(raw.get("generator_energy_meter"))
        raw_generator_power = raw.get("generator_power_kwh", {})
        if isinstance(raw_generator_power, dict):
            for gid in self.all_generators:
                try:
                    bucket["generator_power_kwh"][gid] = max(0.0, float(raw_generator_power.get(gid, 0.0)))
                except (TypeError, ValueError):
                    pass
        raw_pv_by_generator = raw.get("pv_by_generator_kwh", {})
        if isinstance(raw_pv_by_generator, dict):
            for cid in self.all_consumers:
                row = raw_pv_by_generator.get(cid, {})
                if not isinstance(row, dict):
                    continue
                for gid in self.all_generators:
                    try:
                        bucket["pv_by_generator_kwh"][cid][gid] = max(0.0, float(row.get(gid, 0.0)))
                    except (TypeError, ValueError):
                        pass
        bucket["energy_calibration_allowed"] = bool(raw.get("energy_calibration_allowed", True))
        raw_committed = raw.get("lifetime_committed", {})
        if isinstance(raw_committed, dict):
            for cid in self.all_consumers:
                for source in SOURCES:
                    try:
                        bucket["lifetime_committed"][cid][source] = max(
                            0.0, float(raw_committed.get(cid, {}).get(source, 0.0))
                        )
                    except (TypeError, ValueError):
                        pass
        values = raw.get("values", {})
        for cid in self.all_consumers:
            for source in SOURCES:
                try:
                    bucket["values"][cid][source] = max(
                        0.0, float(values.get(cid, {}).get(source, 0.0))
                    )
                except (TypeError, ValueError):
                    pass
        return bucket

    async def async_stop(self) -> None:
        """Stop timers and persist any state that changed since the last save."""
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
        self._unsubs.clear()
        if self._save_task is not None and not self._save_task.done():
            try:
                await self._save_task
            except Exception:  # pragma: no cover - final save below retries
                pass
        await self._async_save_state()

    async def _async_on_stop(self, _event: Event) -> None:
        await self._async_save_state()

    async def _async_periodic_save(self, _now: datetime) -> None:
        # Runtime state is intentionally persisted only every five minutes.
        # Quarter-hour closes schedule an immediate save separately.
        await self._async_save_state()

    async def _async_save_state(self) -> None:
        """Persist a coherent runtime snapshot only when something changed."""
        async with self._save_lock:
            if not self._dirty:
                return
            payload = self._serialize()
            # Clear before awaiting I/O. If a sample changes state while the save
            # is in progress, _advance_interval() sets _dirty again and that
            # newer state will be written by the next scheduled/quarter save.
            self._dirty = False
            try:
                await self._store.async_save(payload)
            except Exception:
                self._dirty = True
                raise

    @callback
    def _schedule_save(self) -> None:
        """Schedule an immediate non-blocking save, coalescing duplicates."""
        if self._save_task is not None and not self._save_task.done():
            return
        self._save_task = self.hass.async_create_task(self._async_save_state())

    async def _async_tick(self, now: datetime) -> None:
        wall_now = dt_util.as_utc(now)
        target_now = wall_now - timedelta(seconds=self.sync_delay if self.sync_enabled else 0.0)
        target_ts = target_now.timestamp()
        if self._last_sample_ts is None:
            self._last_sample_ts = target_ts
            self._last_allocation, self._last_diag = self._calculate_snapshot(target_now)
            return

        dt_s = target_ts - self._last_sample_ts
        # A very large event-loop gap should not turn stale power into fictitious
        # energy. The same max_age used for source freshness is the upper bound.
        if dt_s <= 0:
            return
        if dt_s > self.max_age:
            self._advance_interval(self._last_sample_ts, target_ts, None, None)
        else:
            self._advance_interval(
                self._last_sample_ts,
                target_ts,
                self._last_allocation,
                self._last_diag if self._last_allocation is not None else None,
            )

        self._last_sample_ts = target_ts
        self._last_allocation, self._last_diag = self._calculate_snapshot(target_now)

    def _read_power(
        self,
        entity_id: str | None,
        now: datetime,
        *,
        required: bool,
        max_age: float | None = None,
    ) -> tuple[float | None, str | None, float | None, float | None]:
        """Read one power sensor at the synchronized target timestamp.

        Adaptive mode learns each sensor's normal report cadence. A value stays
        usable until its learned stale threshold is exceeded; an absolute hard
        timeout always bounds that threshold.
        """
        if not entity_id:
            return (None, None if not required else "<not configured>", None, None)

        profile = self._cadence_profile(entity_id, explicit_max_age=max_age)
        freshness = float(profile["stale_after_s"])
        if self.sync_enabled:
            value, age, sample_ts = self._buffer_candidate(
                entity_id, now.timestamp(), max_age=freshness
            )
            if value is None:
                return (None, entity_id if required else None, sample_ts, age)
            return value, None, sample_ts, age

        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return (None, entity_id if required else None, None, None)
        value = _finite_float(state.state)
        if value is None:
            return (None, entity_id if required else None, None, None)
        sample_ts = dt_util.as_utc(state.last_reported).timestamp()
        age = max(0.0, (now.timestamp() - sample_ts))
        if age > freshness:
            return (None, entity_id if required else None, sample_ts, age)
        return value, None, sample_ts, age

    def _power_candidate(
        self, entity_id: str | None, now: datetime, *, max_age: float
    ) -> tuple[float | None, float | None, float | None]:
        """Return a usable power value, report age and report timestamp."""
        if not entity_id:
            return None, None, None
        freshness = float(
            self._cadence_profile(entity_id, explicit_max_age=max_age)["stale_after_s"]
        )
        if self.sync_enabled:
            return self._buffer_candidate(entity_id, now.timestamp(), max_age=freshness)
        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None, None, None
        value = _finite_float(state.state)
        if value is None:
            return None, None, None
        sample_ts = dt_util.as_utc(state.last_reported).timestamp()
        age = max(0.0, now.timestamp() - sample_ts)
        if age > freshness:
            return None, age, sample_ts
        return value, age, sample_ts

    def _sun_below_horizon(self) -> bool:
        """Return True only when Home Assistant positively knows it is night."""
        sun = self.hass.states.get("sun.sun")
        return sun is not None and sun.state == "below_horizon"

    def _read_generator_resilient(
        self, generator: dict[str, Any], now: datetime
    ) -> tuple[float | None, str, list[str], str | None, float | None, float | None]:
        """Read one PV generator with fallback and optional night-zero handling."""
        try:
            grace = max(self.max_age, float(generator.get("max_age", 180.0)))
        except (TypeError, ValueError):
            grace = max(self.max_age, 180.0)

        candidates: list[tuple[float, float, str, float]] = []
        primary_id = str(generator.get("entity_id") or "").strip()
        fallback_id = str(generator.get("fallback_entity_id") or "").strip()
        primary, primary_age, primary_ts = self._power_candidate(primary_id, now, max_age=grace)
        if primary is not None and primary_age is not None and primary_ts is not None:
            candidates.append((primary_age, primary, primary_id, primary_ts))
        fallback, fallback_age, fallback_ts = self._power_candidate(fallback_id, now, max_age=grace)
        if fallback is not None and fallback_age is not None and fallback_ts is not None:
            candidates.append((fallback_age, fallback, fallback_id, fallback_ts))

        if candidates:
            age, value, source, sample_ts = min(candidates, key=lambda item: item[0])
            if fallback_id and source == fallback_id:
                return value, "fallback_generator", [
                    f"{generator.get('name', primary_id)}: Fallback-Sensor verwendet"
                ], source, sample_ts, age
            return value, "ok", [], source, sample_ts, age

        if bool(generator.get("night_zero", True)) and self._sun_below_horizon():
            return 0.0, "fallback_night_zero", [
                f"{generator.get('name', primary_id)}: nachts ohne Messwert als 0 W behandelt"
            ], None, None, None

        return None, "degraded_generator", [
            f"{generator.get('name', primary_id)}: Erzeugungsleistung unbekannt"
        ], None, None, None

    def _positive(self, value: float) -> float:
        if value <= self.deadband:
            return 0.0
        return value

    def _generator_power_from_raw(
        self, generator: dict[str, Any], raw_value: float, source_entity: str | None
    ) -> float:
        """Normalize a generator reading to positive generation power.

        PV meters are not consistent: inverter integrations commonly expose
        generation as positive power, while bidirectional branch meters may
        expose export/generation as negative power. The configured polarity is
        applied before allocation, diagnostics and backfill use the value.
        Primary and fallback sensors can deliberately use different conventions.
        """
        signed = self._signed_deadband(float(raw_value))
        primary = str(generator.get("entity_id") or "")
        fallback = str(generator.get("fallback_entity_id") or "")
        polarity = str(generator.get("polarity") or GENERATOR_POLARITY_POSITIVE)
        if source_entity and fallback and source_entity == fallback:
            fallback_polarity = str(
                generator.get("fallback_polarity")
                or GENERATOR_FALLBACK_POLARITY_SAME
            )
            if fallback_polarity != GENERATOR_FALLBACK_POLARITY_SAME:
                polarity = fallback_polarity
        if polarity == GENERATOR_POLARITY_NEGATIVE:
            return max(-signed, 0.0)
        return max(signed, 0.0)

    def _signed_deadband(self, value: float) -> float:
        if abs(value) <= self.deadband:
            return 0.0
        return value

    def required_history_entities(self) -> list[str]:
        """Return raw entities useful for historical reconstruction."""
        ids: list[str] = [
            str(self.cfg.get(CONF_GRID_IMPORT) or ""),
            str(self.cfg.get(CONF_GRID_EXPORT) or ""),
        ]
        ids.extend(str(item["entity_id"]) for item in self.consumers.values())
        ids.extend(
            str(item.get("energy_entity_id") or "")
            for item in self.energy_consumers.values()
        )
        ids.extend(str(x) for x in (self.cfg.get(CONF_BACKGROUND_LOADS) or []))
        for generator in self.generators.values():
            ids.append(str(generator.get("entity_id") or ""))
            ids.append(str(generator.get("fallback_entity_id") or ""))
            ids.append(str(generator.get("energy_entity_id") or ""))
        if self.battery_enabled:
            ids.extend(
                [
                    str(self.cfg.get(CONF_BATTERY_CHARGE) or ""),
                    str(self.cfg.get(CONF_BATTERY_DISCHARGE) or ""),
                ]
            )
        return list(dict.fromkeys(x for x in ids if x))

    def allocation_from_entity_values(
        self, entity_values: dict[str, float]
    ) -> tuple[dict[str, dict[str, float]] | None, dict[str, Any]]:
        """Calculate one historical snapshot from Recorder as-of values."""
        required: list[str] = [
            str(self.cfg.get(CONF_GRID_IMPORT) or ""),
            str(self.cfg.get(CONF_GRID_EXPORT) or ""),
        ]
        required.extend(str(item["entity_id"]) for item in self.consumers.values())
        required.extend(str(x) for x in (self.cfg.get(CONF_BACKGROUND_LOADS) or []))
        if self.battery_enabled:
            required.extend(
                [
                    str(self.cfg.get(CONF_BATTERY_CHARGE) or ""),
                    str(self.cfg.get(CONF_BATTERY_DISCHARGE) or ""),
                ]
            )
        required = [eid for eid in required if eid]
        missing = [
            eid
            for eid in required
            if eid not in entity_values or not math.isfinite(entity_values[eid])
        ]
        if missing:
            return None, {
                "valid": False,
                "quality": "invalid",
                "stale_entities": sorted(missing),
            }

        generator_readings: dict[str, dict[str, Any]] = {}
        missing_generators: list[str] = []
        quality_notes: list[str] = []
        for gid, generator in self.generators.items():
            primary = str(generator.get("entity_id") or "")
            fallback = str(generator.get("fallback_entity_id") or "")
            value = entity_values.get(primary) if primary else None
            source = primary if value is not None and math.isfinite(value) else None
            if value is None or not math.isfinite(value):
                value = entity_values.get(fallback) if fallback else None
                source = fallback if value is not None and math.isfinite(value) else None
            known = value is not None and math.isfinite(value)
            if not known:
                if self.battery_enabled:
                    missing_generators.append(primary or fallback or gid)
                else:
                    quality_notes.append(
                        f"{generator.get('name', gid)}: historische Erzeugung unbekannt; proportional rekonstruiert"
                    )
            generator_readings[gid] = {
                "value": float(value) if known else 0.0,
                "known": known,
                "source_entity": source,
            }
        if missing_generators:
            return None, {
                "valid": False,
                "quality": "invalid",
                "stale_entities": sorted(set(missing_generators)),
            }

        values = {
            "grid_import": entity_values[str(self.cfg.get(CONF_GRID_IMPORT))],
            "grid_export": entity_values[str(self.cfg.get(CONF_GRID_EXPORT))],
        }
        for cid, consumer in self.consumers.items():
            values[cid] = entity_values[consumer["entity_id"]]
        backgrounds = [
            self._positive(entity_values[str(eid)])
            for eid in (self.cfg.get(CONF_BACKGROUND_LOADS) or [])
        ]
        battery_charge = (
            self._positive(entity_values[str(self.cfg.get(CONF_BATTERY_CHARGE))])
            if self.battery_enabled
            else 0.0
        )
        battery_discharge = (
            self._positive(entity_values[str(self.cfg.get(CONF_BATTERY_DISCHARGE))])
            if self.battery_enabled
            else 0.0
        )
        house_net = entity_values.get(str(self.cfg.get(CONF_HOUSE_NET) or ""))
        return self._compute_allocation(
            values,
            backgrounds,
            generator_readings,
            battery_charge,
            battery_discharge,
            house_net,
            quality="ok" if not quality_notes else "degraded_generator_proportional",
            quality_notes=quality_notes,
        )

    def _calculate_snapshot(
        self, now: datetime
    ) -> tuple[dict[str, dict[str, float]] | None, dict[str, Any]]:
        stale: list[str] = []
        quality = "ok"
        quality_notes: list[str] = []
        sample_times: list[float] = []
        sample_ages: list[float] = []
        critical_entities: set[str] = set()

        def note_timing(
            entity_id: str | None, sample_ts: float | None, age: float | None, *, critical: bool = True
        ) -> None:
            if sample_ts is not None:
                sample_times.append(float(sample_ts))
            if age is not None:
                sample_ages.append(max(0.0, float(age)))
            if critical and entity_id:
                critical_entities.add(str(entity_id))

        required_ids = {
            "grid_import": self.cfg.get(CONF_GRID_IMPORT),
            "grid_export": self.cfg.get(CONF_GRID_EXPORT),
        }
        for cid, consumer in self.consumers.items():
            required_ids[cid] = consumer["entity_id"]

        values: dict[str, float] = {}
        for key, entity_id in required_ids.items():
            val, bad, sample_ts, age = self._read_power(entity_id, now, required=True)
            note_timing(str(entity_id or ""), sample_ts, age)
            if bad:
                stale.append(bad)
            elif val is not None:
                values[key] = val

        backgrounds: list[float] = []
        for entity_id in list(self.cfg.get(CONF_BACKGROUND_LOADS) or []):
            val, bad, sample_ts, age = self._read_power(entity_id, now, required=True)
            note_timing(str(entity_id), sample_ts, age)
            if bad:
                stale.append(bad)
            elif val is not None:
                backgrounds.append(self._positive(val))

        generator_readings: dict[str, dict[str, Any]] = {}
        for gid, generator in self.generators.items():
            value, gen_quality, notes, source_entity, sample_ts, age = (
                self._read_generator_resilient(generator, now)
            )
            known = value is not None
            allocation_critical = (
                self.battery_enabled
                or generator.get("role") == GENERATOR_ROLE_DIRECT_CONSUMER
            )
            if known and source_entity:
                note_timing(source_entity, sample_ts, age, critical=allocation_critical)
            if not known and self.battery_enabled:
                stale.append(str(generator.get("entity_id") or gid))
            elif gen_quality != "ok":
                if quality == "ok" or gen_quality == "degraded_generator":
                    quality = (
                        "degraded_generator_proportional"
                        if not known
                        else gen_quality
                    )
                quality_notes.extend(notes)
            generator_readings[gid] = {
                "value": float(value) if known else 0.0,
                "known": known,
                "source_entity": source_entity,
            }

        battery_charge = 0.0
        battery_discharge = 0.0
        if self.battery_enabled:
            charge_entity = str(self.cfg.get(CONF_BATTERY_CHARGE) or "")
            discharge_entity = str(self.cfg.get(CONF_BATTERY_DISCHARGE) or "")
            charge, bad_charge, charge_ts, charge_age = self._read_power(
                charge_entity, now, required=True
            )
            discharge, bad_discharge, discharge_ts, discharge_age = self._read_power(
                discharge_entity, now, required=True
            )
            note_timing(charge_entity, charge_ts, charge_age)
            note_timing(discharge_entity, discharge_ts, discharge_age)
            if bad_charge:
                stale.append(bad_charge)
            if bad_discharge:
                stale.append(bad_discharge)
            if charge is not None:
                battery_charge = self._positive(charge)
            if discharge is not None:
                battery_discharge = self._positive(discharge)

        sensor_timing = self._timing_snapshot(now.timestamp())
        for entity_id, timing in sensor_timing.items():
            timing["critical"] = entity_id in critical_entities

        # If a PV generator is intentionally treated as zero at night, lack of a
        # report is expected and should not be presented as a timing fault. This
        # applies to both its primary and fallback sensor while still retaining
        # their learned daytime cadence.
        if self._sun_below_horizon():
            for generator in self.generators.values():
                if not bool(generator.get("night_zero", True)):
                    continue
                for entity_id in (
                    str(generator.get("entity_id") or ""),
                    str(generator.get("fallback_entity_id") or ""),
                ):
                    if entity_id and entity_id in sensor_timing:
                        meta = sensor_timing[entity_id]
                        if meta.get("status") in {"missing", "stale"}:
                            meta["status"] = "night_zero"
                            meta["critical"] = False

        delayed_entities = sorted(
            entity_id
            for entity_id, timing in sensor_timing.items()
            if timing.get("critical") and timing.get("status") == "delayed"
        )
        critical_timing = {
            entity_id: timing
            for entity_id, timing in sensor_timing.items()
            if timing.get("critical")
        }
        spread = (
            max(sample_times) - min(sample_times)
            if len(sample_times) >= 2
            else (0.0 if sample_times else None)
        )
        max_sample_age = max(sample_ages) if sample_ages else None
        timing_diag = {
            "sync_enabled": self.sync_enabled,
            "sync_delay_s": self.sync_delay if self.sync_enabled else 0.0,
            "sync_method": "adaptive_sample_hold" if self.sync_enabled else "current_state",
            "sync_target_ms": int(now.timestamp() * 1000),
            "sync_spread_s": spread,
            "sync_max_sample_age_s": max_sample_age,
            "sync_sample_count": len(sample_times),
            "sync_quality": self._sync_quality_from_sensors(critical_timing, self.sync_enabled),
            "adaptive_freshness": self.adaptive_freshness,
            "adaptive_hard_timeout_s": self.adaptive_hard_timeout,
            "sensor_timing": sensor_timing,
            "delayed_entities": delayed_entities,
        }

        if delayed_entities and quality == "ok":
            quality = "delayed_sensor"
            quality_notes.append(
                "Verzögerte Meldung: " + ", ".join(delayed_entities)
            )

        if stale:
            return None, {
                **self._last_diag,
                **timing_diag,
                "valid": False,
                "quality": "invalid",
                "quality_notes": quality_notes,
                "stale_entities": sorted(set(stale)),
            }

        house_net = None
        if self.cfg.get(CONF_HOUSE_NET):
            house_net, _bad, _ts, _age = self._read_power(
                self.cfg.get(CONF_HOUSE_NET), now, required=False
            )

        allocation, diag = self._compute_allocation(
            values,
            backgrounds,
            generator_readings,
            battery_charge,
            battery_discharge,
            house_net,
            quality=quality,
            quality_notes=quality_notes,
        )
        diag.update(timing_diag)
        return allocation, diag

    def _compute_allocation(
        self,
        values: dict[str, float],
        backgrounds: list[float],
        generator_readings: dict[str, dict[str, Any]],
        battery_charge: float,
        battery_discharge: float,
        house_net: float | None,
        *,
        quality: str = "ok",
        quality_notes: list[str] | None = None,
    ) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
        """Pure allocation math shared by live sampling and historical backfill."""
        grid_import = self._positive(values["grid_import"])
        grid_export = self._positive(values["grid_export"])
        grid_net = self._signed_deadband(grid_import - grid_export)
        grid_import_net = max(grid_net, 0.0)

        loads = {cid: self._positive(values[cid]) for cid in self.consumers}
        gross_load = sum(loads.values()) + sum(backgrounds)
        residual_loads = dict(loads)

        direct_by_consumer: dict[str, float] = {cid: 0.0 for cid in self.consumers}
        direct_by_generator_consumer: dict[str, dict[str, float]] = {
            cid: {gid: 0.0 for gid in self.generators} for cid in self.consumers
        }
        generator_power: dict[str, float | None] = {}
        generator_source_entity: dict[str, str | None] = {}
        shared_pv_available_by_generator: dict[str, float] = {gid: 0.0 for gid in self.generators}
        main_bus_pv_available = 0.0
        all_generation_known = True
        local_generator_full_power = 0.0

        # Local generators first cover their electrically linked consumer. Any
        # surplus flows to the shared bus. Main-bus generators feed the shared bus.
        for gid, generator in self.generators.items():
            reading = generator_readings.get(gid, {})
            known = bool(reading.get("known", False))
            raw_value = float(reading.get("value", 0.0)) if known else 0.0
            power = (
                self._generator_power_from_raw(
                    generator, raw_value, reading.get("source_entity")
                )
                if known
                else 0.0
            )
            generator_power[gid] = power if known else None
            generator_source_entity[gid] = reading.get("source_entity")
            if not known:
                all_generation_known = False
                continue

            if generator.get("role") == GENERATOR_ROLE_DIRECT_CONSUMER:
                target = str(generator.get("consumer_id") or "")
                if target in residual_loads:
                    direct = min(power, residual_loads[target])
                    residual_loads[target] = max(residual_loads[target] - direct, 0.0)
                    direct_by_consumer[target] += direct
                    direct_by_generator_consumer[target][gid] += direct
                    surplus = max(power - direct, 0.0)
                    main_bus_pv_available += surplus
                    shared_pv_available_by_generator[gid] += surplus
                    local_generator_full_power += power
                else:
                    main_bus_pv_available += power
                    shared_pv_available_by_generator[gid] += power
            else:
                main_bus_pv_available += power
                shared_pv_available_by_generator[gid] += power

        main_bus_consumer_sink = sum(residual_loads.values()) + sum(backgrounds)
        main_bus_sink = main_bus_consumer_sink + battery_charge
        grid_to_sink = min(grid_import_net, main_bus_sink)
        non_grid_need = max(main_bus_sink - grid_to_sink, 0.0)
        grid_fraction = grid_to_sink / main_bus_sink if main_bus_sink > 0 else 0.0

        if self.battery_enabled and main_bus_sink > 0:
            local_source_total = main_bus_pv_available + battery_discharge
            battery_to_sink = (
                non_grid_need * battery_discharge / local_source_total
                if local_source_total > 0
                else 0.0
            )
            battery_fraction = min(max(battery_to_sink / main_bus_sink, 0.0), 1.0)
        else:
            battery_fraction = 0.0
        pv_fraction = max(0.0, 1.0 - grid_fraction - battery_fraction)

        allocation = _empty_values(self.all_consumers)
        pv_by_generator_w: dict[str, dict[str, float]] = {
            cid: {gid: 0.0 for gid in self.generators} for cid in self.all_consumers
        }
        shared_available_total = sum(shared_pv_available_by_generator.values())
        for cid, load in loads.items():
            residual = residual_loads[cid]
            grid_w = residual * grid_fraction
            battery_w = residual * battery_fraction
            # PV is the residual by construction and therefore includes local
            # direct generation plus the consumer's share of shared-bus PV.
            pv_w = max(load - grid_w - battery_w, 0.0)
            allocation[cid] = {
                "total": load,
                "pv": pv_w,
                "grid": grid_w,
                "battery": battery_w,
            }
            for gid, direct in direct_by_generator_consumer.get(cid, {}).items():
                pv_by_generator_w[cid][gid] += max(0.0, direct)
            shared_pv_for_consumer = max(0.0, pv_w - direct_by_consumer.get(cid, 0.0))
            # Generator-level attribution is exact only while every active PV
            # source is known. Otherwise aggregate PV remains valid from the
            # grid/load balance but its generator origin is intentionally left
            # unattributed instead of guessed.
            if all_generation_known and shared_available_total > 1e-12:
                for gid, available in shared_pv_available_by_generator.items():
                    if available > 0:
                        pv_by_generator_w[cid][gid] += (
                            shared_pv_for_consumer * available / shared_available_total
                        )

        generation_total = sum(x for x in generator_power.values() if x is not None)
        balance_error = None
        if all_generation_known:
            balance_error = (
                grid_import
                + generation_total
                + battery_discharge
                - grid_export
                - gross_load
                - battery_charge
            )

        house_net_error = None
        if house_net is not None and math.isfinite(house_net) and all_generation_known:
            # Optional diagnostic for user-defined net-load sensors behind local
            # consumer-linked generators. Main-bus PV is intentionally excluded.
            expected_house_net = gross_load - local_generator_full_power
            house_net_error = expected_house_net - house_net

        direct_total = sum(direct_by_consumer.values())
        first_direct_power = next(
            (
                generator_power[gid]
                for gid, generator in self.generators.items()
                if generator.get("role") == GENERATOR_ROLE_DIRECT_CONSUMER
                and generator_power.get(gid) is not None
            ),
            None,
        )
        diag = {
            "valid": True,
            "quality": quality,
            "quality_notes": list(quality_notes or []),
            "stale_entities": [],
            "balance_error_w": balance_error,
            "house_net_error_w": house_net_error,
            "dtu_bkw_error_w": None,  # legacy dashboard compatibility
            "grid_fraction": grid_fraction,
            "pv_fraction": pv_fraction,
            "battery_fraction": battery_fraction,
            "gross_load_w": gross_load,
            "main_bus_sink_w": main_bus_sink,
            "direct_pv_w": direct_total,
            "direct_pv_by_consumer_w": direct_by_consumer,
            "pv_by_generator_w": pv_by_generator_w,
            "pv_unattributed_by_consumer_w": {
                cid: max(0.0, allocation[cid]["pv"] - sum(pv_by_generator_w.get(cid, {}).values()))
                for cid in self.all_consumers
            },
            "grid_net_w": grid_net,
            "battery_charge_w": battery_charge,
            "battery_discharge_w": battery_discharge,
            "generator_power": generator_power,
            "generator_source_entity": generator_source_entity,
            "generation_total_w": generation_total if all_generation_known else None,
            "main_bus_pv_available_w": main_bus_pv_available if all_generation_known else None,
            "all_generation_known": all_generation_known,
            "consumer_power": allocation,
            # Backward-compatible aliases used by the v0.4 dashboard.
            "direct_bkw_fw_w": direct_total,
            "main_pv_w": main_bus_pv_available if all_generation_known else None,
            "bkw_w": first_direct_power,
            "bkw_direct_known": all_generation_known,
        }
        return allocation, diag

    def _advance_interval(
        self,
        start: float,
        end: float,
        allocation: dict[str, dict[str, float]] | None,
        diag: dict[str, Any] | None,
    ) -> None:
        if end > start:
            self._dirty = True
        cursor = start
        while cursor < end - 1e-9:
            q_end = self.bucket_15m["start"] + 900.0
            h_end = self.bucket_hour["start"] + 3600.0
            d_end = self._next_day_start(self.bucket_day["start"])
            segment_end = min(end, q_end, h_end, d_end)
            seconds = max(0.0, segment_end - cursor)

            if allocation is not None and seconds > 0:
                self._integrate_bucket(self.bucket_15m, allocation, diag, seconds)
                self._integrate_bucket(self.bucket_hour, allocation, diag, seconds)
                self._integrate_bucket(self.bucket_day, allocation, diag, seconds)
                # Lifetime energy is committed only when the quarter closes.
                # This permits a hardware kWh counter to calibrate the completed
                # interval without ever making TOTAL_INCREASING sensors decrease.
                self.coverage_lifetime_s += seconds

            cursor = segment_end
            closed = False
            if abs(cursor - q_end) < 1e-6:
                self._close_bucket("15m")
                closed = True
            if abs(cursor - h_end) < 1e-6:
                self._close_bucket("hour")
                closed = True
            if abs(cursor - d_end) < 1e-6:
                self._close_bucket("day")
                closed = True

    def _integrate_bucket(
        self,
        bucket: dict[str, Any],
        allocation: dict[str, dict[str, float]],
        diag: dict[str, Any] | None,
        seconds: float,
    ) -> None:
        bucket["coverage"] += seconds
        for cid in self.all_consumers:
            for source in SOURCES:
                bucket["values"][cid][source] += (
                    allocation[cid][source] * seconds / 3_600_000.0
                )
        if diag:
            pv_by_generator_w = diag.get("pv_by_generator_w") or {}
            for cid in self.all_consumers:
                for gid, power in (pv_by_generator_w.get(cid) or {}).items():
                    if cid in bucket.get("pv_by_generator_kwh", {}) and gid in bucket["pv_by_generator_kwh"][cid]:
                        bucket["pv_by_generator_kwh"][cid][gid] += max(0.0, float(power)) * seconds / 3_600_000.0
            for gid, power in (diag.get("generator_power") or {}).items():
                if gid in bucket.get("generator_power_kwh", {}) and power is not None:
                    bucket["generator_power_kwh"][gid] += max(0.0, float(power)) * seconds / 3_600_000.0
            balance = diag.get("balance_error_w")
            house_err = diag.get("house_net_error_w")
            if balance is not None:
                bucket["balance_ws"] += float(balance) * seconds
            if house_err is not None:
                bucket["house_net_error_ws"] += float(house_err) * seconds
            bucket["diag_coverage"] += seconds
            sync_spread = diag.get("sync_spread_s")
            sync_age = diag.get("sync_max_sample_age_s")
            if sync_spread is not None and sync_age is not None:
                spread_f = max(0.0, float(sync_spread))
                age_f = max(0.0, float(sync_age))
                bucket["sync_spread_ss"] += spread_f * seconds
                bucket["sync_max_age_ss"] += age_f * seconds
                bucket["sync_diag_coverage"] += seconds
                bucket["sync_spread_max_s"] = max(
                    float(bucket.get("sync_spread_max_s", 0.0)), spread_f
                )
                bucket["sync_sample_age_max_s"] = max(
                    float(bucket.get("sync_sample_age_max_s", 0.0)), age_f
                )

    def _record_from_bucket(self, bucket: dict[str, Any], duration: float) -> dict[str, Any]:
        diag_cov = float(bucket.get("diag_coverage", 0.0))
        sync_cov = float(bucket.get("sync_diag_coverage", 0.0))
        return {
            "start": int(round(float(bucket["start"]) * 1000)),
            "duration": int(duration),
            "coverage": round(min(max(float(bucket["coverage"]) / duration, 0.0), 1.0), 6),
            "balance_error_avg_w": (
                float(bucket["balance_ws"]) / diag_cov if diag_cov > 0 else None
            ),
            "house_net_error_avg_w": (
                float(bucket["house_net_error_ws"]) / diag_cov if diag_cov > 0 else None
            ),
            "sync_spread_avg_s": (
                float(bucket.get("sync_spread_ss", 0.0)) / sync_cov if sync_cov > 0 else None
            ),
            "sync_max_sample_age_avg_s": (
                float(bucket.get("sync_max_age_ss", 0.0)) / sync_cov if sync_cov > 0 else None
            ),
            "sync_spread_max_s": (
                float(bucket.get("sync_spread_max_s", 0.0)) if sync_cov > 0 else None
            ),
            "sync_sample_age_max_s": (
                float(bucket.get("sync_sample_age_max_s", 0.0)) if sync_cov > 0 else None
            ),
            "sync_diagnostic_coverage": (
                min(max(sync_cov / duration, 0.0), 1.0) if duration > 0 else 0.0
            ),
            "values": deepcopy(bucket["values"]),
            "energy_meter": deepcopy(bucket.get("energy_meter", {})),
            "generator_energy_meter": deepcopy(bucket.get("generator_energy_meter", {})),
            "generator_power_kwh": deepcopy(bucket.get("generator_power_kwh", {})),
            "pv_by_generator_kwh": deepcopy(bucket.get("pv_by_generator_kwh", {})),
        }

    def _close_bucket(self, resolution: str) -> None:
        if resolution == "15m":
            end_ts = float(self.bucket_15m["start"]) + 900.0
            if bool(self.bucket_15m.get("energy_calibration_allowed", True)):
                end_energy = self._calibrate_quarter_with_energy_meters(self.bucket_15m, end_ts)
            else:
                # One migration transition quarter: keep the old power-only
                # accounting but still establish exact meter baselines for the
                # next full quarter.
                end_energy = {cid: None for cid in self.all_consumers}
                for cid in self.energy_consumers:
                    end_energy[cid], _meta = self._energy_counter_at(cid, end_ts)
                self.bucket_15m["energy_meter"] = {
                    cid: {
                        "entity_id": self.energy_consumers[cid].get("energy_entity_id"),
                        "status": "power_fallback",
                        "reason": "upgrade_transition_quarter",
                        "power_integrated_kwh": float(self.bucket_15m["values"][cid]["total"]),
                        "meter_delta_kwh": None,
                        "deviation_percent": None,
                    }
                    for cid in self.energy_consumers
                }
            end_generator_energy = self._calibrate_generator_energy_meters(self.bucket_15m, end_ts)
            record = self._record_from_bucket(self.bucket_15m, 900.0)
            self.last_15m = record
            # Commit only the finalized, not-yet-accounted part of the quarter.
            # This preserves monotonic lifetime sensors across the v0.5 -> v0.6
            # accounting migration.
            committed = self.bucket_15m.get("lifetime_committed", {})
            for cid in self.all_consumers:
                for source in SOURCES:
                    final_value = max(0.0, float(self.bucket_15m["values"][cid][source]))
                    already = max(0.0, float(committed.get(cid, {}).get(source, 0.0)))
                    self.lifetime[cid][source] += max(0.0, final_value - already)
                for gid in self.all_generators:
                    self.pv_generator_lifetime[cid][gid] += max(
                        0.0, float(self.bucket_15m.get("pv_by_generator_kwh", {}).get(cid, {}).get(gid, 0.0))
                    )
            next_bucket = _new_bucket(end_ts, self.all_consumers, self.all_generators)
            next_bucket["energy_start"].update(end_energy)
            next_bucket["generator_energy_start"].update(end_generator_energy)
            self.bucket_15m = next_bucket
            self._dirty = True
            self._notify()
            # A completed billing interval is important enough to persist
            # immediately instead of waiting for the next five-minute save.
            self._schedule_save()
            return
        if resolution == "hour":
            self.bucket_hour = _new_bucket(self.bucket_hour["start"] + 3600.0, self.all_consumers, self.all_generators)
            return
        if resolution == "day":
            duration = self._next_day_start(self.bucket_day["start"]) - self.bucket_day["start"]
            self.bucket_day = _new_bucket(self._next_day_start(self.bucket_day["start"]), self.all_consumers, self.all_generators)

    @staticmethod
    def _quarter_start(ts: float) -> float:
        return math.floor(ts / 900.0) * 900.0

    @staticmethod
    def _hour_start(ts: float) -> float:
        return math.floor(ts / 3600.0) * 3600.0

    @staticmethod
    def _day_start(ts: float) -> float:
        local = dt_util.as_local(datetime.fromtimestamp(ts, UTC))
        midnight = datetime.combine(local.date(), time.min, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(midnight).timestamp()

    @staticmethod
    def _next_day_start(day_start_ts: float) -> float:
        local = dt_util.as_local(datetime.fromtimestamp(day_start_ts, UTC))
        next_date = local.date() + timedelta(days=1)
        midnight = datetime.combine(next_date, time.min, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        return dt_util.as_utc(midnight).timestamp()

    @property
    def consumer_labels(self) -> dict[str, str]:
        """Return all configured labels; inactive consumers remain historically visible."""
        return {cid: consumer["name"] for cid, consumer in self.all_consumers.items()}

    @property
    def consumer_metadata(self) -> dict[str, dict[str, Any]]:
        """Return dashboard-safe consumer metadata."""
        return {
            cid: {
                "id": cid,
                "name": item["name"],
                "entity_id": item["entity_id"],
                "role": item.get("role", "normal"),
                "enabled": bool(item.get("enabled", True)),
                "icon": item.get("icon", "mdi:flash"),
                "description": item.get("description", ""),
                "energy_entity_id": item.get("energy_entity_id"),
                "energy_mode": item.get("energy_mode", ENERGY_MODE_AUTO),
            }
            for cid, item in self.all_consumers.items()
        }

    @property
    def generator_metadata(self) -> dict[str, dict[str, Any]]:
        """Return dashboard-safe PV generator metadata."""
        return {
            gid: {
                "id": gid,
                "name": item["name"],
                "entity_id": item["entity_id"],
                "fallback_entity_id": item.get("fallback_entity_id"),
                "polarity": item.get("polarity", GENERATOR_POLARITY_POSITIVE),
                "fallback_polarity": item.get(
                    "fallback_polarity", GENERATOR_FALLBACK_POLARITY_SAME
                ),
                "role": item.get("role", GENERATOR_ROLE_MAIN_BUS),
                "consumer_id": item.get("consumer_id"),
                "enabled": bool(item.get("enabled", True)),
                "night_zero": bool(item.get("night_zero", True)),
                "max_age": float(item.get("max_age", 180.0)),
                "icon": item.get("icon", "mdi:solar-power"),
                "description": item.get("description", ""),
                "energy_entity_id": item.get("energy_entity_id"),
                "energy_mode": item.get("energy_mode", ENERGY_MODE_AUTO),
                "tariffs": normalize_tariffs(item.get("tariffs")),
            }
            for gid, item in self.all_generators.items()
        }

    def costs_for_record(self, record: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Calculate audit-friendly costs for one energy record.

        Prices are selected by the record's local calendar date. Tariff histories
        are append-only from the user's perspective: a later effective date does
        not alter the price used for earlier records. PV costs are only considered
        exact where PV consumption can be attributed to a configured generator.
        """
        start_ts = float(record.get("start", 0)) / 1000.0
        grid_price = tariff_price_at(self.grid_tariffs, start_ts)
        battery_price = tariff_price_at(self.battery_tariffs, start_ts)
        pv_rows = record.get("pv_by_generator_kwh", {}) or {}
        result: dict[str, dict[str, Any]] = {}
        for cid in self.all_consumers:
            values = record.get("values", {}).get(cid, {}) or {}
            total = max(0.0, float(values.get("total", 0.0)))
            grid_kwh = max(0.0, float(values.get("grid", 0.0)))
            battery_kwh = max(0.0, float(values.get("battery", 0.0)))
            pv_kwh = max(0.0, float(values.get("pv", 0.0)))
            grid_cost = grid_kwh * grid_price if grid_price is not None else 0.0
            battery_cost = battery_kwh * battery_price if battery_price is not None else 0.0
            priced_kwh = (grid_kwh if grid_price is not None else 0.0) + (battery_kwh if battery_price is not None else 0.0)
            pv_cost = 0.0
            pv_by_generator_cost: dict[str, float] = {}
            attributed_pv = 0.0
            row = pv_rows.get(cid, {}) if isinstance(pv_rows, dict) else {}
            if not isinstance(row, dict):
                row = {}
            for gid in self.all_generators:
                kwh = max(0.0, float(row.get(gid, 0.0) or 0.0))
                if kwh <= 0:
                    continue
                # Never price more PV by generator than the consumer's aggregate PV.
                remaining = max(0.0, pv_kwh - attributed_pv)
                kwh = min(kwh, remaining)
                if kwh <= 0:
                    break
                attributed_pv += kwh
                price = tariff_price_at(self.all_generators[gid].get("tariffs"), start_ts)
                if price is not None:
                    c = kwh * price
                    pv_by_generator_cost[gid] = c
                    pv_cost += c
                    priced_kwh += kwh
            unpriced_kwh = max(0.0, total - min(total, priced_kwh))
            result[cid] = {
                "total": grid_cost + pv_cost + battery_cost,
                "grid": grid_cost,
                "pv": pv_cost,
                "battery": battery_cost,
                "pv_by_generator": pv_by_generator_cost,
                "priced_kwh": min(total, priced_kwh),
                "unpriced_kwh": unpriced_kwh,
                "coverage": (min(total, priced_kwh) / total) if total > 1e-12 else 1.0,
                "complete": unpriced_kwh <= 1e-9,
                "grid_price_per_kwh": grid_price,
                "battery_price_per_kwh": battery_price,
            }
        return result

    def decorate_record_costs(self, record: dict[str, Any]) -> dict[str, Any]:
        record["costs"] = self.costs_for_record(record)
        record["currency"] = self.currency
        return record

    @property
    def battery_visible(self) -> bool:
        """Return whether battery data should remain visible."""
        return self.battery_enabled or any(
            self.lifetime.get(cid, {}).get("battery", 0.0) > 0 for cid in self.all_consumers
        )

    def get_summary(self) -> dict[str, Any]:
        today = deepcopy(self.bucket_day["values"])
        coverage = 0.0
        duration = datetime.now(UTC).timestamp() - float(self.bucket_day["start"])
        if duration > 0:
            coverage = min(max(float(self.bucket_day["coverage"]) / duration, 0.0), 1.0)
        return {
            "consumers": self.consumer_labels,
            "consumer_metadata": self.consumer_metadata,
            "groups": deepcopy(self.groups),
            "generators": self.generator_metadata,
            "lifetime": deepcopy(self.lifetime),
            "pv_generator_lifetime": deepcopy(self.pv_generator_lifetime),
            "today": today,
            "today_start": int(float(self.bucket_day["start"]) * 1000),
            "today_coverage": coverage,
            "last_15m": deepcopy(self.last_15m),
            "current_15m": self.decorate_record_costs({
                "start": int(float(self.bucket_15m["start"]) * 1000),
                "duration": 900,
                "coverage_seconds": float(self.bucket_15m["coverage"]),
                "coverage": min(max(float(self.bucket_15m["coverage"]) / 900.0, 0.0), 1.0),
                "values": deepcopy(self.bucket_15m["values"]),
                "pv_by_generator_kwh": deepcopy(self.bucket_15m.get("pv_by_generator_kwh", {})),
            }),
            "pricing": {
                "currency": self.currency,
                "grid_tariffs": deepcopy(self.grid_tariffs),
                "battery_tariffs": deepcopy(self.battery_tariffs),
            },
            "live": deepcopy(self._last_diag),
            "battery_enabled": self.battery_enabled,
            "battery_visible": self.battery_visible,
            "sample_interval": self.sample_interval,
        }
