"""Button platform for the Task integration."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task button entities from a config entry."""
    coordinator = entry.runtime_data

    entities: list[TaskCompleteButton] = [
        TaskCompleteButton(coordinator, subentry_id)
        for subentry_id in coordinator.data.tasks
    ]
    async_add_entities(entities)

    @callback
    def _async_on_coordinator_update() -> None:
        """Add new buttons when tasks are added."""
        known = {
            entity.subentry_id
            for entity in entities
        }
        new_entities: list[TaskCompleteButton] = []
        for subentry_id in coordinator.data.tasks:
            if subentry_id not in known:
                button = TaskCompleteButton(coordinator, subentry_id)
                entities.append(button)
                new_entities.append(button)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(_async_on_coordinator_update))


class TaskCompleteButton(CoordinatorEntity[TaskCoordinator], ButtonEntity):
    """Button to mark a task as complete."""

    _attr_has_entity_name = True
    _attr_translation_key = "complete_task"

    def __init__(
        self,
        coordinator: TaskCoordinator,
        subentry_id: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.subentry_id = subentry_id
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{subentry_id}_button"
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
        """Return the name of the button."""
        if task := self._task_data:
            return f"Complete {task.name}"
        return None

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:check-circle"

    async def async_press(self) -> None:
        """Handle the button press."""
        self.coordinator.store.record_completion(self.subentry_id)
        await self.coordinator.async_request_refresh()
