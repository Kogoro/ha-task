"""Household entry: totals and the unified calendar across all areas."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HOUSEHOLD
from .coordinator import TaskCoordinator, TaskData

_LOGGER = logging.getLogger(__name__)


def is_household(entry: ConfigEntry) -> bool:
    """Return True if the entry is the household entry (not an area)."""
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSEHOLD


def household_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the household entry, if one exists."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if is_household(entry):
            return entry
    return None


# An area announces itself while it is still being set up, so that counts too.
_ACTIVE_STATES = (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)


def loaded_area_coordinators(hass: HomeAssistant) -> list[TaskCoordinator]:
    """Return the coordinators of all area entries that are set up (or being set up)."""
    coordinators: list[TaskCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if is_household(entry) or entry.state not in _ACTIVE_STATES:
            continue
        coordinator = getattr(entry, "runtime_data", None)
        if isinstance(coordinator, TaskCoordinator) and coordinator.data is not None:
            coordinators.append(coordinator)
    return coordinators


@dataclass
class HouseholdItem:
    """A task or maintenance item together with the area it belongs to."""

    area_name: str
    item: TaskData

    @property
    def label(self) -> str:
        """Return "Area: task" for attributes."""
        return f"{self.area_name}: {self.item.name}"


@dataclass
class HouseholdData:
    """All items of all loaded areas."""

    items: list[HouseholdItem] = field(default_factory=list)


class HouseholdCoordinator(DataUpdateCoordinator[HouseholdData]):
    """Aggregates the area coordinators; it never polls on its own."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_household",
            update_interval=None,
        )
        self._unsubscribe: dict[str, Callable[[], None]] = {}

    def _collect(self) -> HouseholdData:
        """Collect the items of every loaded area."""
        items: list[HouseholdItem] = []
        for coordinator in loaded_area_coordinators(self.hass):
            area_name = coordinator.data.area_name
            items.extend(
                HouseholdItem(area_name, item) for item in coordinator.data.all_items
            )
        return HouseholdData(items=items)

    async def _async_update_data(self) -> HouseholdData:
        """Return the current totals."""
        return self._collect()

    @callback
    def async_sync_areas(self) -> None:
        """Follow the areas that are loaded now and publish fresh data."""
        current = {
            coordinator.config_entry.entry_id: coordinator
            for coordinator in loaded_area_coordinators(self.hass)
        }
        for entry_id in set(self._unsubscribe) - set(current):
            self._unsubscribe.pop(entry_id)()
        for entry_id, coordinator in current.items():
            if entry_id not in self._unsubscribe:
                self._unsubscribe[entry_id] = coordinator.async_add_listener(
                    self._handle_area_update
                )
        self.async_set_updated_data(self._collect())

    @callback
    def _handle_area_update(self) -> None:
        """An area recalculated; refresh the totals."""
        self.async_set_updated_data(self._collect())

    @callback
    def async_stop_following(self) -> None:
        """Stop listening to the area coordinators."""
        for unsubscribe in self._unsubscribe.values():
            unsubscribe()
        self._unsubscribe.clear()
