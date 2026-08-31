"""Constants for WattWer."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "pv_energy_allocation"  # Never change: keeps existing Config Entries/entities.
NAME = "WattWer"
VERSION = "0.6.2"
PLATFORMS = [Platform.SENSOR]

# Core metering configuration.
CONF_GRID_IMPORT = "grid_import"
CONF_GRID_EXPORT = "grid_export"
CONF_HOUSE_NET = "house_net"
CONF_BACKGROUND_LOADS = "background_loads"
CONF_BATTERY_CHARGE = "battery_charge"
CONF_BATTERY_DISCHARGE = "battery_discharge"
CONF_GRID_TARIFFS = "grid_tariffs"
CONF_BATTERY_TARIFFS = "battery_tariffs"
CONF_CURRENCY = "currency"

# Structured, stable configuration models.
CONF_CONSUMERS = "consumers"
CONF_GROUPS = "groups"
CONF_GENERATORS = "generators"

# Optional hardware energy counter per consumer. Power remains authoritative for
# source allocation; the cumulative energy counter can calibrate interval kWh.
ENERGY_MODE_AUTO = "auto"
ENERGY_MODE_POWER_ONLY = "power_only"
ENERGY_MODE_METER_PREFERRED = "meter_preferred"
ENERGY_MODES = (ENERGY_MODE_AUTO, ENERGY_MODE_POWER_ONLY, ENERGY_MODE_METER_PREFERRED)

# Runtime settings.
CONF_SAMPLE_INTERVAL = "sample_interval"
CONF_MAX_AGE = "max_age"
CONF_DEADBAND = "deadband"
CONF_QUARTER_RETENTION_DAYS = "quarter_retention_days"
CONF_HOUR_RETENTION_DAYS = "hour_retention_days"
CONF_SYNC_ENABLED = "sync_enabled"
CONF_SYNC_DELAY = "sync_delay"
CONF_SYNC_BUFFER = "sync_buffer"
CONF_SYNC_MAX_SAMPLE_AGE = "sync_max_sample_age"
CONF_ADAPTIVE_FRESHNESS = "adaptive_freshness"
CONF_ADAPTIVE_HARD_TIMEOUT = "adaptive_hard_timeout"

# Legacy keys from WattWer <= 0.4.x. They intentionally remain supported for
# migration only. No installation-specific entity IDs are shipped as defaults.
LEGACY_CONF_MAIN_PV = "main_pv"
LEGACY_CONF_BKW = "bkw"
LEGACY_CONF_DTU_BKW = "dtu_bkw"
LEGACY_CONF_AOR = "aor"
LEGACY_CONF_HEATPUMP = "heatpump"
LEGACY_CONF_GENERAL = "general"
LEGACY_CONF_FW_GROSS = "fw_gross"
LEGACY_CONF_SHELLY = "shelly"
LEGACY_CONF_EXTRA_CONSUMERS = "extra_consumers"

# Stable legacy consumer IDs are part of existing entity unique_ids and must
# never change. These are opaque compatibility identifiers, not defaults.
LEGACY_CONSUMER_SLOTS: dict[str, tuple[str, str]] = {
    "aor": (LEGACY_CONF_AOR, "normal"),
    "heatpump": (LEGACY_CONF_HEATPUMP, "normal"),
    "general": (LEGACY_CONF_GENERAL, "normal"),
    "fw": (LEGACY_CONF_FW_GROSS, "normal"),
    "shelly": (LEGACY_CONF_SHELLY, "normal"),
}

DEFAULTS = {
    CONF_BACKGROUND_LOADS: [],
    CONF_SAMPLE_INTERVAL: 5,
    CONF_MAX_AGE: 30,
    CONF_DEADBAND: 0.0,
    CONF_QUARTER_RETENTION_DAYS: 10,
    CONF_HOUR_RETENTION_DAYS: 730,
    CONF_SYNC_ENABLED: True,
    CONF_SYNC_DELAY: 5.0,
    CONF_SYNC_BUFFER: 30.0,
    CONF_SYNC_MAX_SAMPLE_AGE: 10.0,
    CONF_ADAPTIVE_FRESHNESS: True,
    CONF_ADAPTIVE_HARD_TIMEOUT: 60.0,
    CONF_GRID_TARIFFS: [],
    CONF_BATTERY_TARIFFS: [],
    CONF_CURRENCY: "EUR",
}

# Generator roles.
GENERATOR_ROLE_MAIN_BUS = "main_bus"
GENERATOR_ROLE_DIRECT_CONSUMER = "direct_consumer"
GENERATOR_ROLES = (GENERATOR_ROLE_MAIN_BUS, GENERATOR_ROLE_DIRECT_CONSUMER)
DEFAULT_GENERATOR_MAX_AGE = 180

# PV generator sign conventions. A generator's primary and fallback sensor may
# use different sign conventions (e.g. a bidirectional Shelly reports export as
# negative while a DTU reports generation as positive).
GENERATOR_POLARITY_POSITIVE = "positive"
GENERATOR_POLARITY_NEGATIVE = "negative"
GENERATOR_POLARITIES = (GENERATOR_POLARITY_POSITIVE, GENERATOR_POLARITY_NEGATIVE)
GENERATOR_FALLBACK_POLARITY_SAME = "same"
GENERATOR_FALLBACK_POLARITIES = (
    GENERATOR_FALLBACK_POLARITY_SAME,
    GENERATOR_POLARITY_POSITIVE,
    GENERATOR_POLARITY_NEGATIVE,
)
CADENCE_WINDOW = 60
CADENCE_MIN_SAMPLES = 6

SOURCES = ("total", "pv", "grid", "battery")
SOURCE_LABELS = {
    "total": "Gesamt",
    "pv": "PV",
    "grid": "Netz",
    "battery": "Batterie",
}

PANEL_URL = "pv-energy-allocation"
PANEL_ELEMENT = "pv-energy-allocation-panel"
CONFIG_PANEL_URL = "wattwer-config"
CONFIG_PANEL_ELEMENT = "wattwer-config-panel"
PANEL_STATIC_URL = "/pv_energy_allocation_static"

STORAGE_VERSION = 1
BACKFILL_STORAGE_VERSION = 1
STORAGE_SAVE_INTERVAL = 300
LIVE_DASHBOARD_REFRESH_SECONDS = 5
MAX_BACKFILL_DAYS_PER_RUN = 31
