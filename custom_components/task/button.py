"""Button platform for the Task integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task button entities."""
    coordinator = entry.runtime_data

    for subentry_id in coordinator.data.tasks:
        async_add_entities(
            [TaskCompleteButton(coordinator, subentry_id)],
            config_subentry_id=subentry_id,
        )

    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: _async_check_new_entities(coordinator, async_add_entities)
        )
    )


@callback
def _async_check_new_entities(
    coordinator: TaskCoordinator,
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
                [TaskCompleteButton(coordinator, subentry_id)],
                config_subentry_id=subentry_id,
            )


class TaskCompleteButton(CoordinatorEntity[TaskCoordinator], ButtonEntity):
    """Button to mark a task as completed."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: TaskCoordinator, subentry_id: str
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, context=subentry_id)
        self.subentry_id = subentry_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{subentry_id}_complete"
        )

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.tasks.get(self.subentry_id)

    @property
    def name(self) -> str:
        """Return the name of the button."""
        task = self._task_data
        task_name = task.name if task else "Task"
        return f"{task_name} complete"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:check-circle"

    async def async_press(self) -> None:
        """Handle button press — mark task as completed."""
        self.coordinator.store.record_completion(self.subentry_id)
        await self.coordinator.async_request_refresh()
