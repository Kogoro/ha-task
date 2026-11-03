"""Sensor platform for the Task integration."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AREA_ID,
    ATTR_ASSIGNEES,
    ATTR_CURRENT_ASSIGNEE,
    ATTR_INTERVAL_DAYS,
    ATTR_LAST_COMPLETED,
    ATTR_NEXT_DUE,
    ATTR_OVERDUE,
    ATTR_ROTATION_MODE,
    TaskStatus,
)
from .coordinator import (
    TaskConfigEntry,
    TaskCoordinator,
    TaskCoordinatorData,
    TaskData,
)
from .device import area_device_info, household_device_info, task_device_info
from .history import cycle_stats
from .household import HouseholdCoordinator, is_household

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class AreaSensorDescription(SensorEntityDescription):
    """Describes a summary sensor of an area."""

    match_fn: Callable[[TaskData], bool]


AREA_SENSORS: tuple[AreaSensorDescription, ...] = (
    AreaSensorDescription(
        key="overdue_count",
        translation_key="overdue_count",
        match_fn=lambda item: item.status is TaskStatus.OVERDUE,
    ),
    AreaSensorDescription(
        key="due_today",
        translation_key="due_today",
        match_fn=lambda item: not item.overdue and item.days_until_due == 0,
    ),
    AreaSensorDescription(
        key="due_this_week",
        translation_key="due_this_week",
        match_fn=lambda item: (
            not item.overdue
            and item.days_until_due is not None
            and 0 <= item.days_until_due <= 7
        ),
    ),
    AreaSensorDescription(
        key="due_soon",
        translation_key="due_soon",
        match_fn=lambda item: item.status is TaskStatus.DUE_SOON,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task sensor entities."""
    if is_household(entry):
        async_add_entities(
            HouseholdSummarySensor(entry.runtime_data, description)
            for description in AREA_SENSORS
        )
        return

    coordinator = entry.runtime_data

    for subentry_id in (*coordinator.data.tasks, *coordinator.data.maintenance):
        async_add_entities(
            [
                TaskSensorEntity(coordinator, subentry_id),
                TaskStatusSensorEntity(coordinator, subentry_id),
            ],
            config_subentry_id=subentry_id,
        )

    async_add_entities(
        AreaSummarySensor(coordinator, description) for description in AREA_SENSORS
    )


