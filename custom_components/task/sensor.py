"""Sensor platform for the Task integration."""

import logging

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_AREA_ID,
    ATTR_ASSIGNEE,
    ATTR_INTERVAL_DAYS,
    ATTR_LAST_COMPLETED,
    ATTR_NEXT_DUE,
    ATTR_OVERDUE,
)
from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task sensor entities from a config entry."""
    coordinator = entry.runtime_data

    entities: list[TaskSensor] = [
        TaskSensor(coordinator, subentry_id)
        for subentry_id in coordinator.data.tasks
    ]
    async_add_entities(entities)

    @callback
    def _async_on_coordinator_update() -> None:
        """Add new sensors when tasks are added."""
        known = {
            entity.subentry_id
            for entity in entities
        }
        new_entities: list[TaskSensor] = []
        for subentry_id in coordinator.data.tasks:
            if subentry_id not in known:
                sensor = TaskSensor(coordinator, subentry_id)
                entities.append(sensor)
                new_entities.append(sensor)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_on_coordinator_update))


class TaskSensor(CoordinatorEntity[TaskCoordinator], SensorEntity):
    """Sensor showing days until a task is due."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_translation_key = "days_until_due"

    def __init__(
        self,
        coordinator: TaskCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.subentry_id = subentry_id
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{subentry_id}_sensor"
        self._attr_config_entry_id = entry.entry_id
        self._attr_config_subentry_id = subentry_id

    @property
    def _task_data(self) -> TaskData | None:
        """Get the current task data."""
        return self.coordinator.data.tasks.get(self.subentry_id)

    @property
    def available(self) -> bool:
        """Return True if the task still exists."""
        return super().available and self._task_data is not None

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        if task := self._task_data:
            return task.name
        return None

    @property
    def native_value(self) -> int | None:
        """Return the days until due."""
        if task := self._task_data:
            return task.days_until_due
        return None

    @property
    def icon(self) -> str:
        """Return the icon."""
        if task := self._task_data:
            return task.icon or "mdi:checkbox-marked-circle-outline"
        return "mdi:checkbox-marked-circle-outline"

    @property
    def extra_state_attributes(self) -> dict[str, str | int | bool | None]:
        """Return extra state attributes."""
        task = self._task_data
        if task is None:
            return {}
        return {
            ATTR_ASSIGNEE: task.assignee,
            ATTR_INTERVAL_DAYS: task.interval_days,
            ATTR_LAST_COMPLETED: (
                task.last_completed.isoformat() if task.last_completed else None
            ),
            ATTR_NEXT_DUE: task.next_due.isoformat() if task.next_due else None,
            ATTR_AREA_ID: self.coordinator.data.area_id,
            ATTR_OVERDUE: task.overdue,
        }
