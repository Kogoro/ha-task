"""Calendar platform for the Task integration."""

import datetime
import logging

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CALENDAR_NAME, CONF_UNIFIED_CALENDAR, DOMAIN
from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData

_LOGGER = logging.getLogger(__name__)

UNIFIED_COORDINATORS_KEY = "unified_coordinators"
UNIFIED_CALENDAR_OWNER_KEY = "unified_calendar_owner"
UNIFIED_CALENDAR_ENTITY_KEY = "unified_calendar_entity"
DEFAULT_UNIFIED_NAME = "All Tasks"


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


def _generate_events_for_items(
    items: list[TaskData],
    start: datetime.date,
    end: datetime.date,
    area_name: str | None = None,
) -> list[CalendarEvent]:
    """Generate calendar events for a list of task items within a date range."""
    events: list[CalendarEvent] = []
    for task in items:
        if task.next_due is None or task.interval_days <= 0:
            continue

        desc = _build_event_description(task, area_name)
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
    """Set up Task calendar entity (one per area/config entry)."""
    coordinator = entry.runtime_data
    unified = entry.data.get(CONF_UNIFIED_CALENDAR, False)

    if not unified:
        async_add_entities([TaskCalendarEntity(coordinator)])
        return

    domain_data = hass.data[DOMAIN]
    unified_coords: dict[str, TaskCoordinator] = domain_data.setdefault(
        UNIFIED_COORDINATORS_KEY, {}
    )
    unified_coords[entry.entry_id] = coordinator

    if UNIFIED_CALENDAR_OWNER_KEY not in domain_data:
        domain_data[UNIFIED_CALENDAR_OWNER_KEY] = entry.entry_id
        calendar_name = entry.data.get(CONF_CALENDAR_NAME) or DEFAULT_UNIFIED_NAME
        entity = UnifiedTaskCalendarEntity(hass, entry.entry_id, calendar_name)
        domain_data[UNIFIED_CALENDAR_ENTITY_KEY] = entity
        async_add_entities([entity])
    else:
        existing_entity = domain_data.get(UNIFIED_CALENDAR_ENTITY_KEY)
        if existing_entity:
            existing_entity.async_schedule_update_ha_state(True)


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
            rrule=f"FREQ=DAILY;INTERVAL={soonest.interval_days}",
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


class UnifiedTaskCalendarEntity(CalendarEntity):
    """A calendar aggregating tasks from all areas that opted into unified mode."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self,
        hass: HomeAssistant,
        owner_entry_id: str,
        calendar_name: str,
    ) -> None:
        """Initialize the unified calendar entity."""
        self.hass = hass
        self._owner_entry_id = owner_entry_id
        self._calendar_name = calendar_name
        self._attr_unique_id = f"{DOMAIN}_unified_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "unified_calendar")},
            name="Task Unified Calendar",
            manufacturer="Task",
            model="Task Manager",
        )

    @property
    def name(self) -> str:
        """Return the unified calendar name."""
        return self._calendar_name

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:calendar-star"

    def _get_unified_coordinators(self) -> list[TaskCoordinator]:
        """Get all coordinators registered for unified calendar."""
        domain_data = self.hass.data.get(DOMAIN, {})
        unified_coords: dict[str, TaskCoordinator] = domain_data.get(
            UNIFIED_COORDINATORS_KEY, {}
        )
        return list(unified_coords.values())

    def _collect_all_items(self) -> list[TaskData]:
        """Collect items from all unified coordinators."""
        items: list[TaskData] = []
        for coordinator in self._get_unified_coordinators():
            items.extend(_collect_items(coordinator))
        return items

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event across all unified areas."""
        items = self._collect_all_items()
        soonest = _find_soonest(items)
        if soonest is None or soonest.next_due is None:
            return None

        area_name = self._get_area_name_for_item(soonest)

        return CalendarEvent(
            start=soonest.next_due,
            end=soonest.next_due + datetime.timedelta(days=1),
            summary=soonest.name,
            description=_build_event_description(soonest, area_name),
            uid=soonest.subentry_id,
            rrule=f"FREQ=DAILY;INTERVAL={soonest.interval_days}",
        )

    def _get_area_name_for_item(self, item: TaskData) -> str | None:
        """Resolve the area name for a task item from its coordinator."""
        for coordinator in self._get_unified_coordinators():
            if coordinator.data is None:
                continue
            found = coordinator.data.tasks.get(
                item.subentry_id
            ) or coordinator.data.maintenance.get(item.subentry_id)
            if found:
                return coordinator.data.area_name
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        """Return calendar events within a datetime range from all unified areas."""
        start = start_date.date() if isinstance(start_date, datetime.datetime) else start_date
        end = end_date.date() if isinstance(end_date, datetime.datetime) else end_date

        all_events: list[CalendarEvent] = []
        for coordinator in self._get_unified_coordinators():
            items = _collect_items(coordinator)
            area_name = coordinator.data.area_name if coordinator.data else None
            all_events.extend(
                _generate_events_for_items(items, start, end, area_name)
            )

        return sorted(all_events, key=lambda e: e.start)

    async def async_update(self) -> None:
        """Poll update — no-op, data comes from coordinators."""
