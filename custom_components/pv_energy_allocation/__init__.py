"""PV Energy Allocation integration."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONFIG_PANEL_ELEMENT,
    CONFIG_PANEL_URL,
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_STATIC_URL,
    PANEL_URL,
    PLATFORMS,
    STORAGE_VERSION,
    VERSION,
)
from .controller import PVAllocationController
from .model import normalize_consumers, normalize_generators, normalize_groups
from .const import CONF_CONSUMERS, CONF_GENERATORS, CONF_GROUPS
from .backfill import BackfillArchive
from .websocket import async_setup_websocket


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up static frontend assets and WebSocket API."""
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("_frontend_static_registered"):
        frontend_dir = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(frontend_dir), False)]
        )
        hass.data[DOMAIN]["_frontend_static_registered"] = True
    if not hass.data[DOMAIN].get("_websocket_registered"):
        async_setup_websocket(hass)
        hass.data[DOMAIN]["_websocket_registered"] = True
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy WattWer entries without changing historical identities."""
    if entry.version >= 2:
        return True

    merged = {**entry.data, **entry.options}
    consumers = normalize_consumers(merged)
    # Improve legacy display names from the live entity registry while keeping
    # the old stable consumer IDs used by entity unique_ids/LTS statistics.
    for item in consumers:
        if item.get("name") == item.get("entity_id"):
            state = hass.states.get(item["entity_id"])
            if state and state.attributes.get("friendly_name"):
                item["name"] = str(state.attributes["friendly_name"])
    valid_ids = {item["id"] for item in consumers}
    generators = normalize_generators(merged, valid_ids)
    for item in generators:
        state = hass.states.get(item["entity_id"])
        if state and state.attributes.get("friendly_name") and item.get("name") in {"PV-Erzeuger", "Lokaler PV-Erzeuger"}:
            item["name"] = str(state.attributes["friendly_name"])
    groups = normalize_groups(merged, valid_ids)

    # Only add the structured model. Legacy keys are deliberately not removed:
    # they remain harmless rollback data while all new code prefers these lists.
    options = {
        **entry.options,
        CONF_CONSUMERS: consumers,
        CONF_GENERATORS: generators,
        CONF_GROUPS: groups,
    }
    hass.config_entries.async_update_entry(entry, options=options, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PV Energy Allocation from a config entry."""
    # Keep the existing config entry/unique IDs, only update the visible title.
    if entry.title != "WattWer":
        hass.config_entries.async_update_entry(entry, title="WattWer")
    controller = PVAllocationController(hass, entry)
    archive = BackfillArchive(hass, entry.entry_id)
    await archive.async_load()
    controller.archive = archive
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await controller.async_start()
    if not archive.config_revisions:
        await archive.async_record_revision(
            {
                "consumers": list(controller.consumer_metadata.values()),
                "groups": controller.groups,
                "generators": list(controller.generator_metadata.values()),
            }
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.data[DOMAIN].get("_panel_registered"):
        # Sidebar dashboard. It deliberately has no config_panel_domain: the
        # integration gear must open the dedicated configuration panel below.
        if frontend.async_panel_exists(hass, PANEL_URL):
            frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)

        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name=PANEL_ELEMENT,
            sidebar_title="WattWer",
            sidebar_icon="mdi:solar-power-variant",
            module_url=f"{PANEL_STATIC_URL}/pv-energy-allocation-panel.js?v={VERSION}",
            config={"domain": DOMAIN},
            require_admin=False,
            handle_safe_area=False,
        )
        hass.data[DOMAIN]["_panel_registered"] = True

    if not hass.data[DOMAIN].get("_config_panel_registered"):
        # Rich integration configuration panel. panel_custom's convenience
        # wrapper always shows a panel in the sidebar; direct frontend
        # registration lets us keep this panel hidden while still associating
        # it with WattWer via config_panel_domain. Home Assistant then opens
        # this page from the integration gear icon.
        if frontend.async_panel_exists(hass, CONFIG_PANEL_URL):
            frontend.async_remove_panel(hass, CONFIG_PANEL_URL, warn_if_unknown=False)

        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="WattWer Optionen",
            sidebar_icon="mdi:cog",
            frontend_url_path=CONFIG_PANEL_URL,
            config={
                "domain": DOMAIN,
                "dashboard_path": PANEL_URL,
                "_panel_custom": {
                    "name": CONFIG_PANEL_ELEMENT,
                    "embed_iframe": False,
                    "trust_external": False,
                    "handle_safe_area": False,
                    "module_url": f"{PANEL_STATIC_URL}/wattwer-config-panel.js?v={VERSION}",
                },
            },
            require_admin=True,
            config_panel_domain=DOMAIN,
            show_in_sidebar=False,
        )
        hass.data[DOMAIN]["_config_panel_registered"] = True
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    controller: PVAllocationController | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if controller is not None:
        await controller.async_stop()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    if hass.data.get(DOMAIN, {}).get("_panel_registered"):
        frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
        hass.data[DOMAIN]["_panel_registered"] = False
    if hass.data.get(DOMAIN, {}).get("_config_panel_registered"):
        frontend.async_remove_panel(hass, CONFIG_PANEL_URL, warn_if_unknown=False)
        hass.data[DOMAIN]["_config_panel_registered"] = False
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove persistent integration state after the config entry is deleted."""
    store = Store[dict](hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
    await store.async_remove()
    archive = BackfillArchive(hass, entry.entry_id)
    await archive.async_remove()
