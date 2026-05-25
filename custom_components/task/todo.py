"""Todo platform for the Task integration."""

import logging

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import TaskConfigEntry, TaskCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Task todo list entity."""
    coordinator = entry.runtime_data
    async_add_entities([TaskTodoList(coordinator)])


class TaskTodoList(CoordinatorEntity[TaskCoordinator], TodoListEntity):
    """A todo list representing all tasks in an area."""

    _attr_has_entity_name = True
    _attr_translation_key = "task_list"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(self, coordinator: TaskCoordinator) -> None:
        """Initialize the todo list entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_todo"
        self._attr_config_entry_id = entry.entry_id

    @property
    def name(self) -> str:
        """Return the name of the todo list."""
        return f"{self.coordinator.data.area_name} Tasks"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:clipboard-check-outline"

    @property
    def todo_items(self) -> list[TodoItem]:
        """Return the todo items."""
        items: list[TodoItem] = []
        for task in self.coordinator.data.tasks.values():
            if task.last_completed and not task.overdue:
                status = TodoItemStatus.COMPLETED
            else:
                status = TodoItemStatus.NEEDS_ACTION

            items.append(
                TodoItem(
                    uid=task.subentry_id,
                    summary=task.name,
                    description=task.description,
                    due=task.next_due,
                    status=status,
                )
            )

        items.sort(
            key=lambda item: (
                item.status == TodoItemStatus.COMPLETED,
                item.due or "9999-12-31",
            )
        )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new todo item (task) via subentry."""
        _LOGGER.info(
            "Todo item creation requested for '%s' — "
            "use the config flow to add tasks",
            item.summary,
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a todo item status."""
        if item.uid is None:
            return

        if item.status == TodoItemStatus.COMPLETED:
            self.coordinator.store.record_completion(item.uid)
            await self.coordinator.async_request_refresh()
