"""Calendar platform for the Task integration."""

import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData


def _build_event_description(task: TaskData) -> str | None:
    """Build a rich event description with assignee, task info, and device."""
    parts: list[str] = []
    if task.current_assignee:
        parts.append(f"Assigned to: {task.current_assignee}")
    if task.description:
        parts.append(task.description)
    if task.device_id:
        parts.append(f"Device: {task.device_id}")
    return "\n".join(parts) if parts else None


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=f"{coordinator.data.area_name} Tasks",
            suggested_area=coordinator.data.area_name,
            manufacturer="Task",
            model="Task Manager",
        )

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

        all_items = list(self.coordinator.data.tasks.values()) + list(
            self.coordinator.data.maintenance.values()
        )
        if not all_items:
            return None

        soonest: TaskData | None = None
        for task in all_items:
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
            description=_build_event_description(soonest),
            uid=soonest.subentry_id,
            rrule=f"FREQ=DAILY;INTERVAL={soonest.interval_days}",
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

        all_items = list(self.coordinator.data.tasks.values()) + list(
            self.coordinator.data.maintenance.values()
        )

        for task in all_items:
            if task.next_due is None or task.interval_days <= 0:
                continue

            desc = _build_event_description(task)

            rrule = f"FREQ=DAILY;INTERVAL={task.interval_days}"

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
                            description=desc,
                            uid=task.subentry_id,
                            rrule=rrule,
                            recurrence_id=occurrence.isoformat(),
                        )
                    )
                occurrence += datetime.timedelta(days=task.interval_days)

        return sorted(events, key=lambda e: e.start)
