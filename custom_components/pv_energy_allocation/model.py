"""Stable configuration model helpers for WattWer."""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from .const import (
    CONF_CONSUMERS,
    CONF_GENERATORS,
    CONF_GROUPS,
    DEFAULT_GENERATOR_MAX_AGE,
    GENERATOR_ROLE_DIRECT_CONSUMER,
    GENERATOR_ROLE_MAIN_BUS,
    GENERATOR_ROLES,
    LEGACY_CONF_BKW,
    LEGACY_CONF_DTU_BKW,
    LEGACY_CONF_EXTRA_CONSUMERS,
    LEGACY_CONF_MAIN_PV,
    LEGACY_CONSUMER_SLOTS,
)


def _slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"^sensor\.", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    return value[:32] or "item"


def legacy_extra_consumer_id(entity_id: str) -> str:
    """Match the deterministic ID used by WattWer 0.2.x."""
    digest = hashlib.sha1(entity_id.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"extra_{digest}"


def new_consumer_id(entity_id: str) -> str:
    """Create a stable consumer ID independent from future entity/name changes."""
    return f"consumer_{_slug(entity_id)}_{uuid.uuid4().hex[:8]}"


def new_group_id(name: str) -> str:
    """Create a stable presentation-group ID."""
    return f"group_{_slug(name)}_{uuid.uuid4().hex[:8]}"


def new_generator_id(entity_id: str) -> str:
    """Create a stable PV generator ID independent from source entity changes."""
    return f"generator_{_slug(entity_id)}_{uuid.uuid4().hex[:8]}"


def normalize_consumers(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return stable consumer model, including compatibility with <=0.4.x."""
    raw = cfg.get(CONF_CONSUMERS)
    if isinstance(raw, list) and raw:
        result: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_entities: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            entity_id = str(item.get("entity_id") or "").strip()
            if not cid or not entity_id or cid in seen_ids or entity_id in seen_entities:
                continue
            result.append(
                {
                    "id": cid,
                    "entity_id": entity_id,
                    "name": str(item.get("name") or entity_id).strip() or entity_id,
                    # Old role=fw remains accepted but generator topology is now
                    # authoritative. Keeping it is harmless and migration-safe.
                    "role": str(item.get("role") or "normal"),
                    "enabled": bool(item.get("enabled", True)),
                    "icon": str(item.get("icon") or "mdi:flash").strip() or "mdi:flash",
                    "description": str(item.get("description") or "").strip(),
                }
            )
            seen_ids.add(cid)
            seen_entities.add(entity_id)
        if result:
            return result

    # Legacy fallback. The migration in __init__.py normally materializes this
    # into CONF_CONSUMERS before the controller starts. No private defaults are
    # embedded here; only values already stored in the user's Config Entry are read.
    result: list[dict[str, Any]] = []
    seen_entities: set[str] = set()
    for cid, (conf_key, old_role) in LEGACY_CONSUMER_SLOTS.items():
        entity_id = str(cfg.get(conf_key) or "").strip()
        if not entity_id or entity_id in seen_entities:
            continue
        result.append(
            {
                "id": cid,
                "entity_id": entity_id,
                "name": entity_id,
                "role": old_role,
                "enabled": True,
                "icon": "mdi:flash",
                "description": "",
            }
        )
        seen_entities.add(entity_id)

    for entity_id in cfg.get(LEGACY_CONF_EXTRA_CONSUMERS) or []:
        entity_id = str(entity_id).strip()
        if not entity_id or entity_id in seen_entities:
            continue
        result.append(
            {
                "id": legacy_extra_consumer_id(entity_id),
                "entity_id": entity_id,
                "name": entity_id,
                "role": "normal",
                "enabled": True,
                "icon": "mdi:flash",
                "description": "",
            }
        )
        seen_entities.add(entity_id)
    return result


def normalize_generators(
    cfg: dict[str, Any], valid_consumers: set[str]
) -> list[dict[str, Any]]:
    """Return stable PV generator model, upgrading old main-PV/BKW settings."""
    raw = cfg.get(CONF_GENERATORS)
    if isinstance(raw, list):
        result: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        seen_entities: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            gid = str(item.get("id") or "").strip()
            entity_id = str(item.get("entity_id") or "").strip()
            if not gid or not entity_id or gid in seen_ids or entity_id in seen_entities:
                continue
            role = str(item.get("role") or GENERATOR_ROLE_MAIN_BUS)
            if role not in GENERATOR_ROLES:
                role = GENERATOR_ROLE_MAIN_BUS
            consumer_id = str(item.get("consumer_id") or "").strip() or None
            if role == GENERATOR_ROLE_DIRECT_CONSUMER and consumer_id not in valid_consumers:
                role = GENERATOR_ROLE_MAIN_BUS
                consumer_id = None
            fallback = str(item.get("fallback_entity_id") or "").strip() or None
            try:
                max_age = max(5.0, min(3600.0, float(item.get("max_age", DEFAULT_GENERATOR_MAX_AGE))))
            except (TypeError, ValueError):
                max_age = float(DEFAULT_GENERATOR_MAX_AGE)
            result.append(
                {
                    "id": gid,
                    "entity_id": entity_id,
                    "fallback_entity_id": fallback,
                    "name": str(item.get("name") or entity_id).strip() or entity_id,
                    "role": role,
                    "consumer_id": consumer_id,
                    "enabled": bool(item.get("enabled", True)),
                    "night_zero": bool(item.get("night_zero", True)),
                    "max_age": max_age,
                    "icon": str(item.get("icon") or "mdi:solar-power").strip() or "mdi:solar-power",
                    "description": str(item.get("description") or "").strip(),
                }
            )
            seen_ids.add(gid)
            seen_entities.add(entity_id)
        return result

    # Legacy migration fallback. Uses values stored in the Config Entry, never
    # installation-specific defaults from the source repository.
    result: list[dict[str, Any]] = []
    main_pv = str(cfg.get(LEGACY_CONF_MAIN_PV) or "").strip()
    if main_pv:
        result.append(
            {
                "id": "legacy_main_pv",
                "entity_id": main_pv,
                "fallback_entity_id": None,
                "name": "PV-Erzeuger",
                "role": GENERATOR_ROLE_MAIN_BUS,
                "consumer_id": None,
                "enabled": True,
                "night_zero": True,
                "max_age": float(DEFAULT_GENERATOR_MAX_AGE),
                "icon": "mdi:solar-power",
                "description": "Aus älterer WattWer-Konfiguration übernommen",
            }
        )

    local_pv = str(cfg.get(LEGACY_CONF_BKW) or "").strip()
    if local_pv:
        target = "fw" if "fw" in valid_consumers else None
        fallback = str(cfg.get(LEGACY_CONF_DTU_BKW) or "").strip() or None
        result.append(
            {
                "id": "legacy_local_pv",
                "entity_id": local_pv,
                "fallback_entity_id": fallback,
                "name": "Lokaler PV-Erzeuger",
                "role": GENERATOR_ROLE_DIRECT_CONSUMER if target else GENERATOR_ROLE_MAIN_BUS,
                "consumer_id": target,
                "enabled": True,
                "night_zero": True,
                "max_age": float(DEFAULT_GENERATOR_MAX_AGE),
                "icon": "mdi:solar-panel",
                "description": "Aus älterer WattWer-Konfiguration übernommen",
            }
        )
    return result


def normalize_groups(cfg: dict[str, Any], valid_consumers: set[str]) -> list[dict[str, Any]]:
    """Return valid non-overlapping presentation groups."""
    raw = cfg.get(CONF_GROUPS)
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    assigned: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        gid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        members = [str(x) for x in item.get("members", []) if str(x) in valid_consumers]
        members = [x for x in dict.fromkeys(members) if x not in assigned]
        if not gid or not name or not members or gid in seen_ids:
            continue
        result.append({"id": gid, "name": name, "members": members})
        seen_ids.add(gid)
        assigned.update(members)
    return result


def validate_consumer_config(consumers: list[dict[str, Any]], groups: list[dict[str, Any]]) -> str | None:
    """Validate consumers/groups; return error key or None."""
    if not consumers:
        return "at_least_one_consumer"
    ids: set[str] = set()
    entities: set[str] = set()
    for item in consumers:
        cid = str(item.get("id") or "").strip()
        entity_id = str(item.get("entity_id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not cid or not entity_id or not name:
            return "consumer_fields_required"
        if cid in ids or entity_id in entities:
            return "consumer_duplicate"
        ids.add(cid)
        entities.add(entity_id)

    group_ids: set[str] = set()
    assigned: set[str] = set()
    for group in groups:
        gid = str(group.get("id") or "").strip()
        name = str(group.get("name") or "").strip()
        members = [str(x) for x in group.get("members", [])]
        if not gid or not name or not members:
            return "group_fields_required"
        if gid in group_ids:
            return "group_duplicate"
        group_ids.add(gid)
        for member in members:
            if member not in ids:
                return "group_unknown_member"
            if member in assigned:
                return "group_member_duplicate"
            assigned.add(member)
    return None


def validate_generator_config(
    generators: list[dict[str, Any]], consumers: list[dict[str, Any]]
) -> str | None:
    """Validate generic PV generation sources."""
    valid_consumers = {str(x.get("id")) for x in consumers}
    ids: set[str] = set()
    entities: set[str] = set()
    for item in generators:
        gid = str(item.get("id") or "").strip()
        entity_id = str(item.get("entity_id") or "").strip()
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or GENERATOR_ROLE_MAIN_BUS)
        fallback = str(item.get("fallback_entity_id") or "").strip()
        if not gid or not entity_id or not name:
            return "generator_fields_required"
        if gid in ids or entity_id in entities:
            return "generator_duplicate"
        if fallback and (fallback == entity_id or fallback in entities):
            return "generator_fallback_same"
        if role not in GENERATOR_ROLES:
            return "generator_invalid_role"
        if role == GENERATOR_ROLE_DIRECT_CONSUMER:
            if str(item.get("consumer_id") or "") not in valid_consumers:
                return "generator_consumer_required"
        ids.add(gid)
        entities.add(entity_id)
        if fallback:
            entities.add(fallback)
    return None
