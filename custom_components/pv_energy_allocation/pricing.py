"""Tariff normalization and historical price lookup for WattWer."""
from __future__ import annotations

from datetime import UTC, date, datetime, time
import math
from typing import Any

from homeassistant.util import dt as dt_util


def normalize_tariffs(raw: Any) -> list[dict[str, Any]]:
    """Normalize a tariff history to unique local effective dates.

    Tariffs are deliberately date based. An entry becomes effective at local
    midnight in the Home Assistant timezone and remains active until the next
    entry. This makes supplier/PV price changes audit-friendly and keeps older
    prices intact when a new future tariff is added.
    """
    if not isinstance(raw, list):
        return []
    by_date: dict[str, float] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        valid_from = str(item.get("valid_from") or "").strip()
        try:
            parsed = date.fromisoformat(valid_from)
            price = float(item.get("price_per_kwh"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price < 0:
            continue
        by_date[parsed.isoformat()] = price
    return [
        {"valid_from": key, "price_per_kwh": by_date[key]}
        for key in sorted(by_date)
    ]


def tariff_price_at(raw: Any, timestamp: float) -> float | None:
    """Return the tariff active at timestamp, or None when not configured."""
    tariffs = normalize_tariffs(raw)
    if not tariffs:
        return None
    local_day = dt_util.as_local(datetime.fromtimestamp(timestamp, UTC)).date().isoformat()
    price: float | None = None
    for item in tariffs:
        if item["valid_from"] <= local_day:
            price = float(item["price_per_kwh"])
        else:
            break
    return price


def tariff_boundary_ts(valid_from: str) -> float | None:
    """Return UTC timestamp for a local effective-date boundary."""
    try:
        day = date.fromisoformat(valid_from)
    except ValueError:
        return None
    local = datetime.combine(day, time.min, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    return dt_util.as_utc(local).timestamp()
