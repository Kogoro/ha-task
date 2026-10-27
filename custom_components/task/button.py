"""Button platform for the Task integration."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TaskConfigEntry, TaskCoordinator, TaskData
from .device import task_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task button entities."""
    coordinator = entry.runtime_data

    for subentry_id in coordinator.data.tasks:
        async_add_entities(
            [
                TaskCompleteButton(coordinator, subentry_id),
                TaskAssignToMeButton(coordinator, subentry_id),
            ],
            config_subentry_id=subentry_id,
        )

    for subentry_id in coordinator.data.maintenance:
        async_add_entities(
            [
                TaskCompleteButton(coordinator, subentry_id),
                TaskAssignToMeButton(coordinator, subentry_id),
            ],
            config_subentry_id=subentry_id,
        )


class TaskCompleteButton(CoordinatorEntity[TaskCoordinator], ButtonEntity):
    """Button to mark a task as completed."""

    _attr_has_entity_name = True
    _attr_translation_key = "complete"

    def __init__(
        self, coordinator: TaskCoordinator, subentry_id: str
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, context=subentry_id)
        self.subentry_id = subentry_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{subentry_id}_complete"
        )
        self._attr_device_info = task_device_info(coordinator, subentry_id)

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator._find_item(self.subentry_id)

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return "Complete"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:check-circle"

    async def async_press(self) -> None:
        """Handle button press — record completion and advance rotation."""
        self.coordinator.complete_task(self.subentry_id)
        await self.coordinator.async_request_refresh()


class TaskAssignToMeButton(CoordinatorEntity[TaskCoordinator], ButtonEntity):
    """Button to assign a task to the current HA user."""

    _attr_has_entity_name = True
    _attr_translation_key = "assign_to_me"

    def __init__(
        self, coordinator: TaskCoordinator, subentry_id: str
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, context=subentry_id)
        self.subentry_id = subentry_id
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{subentry_id}_assign_to_me"
        )
        self._attr_device_info = task_device_info(coordinator, subentry_id)

    @property
    def _task_data(self) -> TaskData | None:
        """Get current task data."""
        if self.coordinator.data is None:
            return None
        return self.coordinator._find_item(self.subentry_id)

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return "Assign to me"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:account-arrow-left"

    async def async_press(self) -> None:
        """Handle button press — assign the task to the calling user's person entity."""
        user_id = self._context.user_id if self._context else None
        person_id = None
        if user_id:
            for state in self.hass.states.async_all("person"):
                if state.attributes.get("user_id") == user_id:
                    person_id = state.entity_id
                    break
        self.coordinator.assign_to(self.subentry_id, person_id)
        await self.coordinator.async_request_refresh()
