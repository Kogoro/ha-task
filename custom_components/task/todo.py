"""Todo platform for the Task integration."""

from types import MappingProxyType

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ASSIGNEE, CONF_INTERVAL_DAYS, SUBENTRY_TYPE_TASK
from .coordinator import TaskConfigEntry, TaskCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TaskConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Task todo entity (one per area/config entry)."""
    coordinator = entry.runtime_data
    async_add_entities([TaskTodoEntity(coordinator)])


class TaskTodoEntity(CoordinatorEntity[TaskCoordinator], TodoListEntity):
    """A todo list representing all tasks in an area."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(self, coordinator: TaskCoordinator) -> None:
        """Initialize the todo entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_todo"

    @property
    def name(self) -> str:
        """Return the name."""
        return f"{self.coordinator.data.area_name} tasks"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:clipboard-list"

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return todo items for all tasks in this area."""
        if self.coordinator.data is None:
            return None

        items: list[TodoItem] = []
        for task in self.coordinator.data.tasks.values():
            status = (
                TodoItemStatus.NEEDS_ACTION
                if task.overdue or task.days_until_due is not None and task.days_until_due <= 0
                else TodoItemStatus.COMPLETED
            )
            items.append(
                TodoItem(
                    uid=task.subentry_id,
                    summary=task.name,
                    status=status,
                    description=task.description,
                    due=task.next_due,
                )
            )
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create a new task via subentry."""
        entry = self.coordinator.config_entry
        subentry = ConfigSubentry(
            data=MappingProxyType({
                CONF_INTERVAL_DAYS: 7,
                CONF_ASSIGNEE: None,
                "description": item.description,
                "icon": None,
            }),
            subentry_type=SUBENTRY_TYPE_TASK,
            title=item.summary or "New Task",
            unique_id=None,
        )
        self.hass.config_entries.async_add_subentry(entry, subentry)
        await self.coordinator.async_request_refresh()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update a todo item — mark as completed if status changed."""
        if item.uid is None:
            return

        if item.status == TodoItemStatus.COMPLETED:
            self.coordinator.store.record_completion(item.uid)
            await self.coordinator.async_request_refresh()
