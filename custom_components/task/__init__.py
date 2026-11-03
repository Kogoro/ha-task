"""The Task integration."""

import datetime
import logging
import shutil
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CALENDAR_NAME,
    CONF_UNIFIED_CALENDAR,
    DOMAIN,
    SERVICE_CLEAR_AWAY,
    SERVICE_COMPLETE_TASK,
    SERVICE_GET_HISTORY,
    SERVICE_POSTPONE_TASK,
    SERVICE_RESET_TASK,
    SERVICE_SET_AWAY,
    SERVICE_UNDO_COMPLETION,
    SIGNAL_AREAS_CHANGED,
    UNIFIED_CALENDAR_UNIQUE_ID,
)
from .coordinator import TaskConfigEntry, TaskCoordinator
from .history import cycle_days, cycle_stats
from .household import HouseholdCoordinator, household_entry, is_household
from .store import TaskStore

FRONTEND_SCRIPT_PATH = f"/{DOMAIN}/task-card.js"
FRONTEND_SCRIPT_URL = f"{FRONTEND_SCRIPT_PATH}?v=0.4.0-beta.2"
BLUEPRINTS_DIR = Path(__file__).parent / "blueprints"

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.TODO, Platform.CALENDAR, Platform.BUTTON]

SERVICE_COMPLETE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("completed_at"): vol.Any(cv.datetime, cv.date),
    }
)

SERVICE_POSTPONE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("days", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=365)
        ),
    }
)

SERVICE_UNDO_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_id})

SERVICE_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("limit", default=50): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=500)
        ),
    }
)

SERVICE_SET_AWAY_SCHEMA = vol.Schema(
    {
        vol.Required("person"): cv.entity_domain("person"),
        vol.Optional("start"): cv.date,
        vol.Optional("end"): cv.date,
    }
)

SERVICE_CLEAR_AWAY_SCHEMA = vol.Schema({vol.Required("person"): cv.entity_domain("person")})

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

        completed_at = call.data.get("completed_at")
        if completed_at is not None:
            if not isinstance(completed_at, datetime.datetime):
                completed_at = datetime.datetime.combine(
                    completed_at, datetime.time(12, 0)
                )
            completed_at = dt_util.as_utc(completed_at)
            if completed_at > dt_util.utcnow():
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="completed_at_in_future",
                )

        subentry_id = entity_entry.config_subentry_id
        coordinator = _find_coordinator_for_subentry(hass, subentry_id)
        if coordinator:
            coordinator.complete_task(
                subentry_id, completed_by=completed_by, completed_at=completed_at
            )
        else:
            store.record_completion(
                subentry_id, completed_by=completed_by, completed_at=completed_at
            )
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
    async def handle_postpone_task(call: ServiceCall) -> None:
        """Handle the postpone_task service call."""
        entity_id = call.data["entity_id"]
        entity_reg = er.async_get(hass)
        entity_entry = entity_reg.async_get(entity_id)
        if entity_entry is None or entity_entry.config_subentry_id is None:
            _LOGGER.error("Entity %s not found or not a task entity", entity_id)
            return

        subentry_id = entity_entry.config_subentry_id
        coordinator = _find_coordinator_for_subentry(hass, subentry_id)
        if coordinator is None:
            _LOGGER.error("No task found for entity %s", entity_id)
            return
        coordinator.postpone_task(subentry_id, call.data["days"])
        await _async_refresh_coordinators(hass)

    def _coordinator_for_entity(entity_id: str) -> tuple[TaskCoordinator, str] | None:
        entity_entry = er.async_get(hass).async_get(entity_id)
        if entity_entry is None or entity_entry.config_subentry_id is None:
            return None
        coordinator = _find_coordinator_for_subentry(
            hass, entity_entry.config_subentry_id
        )
        if coordinator is None:
            return None
        return coordinator, entity_entry.config_subentry_id

    async def handle_undo_completion(call: ServiceCall) -> None:
        """Handle the undo_completion service call."""
        found = _coordinator_for_entity(call.data["entity_id"])
        if found is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_task"
            )
        coordinator, subentry_id = found
        if coordinator.undo_completion(subentry_id) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_undo"
            )
        await _async_refresh_coordinators(hass)

    async def handle_get_history(call: ServiceCall) -> ServiceResponse:
        """Return the completion history of a task, newest first."""
        found = _coordinator_for_entity(call.data["entity_id"])
        if found is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="not_a_task"
            )
        coordinator, subentry_id = found
        item = coordinator.find_item(subentry_id)
        completions = coordinator.store.get_history(subentry_id).completions
        interval = item.interval_days if item else 7
        stats = cycle_stats(completions, interval)
        cycles = cycle_days(completions)
        rows = [
            {
                "completed_at": entry.completed_at.isoformat(),
                "completed_by": entry.completed_by,
                "days_since_previous": cycle,
            }
            for entry, cycle in zip(completions, cycles, strict=True)
        ]
        return {
            "task": item.name if item else None,
            "interval_days": interval,
            "total_completions": len(completions),
            "average_cycle_days": stats.average_cycle_days,
            "last_cycle_days": stats.last_cycle_days,
            "on_time_percent": stats.on_time_percent,
            "completions": list(reversed(rows))[: call.data["limit"]],
        }

    async def handle_set_away(call: ServiceCall) -> None:
        """Mark a person as away; the rotation skips them meanwhile."""
        today = dt_util.now().date()
        start = call.data.get("start", today)
        end = call.data.get("end")
        if end is not None and end < start:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="away_end_before_start"
            )
        if end is not None and end < today:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="away_already_over"
            )
        store.set_away(call.data["person"], start, end)
        await _async_refresh_coordinators(hass)

    async def handle_clear_away(call: ServiceCall) -> None:
        """Mark a person as present again."""
        store.clear_away(call.data["person"])
        await _async_refresh_coordinators(hass)

    hass.services.async_register(
        DOMAIN, SERVICE_SET_AWAY, handle_set_away, schema=SERVICE_SET_AWAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_AWAY, handle_clear_away, schema=SERVICE_CLEAR_AWAY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_POSTPONE_TASK, handle_postpone_task, schema=SERVICE_POSTPONE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNDO_COMPLETION, handle_undo_completion, schema=SERVICE_UNDO_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        handle_get_history,
        schema=SERVICE_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET_TASK, handle_reset_task, schema=SERVICE_RESET_SCHEMA
    )

    await _async_install_blueprints(hass)
    _async_migrate_unified_calendar(hass)

    return True


