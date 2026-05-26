"""The Task integration."""

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    DOMAIN,
    SERVICE_COMPLETE_TASK,
    SERVICE_RESET_TASK,
)
from .coordinator import TaskConfigEntry, TaskCoordinator
from .store import TaskStore

FRONTEND_SCRIPT_PATH = f"/{DOMAIN}/task-card.js"
FRONTEND_SCRIPT_URL = f"{FRONTEND_SCRIPT_PATH}?v=0.5.0"

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.TODO, Platform.CALENDAR, Platform.BUTTON]

SERVICE_COMPLETE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)

SERVICE_RESET_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the Task integration services."""
    store = TaskStore(hass)
    await store.async_load()
    hass.data[DOMAIN] = {"store": store}

    await hass.http.async_register_static_paths(
        [StaticPathConfig(
            url_path=FRONTEND_SCRIPT_PATH,
            path=str(Path(__file__).parent / "www" / "task-card.js"),
            cache_headers=False,
        )]
    )
    add_extra_js_url(hass, FRONTEND_SCRIPT_URL)

    async def handle_complete_task(call: ServiceCall) -> None:
        """Handle the complete_task service call."""
        entity_id = call.data["entity_id"]
        entity_reg = er.async_get(hass)
        entity_entry = entity_reg.async_get(entity_id)
        if entity_entry is None or entity_entry.config_subentry_id is None:
            _LOGGER.error("Entity %s not found or not a task entity", entity_id)
            return

        user_id = call.context.user_id
        completed_by = None
        if user_id:
            for state in hass.states.async_all("person"):
                if state.attributes.get("user_id") == user_id:
                    completed_by = state.entity_id
                    break

        subentry_id = entity_entry.config_subentry_id
        coordinator = _find_coordinator_for_subentry(hass, subentry_id)
        if coordinator:
            coordinator.complete_task(subentry_id, completed_by=completed_by)
        else:
            store.record_completion(subentry_id, completed_by=completed_by)
        await _async_refresh_coordinators(hass)

    async def handle_reset_task(call: ServiceCall) -> None:
        """Handle the reset_task service call."""
        entity_id = call.data["entity_id"]
        entity_reg = er.async_get(hass)
        entity_entry = entity_reg.async_get(entity_id)
        if entity_entry is None or entity_entry.config_subentry_id is None:
            _LOGGER.error("Entity %s not found or not a task entity", entity_id)
            return

        store.reset_history(entity_entry.config_subentry_id)
        await _async_refresh_coordinators(hass)

    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE_TASK, handle_complete_task, schema=SERVICE_COMPLETE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_TASK, handle_reset_task, schema=SERVICE_RESET_SCHEMA
    )

    return True


def _find_coordinator_for_subentry(
    hass: HomeAssistant, subentry_id: str
) -> TaskCoordinator | None:
    """Find the coordinator that owns a given subentry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if (
            hasattr(entry, "runtime_data")
            and isinstance(entry.runtime_data, TaskCoordinator)
            and subentry_id in entry.subentries
        ):
            return entry.runtime_data
    return None


async def _async_refresh_coordinators(hass: HomeAssistant) -> None:
    """Request refresh on all task coordinators."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if hasattr(entry, "runtime_data") and isinstance(entry.runtime_data, TaskCoordinator):
            await entry.runtime_data.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: TaskConfigEntry) -> bool:
    """Set up Task from a config entry."""
    store: TaskStore = hass.data[DOMAIN]["store"]
    coordinator = TaskCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    return True


async def _async_entry_updated(
    hass: HomeAssistant, entry: TaskConfigEntry
) -> None:
    """Handle config entry or subentry updates by reloading."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TaskConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
