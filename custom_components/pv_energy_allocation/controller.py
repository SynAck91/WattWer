"""Sampling, allocation and persistence for PV Energy Allocation."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, time, timedelta
import asyncio
import logging
import math
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BACKGROUND_LOADS,
    CONF_BATTERY_CHARGE,
    CONF_BATTERY_DISCHARGE,
    CONF_DEADBAND,
    CONF_GENERATORS,
    CONF_GRID_EXPORT,
    CONF_GRID_IMPORT,
    CONF_HOUR_RETENTION_DAYS,
    CONF_HOUSE_NET,
    CONF_MAX_AGE,
    CONF_QUARTER_RETENTION_DAYS,
    CONF_SAMPLE_INTERVAL,
    DEFAULTS,
    DOMAIN,
    GENERATOR_ROLE_DIRECT_CONSUMER,
    GENERATOR_ROLE_MAIN_BUS,
    SOURCES,
    STORAGE_SAVE_INTERVAL,
    STORAGE_VERSION,
)
from .model import normalize_consumers, normalize_generators, normalize_groups

_LOGGER = logging.getLogger(__name__)


def _empty_values(consumer_ids) -> dict[str, dict[str, float]]:
    return {cid: {source: 0.0 for source in SOURCES} for cid in consumer_ids}


def _new_bucket(start: float, consumer_ids) -> dict[str, Any]:
    return {
        "start": float(start),
        "coverage": 0.0,
        "values": _empty_values(consumer_ids),
        "balance_ws": 0.0,
        "house_net_error_ws": 0.0,
        "diag_coverage": 0.0,
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
        self.q_retention_days = int(
            self.cfg.get(CONF_QUARTER_RETENTION_DAYS, DEFAULTS[CONF_QUARTER_RETENTION_DAYS])
        )
        self.h_retention_days = int(
            self.cfg.get(CONF_HOUR_RETENTION_DAYS, DEFAULTS[CONF_HOUR_RETENTION_DAYS])
        )
        self.battery_enabled = bool(
            self.cfg.get(CONF_BATTERY_CHARGE) and self.cfg.get(CONF_BATTERY_DISCHARGE)
        )

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
        self.groups = normalize_groups(self.cfg, set(self.all_consumers))
        generator_list = normalize_generators(self.cfg, set(self.all_consumers))
        self.all_generators: dict[str, dict[str, Any]] = {
            item["id"]: item for item in generator_list
        }
        self.generators: dict[str, dict[str, Any]] = {
            gid: item for gid, item in self.all_generators.items() if item.get("enabled", True)
        }

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
        }

        self.lifetime = _empty_values(self.all_consumers)
        self.last_15m: dict[str, Any] | None = None
        self.coverage_lifetime_s = 0.0
        now = datetime.now(UTC).timestamp()
        self.bucket_15m = _new_bucket(self._quarter_start(now), self.all_consumers)
        self.bucket_hour = _new_bucket(self._hour_start(now), self.all_consumers)
        self.bucket_day = _new_bucket(self._day_start(now), self.all_consumers)

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
            "last_15m": deepcopy(self.last_15m),
            "coverage_lifetime_s": self.coverage_lifetime_s,
            "bucket_15m": deepcopy(self.bucket_15m),
            "bucket_hour": deepcopy(self.bucket_hour),
            "bucket_day": deepcopy(self.bucket_day),
            "last_sample_ts": self._last_sample_ts,
        }

    async def async_start(self) -> None:
        """Load persisted state and start periodic sampling."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._restore(stored)

        now_ts = datetime.now(UTC).timestamp()
        if self._last_sample_ts is not None and now_ts > self._last_sample_ts:
            # Never invent energy for a Home Assistant outage. We do close elapsed
            # buckets so their coverage explicitly reports the missing interval.
            self._advance_interval(self._last_sample_ts, now_ts, None, None)
        self._last_sample_ts = now_ts
        self._last_allocation, self._last_diag = self._calculate_snapshot(datetime.now(UTC))

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

        self.last_15m = stored.get("last_15m") if isinstance(stored.get("last_15m"), dict) else None
        try:
            self.coverage_lifetime_s = max(0.0, float(stored.get("coverage_lifetime_s", 0.0)))
        except (TypeError, ValueError):
            self.coverage_lifetime_s = 0.0

        now_ts = datetime.now(UTC).timestamp()
        self.bucket_15m = self._restore_bucket(stored.get("bucket_15m"), self._quarter_start(now_ts))
        self.bucket_hour = self._restore_bucket(stored.get("bucket_hour"), self._hour_start(now_ts))
        self.bucket_day = self._restore_bucket(stored.get("bucket_day"), self._day_start(now_ts))
        last_ts = stored.get("last_sample_ts")
        try:
            self._last_sample_ts = float(last_ts) if last_ts is not None else None
        except (TypeError, ValueError):
            self._last_sample_ts = None

    def _restore_bucket(self, raw: Any, fallback_start: float) -> dict[str, Any]:
        if not isinstance(raw, dict) or "start" not in raw:
            return _new_bucket(fallback_start, self.all_consumers)
        bucket = _new_bucket(float(raw.get("start", fallback_start)), self.all_consumers)
        bucket["coverage"] = max(0.0, float(raw.get("coverage", 0.0)))
        bucket["balance_ws"] = float(raw.get("balance_ws", 0.0))
        bucket["house_net_error_ws"] = float(raw.get("house_net_error_ws", 0.0))
        bucket["diag_coverage"] = max(0.0, float(raw.get("diag_coverage", 0.0)))
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
        now_utc = dt_util.as_utc(now)
        now_ts = now_utc.timestamp()
        if self._last_sample_ts is None:
            self._last_sample_ts = now_ts
            self._last_allocation, self._last_diag = self._calculate_snapshot(now_utc)
            return

        dt_s = now_ts - self._last_sample_ts
        # A very large event-loop gap should not turn stale power into fictitious
        # energy. The same max_age used for source freshness is the upper bound.
        if dt_s <= 0:
            self._last_sample_ts = now_ts
            return
        if dt_s > self.max_age:
            self._advance_interval(self._last_sample_ts, now_ts, None, None)
        else:
            self._advance_interval(
                self._last_sample_ts,
                now_ts,
                self._last_allocation,
                self._last_diag if self._last_allocation is not None else None,
            )

        self._last_sample_ts = now_ts
        self._last_allocation, self._last_diag = self._calculate_snapshot(now_utc)

    def _read_power(
        self,
        entity_id: str | None,
        now: datetime,
        *,
        required: bool,
        max_age: float | None = None,
    ) -> tuple[float | None, str | None]:
        """Read one power sensor with freshness validation.

        Optional diagnostics must never invalidate the allocation.  A configured
        optional entity may legitimately be unavailable (for example a PV
        inverter that powers down at night), so failures are only returned for
        required inputs.
        """
        if not entity_id:
            return (None, None if not required else "<not configured>")
        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return (None, entity_id if required else None)
        value = _finite_float(state.state)
        if value is None:
            return (None, entity_id if required else None)
        freshness = self.max_age if max_age is None else max_age
        age = (now - dt_util.as_utc(state.last_reported)).total_seconds()
        if age > freshness:
            return (None, entity_id if required else None)
        return value, None

    def _power_candidate(
        self, entity_id: str | None, now: datetime, *, max_age: float
    ) -> tuple[float | None, float | None]:
        """Return a numeric power value and its report age if still usable."""
        if not entity_id:
            return None, None
        state: State | None = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None, None
        value = _finite_float(state.state)
        if value is None:
            return None, None
        age = max(0.0, (now - dt_util.as_utc(state.last_reported)).total_seconds())
        if age > max_age:
            return None, age
        return value, age

    def _sun_below_horizon(self) -> bool:
        """Return True only when Home Assistant positively knows it is night."""
        sun = self.hass.states.get("sun.sun")
        return sun is not None and sun.state == "below_horizon"

    def _read_generator_resilient(
        self, generator: dict[str, Any], now: datetime
    ) -> tuple[float | None, str, list[str], str | None]:
        """Read one PV generator with fallback and optional night-zero handling."""
        try:
            grace = max(self.max_age, float(generator.get("max_age", 180.0)))
        except (TypeError, ValueError):
            grace = max(self.max_age, 180.0)

        candidates: list[tuple[float, float, str]] = []
        primary_id = str(generator.get("entity_id") or "").strip()
        fallback_id = str(generator.get("fallback_entity_id") or "").strip()
        primary, primary_age = self._power_candidate(primary_id, now, max_age=grace)
        if primary is not None and primary_age is not None:
            candidates.append((primary_age, primary, primary_id))
        fallback, fallback_age = self._power_candidate(fallback_id, now, max_age=grace)
        if fallback is not None and fallback_age is not None:
            candidates.append((fallback_age, fallback, fallback_id))

        if candidates:
            _age, value, source = min(candidates, key=lambda item: item[0])
            if fallback_id and source == fallback_id:
                return value, "fallback_generator", [
                    f"{generator.get('name', primary_id)}: Fallback-Sensor verwendet"
                ], source
            return value, "ok", [], source

        if bool(generator.get("night_zero", True)) and self._sun_below_horizon():
            return 0.0, "fallback_night_zero", [
                f"{generator.get('name', primary_id)}: nachts ohne Messwert als 0 W behandelt"
            ], None

        return None, "degraded_generator", [
            f"{generator.get('name', primary_id)}: Erzeugungsleistung unbekannt"
        ], None

    def _positive(self, value: float) -> float:
        if value <= self.deadband:
            return 0.0
        return value

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
        ids.extend(str(x) for x in (self.cfg.get(CONF_BACKGROUND_LOADS) or []))
        for generator in self.generators.values():
            ids.append(str(generator.get("entity_id") or ""))
            ids.append(str(generator.get("fallback_entity_id") or ""))
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

        required_ids = {
            "grid_import": self.cfg.get(CONF_GRID_IMPORT),
            "grid_export": self.cfg.get(CONF_GRID_EXPORT),
        }
        for cid, consumer in self.consumers.items():
            required_ids[cid] = consumer["entity_id"]

        values: dict[str, float] = {}
        for key, entity_id in required_ids.items():
            val, bad = self._read_power(entity_id, now, required=True)
            if bad:
                stale.append(bad)
            elif val is not None:
                values[key] = val

        backgrounds: list[float] = []
        for entity_id in list(self.cfg.get(CONF_BACKGROUND_LOADS) or []):
            val, bad = self._read_power(entity_id, now, required=True)
            if bad:
                stale.append(bad)
            elif val is not None:
                backgrounds.append(self._positive(val))

        generator_readings: dict[str, dict[str, Any]] = {}
        for gid, generator in self.generators.items():
            value, gen_quality, notes, source_entity = self._read_generator_resilient(generator, now)
            known = value is not None
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
            charge, bad_charge = self._read_power(
                self.cfg.get(CONF_BATTERY_CHARGE), now, required=True
            )
            discharge, bad_discharge = self._read_power(
                self.cfg.get(CONF_BATTERY_DISCHARGE), now, required=True
            )
            if bad_charge:
                stale.append(bad_charge)
            if bad_discharge:
                stale.append(bad_discharge)
            if charge is not None:
                battery_charge = self._positive(charge)
            if discharge is not None:
                battery_discharge = self._positive(discharge)

        if stale:
            return None, {
                **self._last_diag,
                "valid": False,
                "quality": "invalid",
                "quality_notes": quality_notes,
                "stale_entities": sorted(set(stale)),
            }

        house_net = None
        if self.cfg.get(CONF_HOUSE_NET):
            house_net, _ = self._read_power(self.cfg.get(CONF_HOUSE_NET), now, required=False)

        return self._compute_allocation(
            values,
            backgrounds,
            generator_readings,
            battery_charge,
            battery_discharge,
            house_net,
            quality=quality,
            quality_notes=quality_notes,
        )

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
        generator_power: dict[str, float | None] = {}
        generator_source_entity: dict[str, str | None] = {}
        main_bus_pv_available = 0.0
        all_generation_known = True
        local_generator_full_power = 0.0

        # Local generators first cover their electrically linked consumer. Any
        # surplus flows to the shared bus. Main-bus generators feed the shared bus.
        for gid, generator in self.generators.items():
            reading = generator_readings.get(gid, {})
            known = bool(reading.get("known", False))
            raw_value = float(reading.get("value", 0.0)) if known else 0.0
            power = self._positive(raw_value) if known else 0.0
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
                    main_bus_pv_available += max(power - direct, 0.0)
                    local_generator_full_power += power
                else:
                    main_bus_pv_available += power
            else:
                main_bus_pv_available += power

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
                for cid in self.all_consumers:
                    for source in SOURCES:
                        kwh = allocation[cid][source] * seconds / 3_600_000.0
                        self.lifetime[cid][source] += kwh
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
            balance = diag.get("balance_error_w")
            house_err = diag.get("house_net_error_w")
            if balance is not None:
                bucket["balance_ws"] += float(balance) * seconds
            if house_err is not None:
                bucket["house_net_error_ws"] += float(house_err) * seconds
            bucket["diag_coverage"] += seconds

    def _record_from_bucket(self, bucket: dict[str, Any], duration: float) -> dict[str, Any]:
        diag_cov = float(bucket.get("diag_coverage", 0.0))
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
            "values": deepcopy(bucket["values"]),
        }

    def _close_bucket(self, resolution: str) -> None:
        if resolution == "15m":
            record = self._record_from_bucket(self.bucket_15m, 900.0)
            self.last_15m = record
            self.bucket_15m = _new_bucket(self.bucket_15m["start"] + 900.0, self.all_consumers)
            self._dirty = True
            self._notify()
            # A completed billing interval is important enough to persist
            # immediately instead of waiting for the next five-minute save.
            self._schedule_save()
            return
        if resolution == "hour":
            self.bucket_hour = _new_bucket(self.bucket_hour["start"] + 3600.0, self.all_consumers)
            return
        if resolution == "day":
            duration = self._next_day_start(self.bucket_day["start"]) - self.bucket_day["start"]
            self.bucket_day = _new_bucket(self._next_day_start(self.bucket_day["start"]), self.all_consumers)

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
                "role": item.get("role", GENERATOR_ROLE_MAIN_BUS),
                "consumer_id": item.get("consumer_id"),
                "enabled": bool(item.get("enabled", True)),
                "night_zero": bool(item.get("night_zero", True)),
                "max_age": float(item.get("max_age", 180.0)),
                "icon": item.get("icon", "mdi:solar-power"),
                "description": item.get("description", ""),
            }
            for gid, item in self.all_generators.items()
        }

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
            "today": today,
            "today_start": int(float(self.bucket_day["start"]) * 1000),
            "today_coverage": coverage,
            "last_15m": deepcopy(self.last_15m),
            "current_15m": {
                "start": int(float(self.bucket_15m["start"]) * 1000),
                "coverage_seconds": float(self.bucket_15m["coverage"]),
                "values": deepcopy(self.bucket_15m["values"]),
            },
            "live": deepcopy(self._last_diag),
            "battery_enabled": self.battery_enabled,
            "battery_visible": self.battery_visible,
            "sample_interval": self.sample_interval,
        }
