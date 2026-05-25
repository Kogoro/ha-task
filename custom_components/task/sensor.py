"""Sensor platform for the Task integration."""

from homeassistant.components.sensor import SensorEntity
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

    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: _async_check_new_entities(coordinator, entry, async_add_entities)
        )
    )


@callback
def _async_check_new_entities(
    coordinator: TaskCoordinator,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add entities for newly added subentries."""
    existing_subentry_ids = {
        subentry_id
        for subentry_id in coordinator.async_contexts()
        if isinstance(subentry_id, str)
    }
    for subentry_id in coordinator.data.tasks:
        if subentry_id not in existing_subentry_ids:
            async_add_entities(
                [TaskSensorEntity(coordinator, subentry_id)],
                config_subentry_id=subentry_id,
            )


class TaskSensorEntity(CoordinatorEntity[TaskCoordinator], SensorEntity):
    """Sensor showing days until a task is due."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "days"

    def __init__(
        self, coordinator: TaskCoordinator, subentry_id: str
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, context=subentry_id)
        self.subentry_id = subentry_id
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{subentry_id}_sensor"

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.tasks.get(self.subentry_id)

    @property
    def name(self) -> str | None:
        """Return the name of the sensor."""
        task = self._task_data
        if task:
            return task.name
        return None

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
    def extra_state_attributes(self) -> dict[str, str | int | bool | None]:
        """Return additional attributes."""
        task = self._task_data
        if not task:
            return {}
        return {
            ATTR_ASSIGNEE: task.assignee,
            ATTR_INTERVAL_DAYS: task.interval_days,
            ATTR_LAST_COMPLETED: (
                task.last_completed.isoformat() if task.last_completed else None
            ),
            ATTR_NEXT_DUE: task.next_due.isoformat() if task.next_due else None,
            ATTR_OVERDUE: task.overdue,
            ATTR_AREA_ID: self.coordinator.data.area_id,
        }
