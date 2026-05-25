"""Calendar platform for the Task integration."""

import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Task calendar entity."""
    coordinator = entry.runtime_data
    async_add_entities([TaskCalendar(coordinator)])


class TaskCalendar(CoordinatorEntity[TaskCoordinator], CalendarEntity):
    """Calendar entity showing task schedule for an area."""

    _attr_has_entity_name = True
    _attr_translation_key = "task_schedule"

    def __init__(self, coordinator: TaskCoordinator) -> None:
        """Initialize the calendar entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_config_entry_id = entry.entry_id

    @property
    def name(self) -> str:
        """Return the name of the calendar."""
        return f"{self.coordinator.data.area_name} Task Schedule"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:calendar-check"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming or current overdue event."""
        today = dt_util.now().date()
        soonest_event: CalendarEvent | None = None
        soonest_date: datetime.date | None = None

        for task in self.coordinator.data.tasks.values():
            if task.next_due is None:
                continue
            if soonest_date is None or task.next_due <= soonest_date:
                soonest_date = task.next_due
                soonest_event = self._make_event(task, task.next_due)

        return soonest_event

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return events within the requested date range."""
        events: list[CalendarEvent] = []
        range_start = start_date.date()
        range_end = end_date.date()

        for task in self.coordinator.data.tasks.values():
            task_events = self._generate_occurrences(task, range_start, range_end)
            events.extend(task_events)

        events.sort(key=lambda e: e.start)
        return events

    def _generate_occurrences(
        self,
        task: TaskData,
        range_start: datetime.date,
        range_end: datetime.date,
    ) -> list[CalendarEvent]:
        """Generate recurring event occurrences for a task within a range."""
        if task.next_due is None:
            return []

        events: list[CalendarEvent] = []
        interval = datetime.timedelta(days=task.interval_days)
        occurrence = task.next_due

        while occurrence > range_start and task.interval_days > 0:
            prev = occurrence - interval
            if prev < range_start:
                break
            occurrence = prev

        while occurrence < range_end:
            if occurrence >= range_start:
                events.append(self._make_event(task, occurrence))
            occurrence += interval
            if task.interval_days <= 0:
                break

        return events

    def _make_event(self, task: TaskData, event_date: datetime.date) -> CalendarEvent:
        """Create a CalendarEvent for a task occurrence."""
        return CalendarEvent(
            summary=task.name,
            start=event_date,
            end=event_date + datetime.timedelta(days=1),
            description=task.description,
            uid=task.subentry_id,
        )
