"""Sensor platform for the Task integration."""

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
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
    DOMAIN,
)
from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task sensor entities."""
    coordinator = entry.runtime_data

    for subentry_id in coordinator.data.tasks:
        async_add_entities(
            [TaskSensorEntity(coordinator, subentry_id)],
            config_subentry_id=subentry_id,
        )

    for subentry_id in coordinator.data.maintenance:
        async_add_entities(
            [TaskSensorEntity(coordinator, subentry_id)],
            config_subentry_id=subentry_id,
        )


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
        item = coordinator._find_item(subentry_id)
        task_name = item.name if item else "Task"
        if item and item.device_id:
            dev_reg = dr.async_get(coordinator.hass)
            device = dev_reg.async_get(item.device_id)
            if device:
                self._attr_device_info = DeviceInfo(
                    identifiers=device.identifiers,
                )
            else:
                self._attr_device_info = DeviceInfo(
                    identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_{subentry_id}")},
                    name=task_name,
                    suggested_area=coordinator.data.area_name,
                    manufacturer="Task",
                    model="Device Maintenance",
                )
        else:
            entry_slug = coordinator.config_entry.title.lower().replace(" ", "_")
            task_slug = task_name.lower().replace(" ", "_")
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry_slug}_{task_slug}")},
                name=task_name,
                suggested_area=coordinator.data.area_name,
                manufacturer="Task",
                model="Household Task",
            )

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator._find_item(self.subentry_id)

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
            })

        attrs = {
            ATTR_CURRENT_ASSIGNEE: task.current_assignee,
            ATTR_ASSIGNEES: task.assignees,
            ATTR_ROTATION_MODE: task.rotation_mode,
            ATTR_INTERVAL_DAYS: task.interval_days,
            ATTR_LAST_COMPLETED: (
                task.last_completed.isoformat() if task.last_completed else None
            ),
            "last_completed_by": task.last_completed_by,
            ATTR_NEXT_DUE: task.next_due.isoformat() if task.next_due else None,
            ATTR_OVERDUE: task.overdue,
            ATTR_AREA_ID: self.coordinator.data.area_id,
            "subentry_type": task.subentry_type,
            "total_completions": len(history.completions),
            "completions_by_person": completions_by_person,
            "recent_completions": recent_completions,
        }
        if task.description:
            attrs["description"] = task.description
        if task.device_id:
            attrs["device_id"] = task.device_id
        return attrs