@callback
def _async_migrate_unified_calendar(hass: HomeAssistant) -> None:
    """Create the household entry for installs that used the unified calendar.

    The unified calendar used to be owned by the first area that opted in. It
    now belongs to the household entry, which is created here once, taking over
    the calendar name the owner area had set.
    """
    if household_entry(hass) is not None:
        return
    unified = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if not is_household(entry) and entry.data.get(CONF_UNIFIED_CALENDAR)
    ]
    if not unified:
        return
    name = next(
        (e.data[CONF_CALENDAR_NAME] for e in unified if e.data.get(CONF_CALENDAR_NAME)),
        None,
    )
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={CONF_CALENDAR_NAME: name} if name else {},
        )
    )


async def _async_install_blueprints(hass: HomeAssistant) -> None:
    """Copy bundled automation blueprints into the user's config directory."""
    if not BLUEPRINTS_DIR.is_dir():
        return

    target_dir = Path(hass.config.path("blueprints", "automation", DOMAIN))

    def _copy() -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in BLUEPRINTS_DIR.glob("*.yaml"):
            dest = target_dir / source.name
            if not dest.exists():
                shutil.copy2(source, dest)
                _LOGGER.debug("Installed blueprint %s", source.name)

    await hass.async_add_executor_job(_copy)


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
            await entry.runtime_data.async_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: TaskConfigEntry) -> bool:
    """Set up Task from a config entry (an area or the household)."""
    if is_household(entry):
        return await _async_setup_household(hass, entry)

    store: TaskStore = hass.data[DOMAIN]["store"]
    coordinator = TaskCoordinator(hass, entry, store)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))
    async_dispatcher_send(hass, SIGNAL_AREAS_CHANGED)

    return True


async def _async_setup_household(hass: HomeAssistant, entry: TaskConfigEntry) -> bool:
    """Set up the household entry: totals and the unified calendar."""
    coordinator = HouseholdCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.async_sync_areas()
    entry.async_on_unload(coordinator.async_stop_following)
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_AREAS_CHANGED, coordinator.async_sync_areas)
    )

    legacy_device_id = _async_legacy_unified_device_id(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    _async_remove_device_if_empty(hass, legacy_device_id)
    _async_reload_areas(hass, with_own_calendar=True)
    return True


@callback
def _async_legacy_unified_device_id(hass: HomeAssistant) -> str | None:
    """Return the device the unified calendar still sits on from before, if any."""
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("calendar", DOMAIN, UNIFIED_CALENDAR_UNIQUE_ID)
    entry = ent_reg.async_get(entity_id) if entity_id else None
    return entry.device_id if entry else None


@callback
def _async_remove_device_if_empty(hass: HomeAssistant, device_id: str | None) -> None:
    """Remove the device the unified calendar used to live on, once it is empty."""
    if device_id is None:
        return
    dev_reg = dr.async_get(hass)
    if dev_reg.async_get(device_id) and not er.async_entries_for_device(
        er.async_get(hass), device_id
    ):
        dev_reg.async_remove_device(device_id)


@callback
def _async_reload_areas(hass: HomeAssistant, *, with_own_calendar: bool) -> None:
    """Reload loaded areas that opted out of their own calendar.

    With ``with_own_calendar`` only areas that still have a calendar of their
    own are reloaded (they must drop it now that the household calendar
    exists); otherwise all of them are (they need their own calendar back).
    """
    ent_reg = er.async_get(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if (
            is_household(entry)
            or not entry.data.get(CONF_UNIFIED_CALENDAR)
            or entry.state is not ConfigEntryState.LOADED
        ):
            continue
        has_calendar = ent_reg.async_get_entity_id(
            "calendar", DOMAIN, f"{entry.entry_id}_calendar"
        )
        if with_own_calendar == bool(has_calendar):
            hass.config_entries.async_schedule_reload(entry.entry_id)


async def _async_entry_updated(
    hass: HomeAssistant, entry: TaskConfigEntry
) -> None:
    """Handle config entry or subentry updates by reloading."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TaskConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not is_household(entry):
        async_dispatcher_send(hass, SIGNAL_AREAS_CHANGED)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: TaskConfigEntry) -> None:
    """Give areas their own calendar back when the household entry is removed."""
    if is_household(entry):
        _async_reload_areas(hass, with_own_calendar=False)