class AreaSummarySensor(CoordinatorEntity[TaskCoordinator], SensorEntity):
    """Number of tasks in an area that match a condition."""

    entity_description: AreaSensorDescription
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "tasks"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: TaskCoordinator, description: AreaSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{description.key}"
        )
        self._attr_device_info = area_device_info(coordinator)

    @property
    def _matches(self) -> list[TaskData]:
        """Return the items that match the sensor's condition."""
        data: TaskCoordinatorData | None = self.coordinator.data
        if data is None:
            return []
        return [i for i in data.all_items if self.entity_description.match_fn(i)]

    @property
    def native_value(self) -> int:
        """Return the number of matching items."""
        return len(self._matches)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the names of the matching items and who is responsible."""
        matches = self._matches
        return {
            "tasks": [item.name for item in matches],
            "assignees": {
                item.name: item.current_assignee
                for item in matches
                if item.current_assignee
            },
        }


class HouseholdSummarySensor(CoordinatorEntity[HouseholdCoordinator], SensorEntity):
    """Number of tasks across all areas that match a condition."""

    entity_description: AreaSensorDescription
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "tasks"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator: HouseholdCoordinator, description: AreaSensorDescription
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = household_device_info(entry_id)

    @property
    def _matches(self):
        """Return the items that match the sensor's condition."""
        if self.coordinator.data is None:
            return []
        return [
            entry
            for entry in self.coordinator.data.items
            if self.entity_description.match_fn(entry.item)
        ]

    @property
    def native_value(self) -> int:
        """Return the number of matching items."""
        return len(self._matches)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the matching items as "Area: task" and who is responsible."""
        matches = self._matches
        return {
            "tasks": [entry.label for entry in matches],
            "assignees": {
                entry.label: entry.item.current_assignee
                for entry in matches
                if entry.item.current_assignee
            },
        }


class TaskStatusSensorEntity(CoordinatorEntity[TaskCoordinator], SensorEntity):
    """Status of a task: ok, due soon or overdue."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "status"

    def __init__(self, coordinator: TaskCoordinator, subentry_id: str) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, context=subentry_id)
        self._attr_options = [status.value for status in TaskStatus]
        self.subentry_id = subentry_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{subentry_id}_status"
        )
        self._attr_device_info = task_device_info(coordinator, subentry_id)

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.find_item(self.subentry_id)

    @property
    def native_value(self) -> str | None:
        """Return the status."""
        task = self._task_data
        return task.status.value if task else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the warning window that applies to the task."""
        task = self._task_data
        return {"warn_days": task.warn_days} if task else {}


class TaskSensorEntity(CoordinatorEntity[TaskCoordinator], SensorEntity):
    """Sensor showing days until a task is due."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "days"
    _attr_translation_key = "days_until_due"

    _attr_name = None

    def __init__(
        self, coordinator: TaskCoordinator, subentry_id: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, context=subentry_id)
        self.subentry_id = subentry_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{subentry_id}_sensor"
        self._attr_device_info = task_device_info(coordinator, subentry_id)

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.find_item(self.subentry_id)

    @property
    def native_value(self) -> int | None:
        """Return days until due (negative if overdue)."""
        task = self._task_data
        if task:
            return task.days_until_due
        return None

    @property
    def icon(self) -> str | None:
        """Return the icon."""
        task = self._task_data
        if task and task.icon:
            return task.icon
        return "mdi:clipboard-check-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes including completion history."""
        task = self._task_data
        if not task:
            return {}

        history = self.coordinator.store.get_history(self.subentry_id)
        stats = cycle_stats(history.completions, task.interval_days)

        completions_by_person: dict[str, int] = {}
        recent_completions: list[dict[str, str | None]] = []

        for entry in history.completions:
            person = entry.completed_by or "unknown"
            completions_by_person[person] = completions_by_person.get(person, 0) + 1

        for entry in history.completions[-20:]:
            recent_completions.append({
                "completed_at": (
                    entry.completed_at.isoformat() if entry.completed_at else None
                ),
                "completed_by": entry.completed_by,
                "points": entry.points,
            })

        attrs = {
            ATTR_CURRENT_ASSIGNEE: task.current_assignee,
            ATTR_ASSIGNEES: task.assignees,
            ATTR_ROTATION_MODE: task.rotation_mode,
            ATTR_INTERVAL_DAYS: task.interval_days,
            "interval_value": task.interval_value,
            "interval_unit": task.interval_unit,
            "active_months": task.active_months,
            "in_season": task.in_season,
            ATTR_LAST_COMPLETED: (
                task.last_completed.isoformat() if task.last_completed else None
            ),
            "last_completed_by": task.last_completed_by,
            ATTR_NEXT_DUE: task.next_due.isoformat() if task.next_due else None,
            ATTR_OVERDUE: task.overdue,
            ATTR_AREA_ID: self.coordinator.data.area_id,
            "subentry_type": task.subentry_type,
            "total_completions": len(history.completions),
            "points": task.points,
            "away_assignees": task.away_assignees,
            "can_undo": history.undo is not None,
            "undo_completed_at": (
                history.undo.completed_at.isoformat() if history.undo else None
            ),
            "average_cycle_days": stats.average_cycle_days,
            "last_cycle_days": stats.last_cycle_days,
            "on_time_percent": stats.on_time_percent,
            "completions_by_person": completions_by_person,
            "recent_completions": recent_completions,
        }
        if task.description:
            attrs["description"] = task.description
        if task.device_id:
            attrs["device_id"] = task.device_id
        return attrs
