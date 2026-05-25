"""Calendar platform for the Task integration."""

import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task calendar entity (one per area/config entry)."""
    coordinator = entry.runtime_data
    async_add_entities([TaskCalendarEntity(coordinator)])


class TaskCalendarEntity(CoordinatorEntity[TaskCoordinator], CalendarEntity):
    """A calendar showing task due dates for an area."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TaskCoordinator) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_calendar"

    @property
    def name(self) -> str:
        """Return the name."""
        return f"{self.coordinator.data.area_name} tasks"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:calendar-check"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        if self.coordinator.data is None:
            return None

        tasks = self.coordinator.data.tasks.values()
        if not tasks:
            return None

        soonest: TaskData | None = None
        for task in tasks:
            if task.next_due is None:
                continue
            if soonest is None or (
                task.next_due < soonest.next_due
            ):
                soonest = task

        if soonest is None or soonest.next_due is None:
            return None

        return CalendarEvent(
            start=soonest.next_due,
            end=soonest.next_due + datetime.timedelta(days=1),
            summary=soonest.name,
            description=soonest.description,
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        if self.coordinator.data is None:
            return []

        events: list[CalendarEvent] = []
        start = start_date.date() if isinstance(start_date, datetime.datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime.datetime) else end_date

        for task in self.coordinator.data.tasks.values():
            if task.next_due is None or task.interval_days <= 0:
                continue

            occurrence = task.next_due
            while occurrence > start:
                prev = occurrence - datetime.timedelta(days=task.interval_days)
                if prev < start:
                    break
                occurrence = prev

            while occurrence < end:
                if occurrence >= start:
                    events.append(
                        CalendarEvent(
                            start=occurrence,
                            end=occurrence + datetime.timedelta(days=1),
                            summary=task.name,
                            description=task.description,
                            uid=f"{task.subentry_id}_{occurrence.isoformat()}",
                        )
                    )
                occurrence += datetime.timedelta(days=task.interval_days)

        return sorted(events, key=lambda e: e.start)
