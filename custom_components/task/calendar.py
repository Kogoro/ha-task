"""Calendar platform for the Task integration."""

import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CALENDAR_NAME,
    CONF_UNIFIED_CALENDAR,
    DEFAULT_HOUSEHOLD_CALENDAR_NAME,
    DOMAIN,
    UNIFIED_CALENDAR_UNIQUE_ID,
)
from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData
from .household import HouseholdCoordinator, household_entry, is_household
from .schedule import occurrences, rrule

_LOGGER = logging.getLogger(__name__)


def _build_event_description(task: TaskData, area_name: str | None = None) -> str | None:
    """Build a rich event description with assignee, task info, and device."""
    parts: list[str] = []
    if area_name:
        parts.append(f"Area: {area_name}")
    if task.current_assignee:
        parts.append(f"Assigned to: {task.current_assignee}")
    if task.description:
        parts.append(task.description)
    if task.device_id:
        parts.append(f"Device: {task.device_id}")
    return "\n".join(parts) if parts else None


def _collect_items(coordinator: TaskCoordinator) -> list[TaskData]:
    """Collect all task and maintenance items from a coordinator."""
    if coordinator.data is None:
        return []
    return list(coordinator.data.tasks.values()) + list(
        coordinator.data.maintenance.values()
    )


def _task_rrule(task: TaskData) -> str:
    """Return the recurrence rule of a task."""
    return rrule(task.interval_value, task.interval_unit, task.active_months)


def _generate_events_for_items(
    items: list[TaskData],
    start: datetime.date,
    end: datetime.date,
    area_name: str | None = None,
) -> list[CalendarEvent]:
    """Generate calendar events for a list of task items within a date range."""
    events: list[CalendarEvent] = []
    for task in items:
        if task.next_due is None or task.interval_value <= 0:
            continue

        desc = _build_event_description(task, area_name)
        recurrence = _task_rrule(task)
        for occurrence in occurrences(
            task.next_due,
            task.interval_value,
            task.interval_unit,
            task.active_months,
            start,
            end,
        ):
            events.append(
                CalendarEvent(
                    start=occurrence,
                    end=occurrence + datetime.timedelta(days=1),
                    summary=task.name,
                    description=desc,
                    uid=task.subentry_id,
                    rrule=recurrence,
                    recurrence_id=occurrence.isoformat(),
                )
            )

    return events


def _find_soonest(items: list[TaskData]) -> TaskData | None:
    """Find the item with the earliest next_due date."""
    soonest: TaskData | None = None
    for task in items:
        if task.next_due is None:
            continue
        if soonest is None or task.next_due < soonest.next_due:
            soonest = task
    return soonest


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendar: the unified one for the household, else one per area."""
    if is_household(entry):
        async_add_entities([UnifiedTaskCalendarEntity(entry.runtime_data)])
        return

    if entry.data.get(CONF_UNIFIED_CALENDAR) and household_entry(hass) is not None:
        # The area's tasks are in the household calendar; drop a leftover own one.
        ent_reg = er.async_get(hass)
        stale = ent_reg.async_get_entity_id(
            "calendar", DOMAIN, f"{entry.entry_id}_calendar"
        )
        if stale:
            ent_reg.async_remove(stale)
        return

    async_add_entities([TaskCalendarEntity(entry.runtime_data)])


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
        """Return the name, using custom calendar_name if set."""
        custom = self.coordinator.config_entry.data.get(CONF_CALENDAR_NAME)
        if custom:
            return custom
        return f"{self.coordinator.data.area_name} tasks"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:calendar-check"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        items = _collect_items(self.coordinator)
        soonest = _find_soonest(items)
        if soonest is None or soonest.next_due is None:
            return None

        return CalendarEvent(
            start=soonest.next_due,
            end=soonest.next_due + datetime.timedelta(days=1),
            summary=soonest.name,
            description=_build_event_description(soonest),
            uid=soonest.subentry_id,
            rrule=_task_rrule(soonest),
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range."""
        items = _collect_items(self.coordinator)
        start = start_date.date() if isinstance(start_date, datetime.datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime.datetime) else end_date
        events = _generate_events_for_items(items, start, end)
        return sorted(events, key=lambda e: e.start)


class UnifiedTaskCalendarEntity(CoordinatorEntity[HouseholdCoordinator], CalendarEntity):
    """A calendar with the tasks of all areas, owned by the household entry."""

    # Named exactly as the user chose; it is not attached to a device, because
    # Home Assistant would then prefix the device's name.
    _attr_has_entity_name = False

    def __init__(self, coordinator: HouseholdCoordinator) -> None:
        """Initialize the unified calendar entity."""
        super().__init__(coordinator)
        # Same unique ID as before the household entry existed, so the entity
        # keeps its entity ID and history.
        self._attr_unique_id = UNIFIED_CALENDAR_UNIQUE_ID

    @property
    def name(self) -> str:
        """Return the calendar name set on the household entry."""
        return (
            self.coordinator.config_entry.data.get(CONF_CALENDAR_NAME)
            or DEFAULT_HOUSEHOLD_CALENDAR_NAME
        )

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:calendar-star"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event across all areas."""
        if self.coordinator.data is None:
            return None
        soonest_entry = None
        for entry in self.coordinator.data.items:
            if entry.item.next_due is None:
                continue
            if soonest_entry is None or entry.item.next_due < soonest_entry.item.next_due:
                soonest_entry = entry
        if soonest_entry is None:
            return None
        soonest = soonest_entry.item
        return CalendarEvent(
            start=soonest.next_due,
            end=soonest.next_due + datetime.timedelta(days=1),
            summary=soonest.name,
            description=_build_event_description(soonest, soonest_entry.area_name),
            uid=soonest.subentry_id,
            rrule=_task_rrule(soonest),
        )

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range from all areas."""
        if self.coordinator.data is None:
            return []
        start = start_date.date() if isinstance(start_date, datetime.datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime.datetime) else end_date

        by_area: dict[str, list[TaskData]] = {}
        for entry in self.coordinator.data.items:
            by_area.setdefault(entry.area_name, []).append(entry.item)

        events: list[CalendarEvent] = []
        for area_name, items in by_area.items():
            events.extend(_generate_events_for_items(items, start, end, area_name))
        return sorted(events, key=lambda e: e.start)
