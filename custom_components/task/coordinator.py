"""DataUpdateCoordinator for the Task integration."""

import datetime
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import CONF_AREA_ID, CONF_ASSIGNEE, CONF_INTERVAL_DAYS, DOMAIN
from .store import TaskStore

_LOGGER = logging.getLogger(__name__)

type TaskConfigEntry = ConfigEntry[TaskCoordinator]


@dataclass
class TaskData:
    """Computed state for a single task."""

    subentry_id: str
    name: str
    description: str | None
    assignee: str | None
    interval_days: int
    icon: str | None
    last_completed: datetime.datetime | None
    next_due: datetime.date | None
    days_until_due: int | None
    overdue: bool


@dataclass
class TaskCoordinatorData:
    """All computed data for a config entry."""

    area_id: str
    area_name: str
    tasks: dict[str, TaskData]


class TaskCoordinator(DataUpdateCoordinator[TaskCoordinatorData]):
    """Coordinator for the Task integration."""

    config_entry: TaskConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: TaskConfigEntry,
        store: TaskStore,
    ) -> None:
        """Initialize the coordinator."""
        self.store = store
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{config_entry.entry_id}",
        )

    async def _async_update_data(self) -> TaskCoordinatorData:
        """Compute derived state for all tasks."""
        entry = self.config_entry
        area_id = entry.data[CONF_AREA_ID]

        area_reg = ar.async_get(self.hass)
        area_entry = area_reg.async_get_area(area_id)
        area_name = area_entry.name if area_entry else area_id

        today = dt_util.now().date()
        tasks: dict[str, TaskData] = {}

        for subentry in entry.subentries.values():
            if subentry.subentry_type != "task":
                continue

            history = self.store.get_history(subentry.subentry_id)
            interval_days = subentry.data.get(CONF_INTERVAL_DAYS, 7)
            last_completed = history.last_completed

            next_due: datetime.date | None = None
            days_until_due: int | None = None
            overdue = False

            if last_completed:
                next_due = (
                    last_completed + datetime.timedelta(days=interval_days)
                ).date()
                days_until_due = (next_due - today).days
                overdue = days_until_due < 0
            else:
                days_until_due = 0
                overdue = True
                next_due = today

            tasks[subentry.subentry_id] = TaskData(
                subentry_id=subentry.subentry_id,
                name=subentry.title,
                description=subentry.data.get("description"),
                assignee=subentry.data.get(CONF_ASSIGNEE),
                interval_days=interval_days,
                icon=subentry.data.get("icon"),
                last_completed=last_completed,
                next_due=next_due,
                days_until_due=days_until_due,
                overdue=overdue,
            )

        return TaskCoordinatorData(
            area_id=area_id,
            area_name=area_name,
            tasks=tasks,
        )
