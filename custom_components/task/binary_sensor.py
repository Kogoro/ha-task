"""Binary sensor platform for the Task integration."""

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData
from .device import task_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task binary sensor entities."""
    coordinator = entry.runtime_data

    for subentry_id in coordinator.data.tasks:
        async_add_entities(
            [TaskOverdueBinarySensor(coordinator, subentry_id)],
            config_subentry_id=subentry_id,
        )

    for subentry_id in coordinator.data.maintenance:
        async_add_entities(
            [TaskOverdueBinarySensor(coordinator, subentry_id)],
            config_subentry_id=subentry_id,
        )

    async_add_entities([AreaOverdueBinarySensor(coordinator)])


class TaskOverdueBinarySensor(CoordinatorEntity[TaskCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether a task is overdue."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "overdue"

    def __init__(
        self, coordinator: TaskCoordinator, subentry_id: str
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, context=subentry_id)
        self.subentry_id = subentry_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{subentry_id}_overdue"
        )
        self._attr_device_info = task_device_info(coordinator, subentry_id)

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator._find_item(self.subentry_id)

    @property
    def is_on(self) -> bool | None:
        """Return True if the task is overdue."""
        task = self._task_data
        if task is None:
            return None
        return task.overdue


class AreaOverdueBinarySensor(CoordinatorEntity[TaskCoordinator], BinarySensorEntity):
    """Binary sensor indicating whether any task in the area is overdue."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "area_overdue"

    def __init__(self, coordinator: TaskCoordinator) -> None:
        """Initialize the area summary binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_area_overdue"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name=f"{coordinator.data.area_name} Tasks",
            suggested_area=coordinator.data.area_name,
            manufacturer="Task",
            model="Task Manager",
        )

    @property
    def _overdue_items(self) -> list[TaskData]:
        """Get all overdue items across tasks and maintenance."""
        if self.coordinator.data is None:
            return []
        return [
            item
            for item in (
                *self.coordinator.data.tasks.values(),
                *self.coordinator.data.maintenance.values(),
            )
            if item.overdue
        ]

    @property
    def is_on(self) -> bool | None:
        """Return True if any task in the area is overdue."""
        if self.coordinator.data is None:
            return None
        return len(self._overdue_items) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return overdue count and list of overdue task names."""
        overdue = self._overdue_items
        return {
            "overdue_count": len(overdue),
            "overdue_tasks": [item.name for item in overdue],
        }
