"""DataUpdateCoordinator for the Task integration."""

import datetime
from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AREA_ID,
    CONF_ASSIGNEE,
    CONF_ASSIGNEES,
    CONF_DEVICE_ID,
    CONF_INTERVAL_DAYS,
    CONF_ROTATION_MODE,
    DOMAIN,
    SUBENTRY_TYPE_MAINTENANCE,
    SUBENTRY_TYPE_TASK,
    RotationMode,
)
from .store import TaskStore

_LOGGER = logging.getLogger(__name__)

type TaskConfigEntry = ConfigEntry[TaskCoordinator]


@dataclass
class TaskData:
    """Computed state for a single task or maintenance item."""

    subentry_id: str
    subentry_type: str
    name: str
    description: str | None
    assignees: list[str]
    current_assignee: str | None
    rotation_mode: str
    interval_days: int
    icon: str | None
    last_completed: datetime.datetime | None
    last_completed_by: str | None
    next_due: datetime.date | None
    days_until_due: int | None
    overdue: bool
    device_id: str | None = None


@dataclass
class TaskCoordinatorData:
    """All computed data for a config entry."""

    area_id: str
    area_name: str
    tasks: dict[str, TaskData]
    maintenance: dict[str, TaskData]


class TaskCoordinator(DataUpdateCoordinator[TaskCoordinatorData]):
    """Coordinator for the Task integration."""

    config_entry: TaskConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: TaskConfigEntry,
        store: TaskStore,
    ) -> None:
        """Initialize the coordinator."""
        self.store = store
        self._previous_overdue: set[str] = set()
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN}_{config_entry.entry_id}",
        )

    def _resolve_assignees(self, subentry_data: dict) -> list[str]:
        """Resolve assignees list from config, with backward compatibility."""
        assignees = list(subentry_data.get(CONF_ASSIGNEES, []))
        if not assignees:
            old_assignee = subentry_data.get(CONF_ASSIGNEE)
            if old_assignee:
                assignees = [old_assignee]
        return assignees

    def _compute_current_assignee(
        self,
        subentry_id: str,
        assignees: list[str],
        rotation_mode: str,
    ) -> str | None:
        """Compute current assignee from rotation state."""
        if not assignees:
            return self.store.get_history(subentry_id).claimed_by

        history = self.store.get_history(subentry_id)

        if rotation_mode == RotationMode.ROUND_ROBIN:
            index = history.current_assignee_index % len(assignees)
            return assignees[index]

        self.store.init_random_pool(subentry_id, assignees)
        remaining = history.remaining_assignees
        return remaining[0] if remaining else None

    def _compute_subentry_data(
        self,
        subentry_id: str,
        subentry_type: str,
        data: dict,
        title: str,
        today: datetime.date,
    ) -> TaskData:
        """Compute derived state for a single subentry."""
        history = self.store.get_history(subentry_id)
        default_interval = 7 if subentry_type == SUBENTRY_TYPE_TASK else 30
        interval_days = data.get(CONF_INTERVAL_DAYS, default_interval)
        last_completed = history.last_completed

        next_due: datetime.date | None = None
        days_until_due: int | None = None
        overdue = False

        if last_completed:
            next_due = (
                last_completed + datetime.timedelta(days=interval_days)
            ).date()
            days_until_due = (next_due - today).days
            overdue = days_until_due < 0
        else:
            days_until_due = 0
            overdue = True
            next_due = today

        assignees = self._resolve_assignees(dict(data))
        rotation_mode = data.get(
            CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
        )
        current_assignee = self._compute_current_assignee(
            subentry_id, assignees, rotation_mode
        )

        last_completed_by = None
        if history.completions:
            last_completed_by = history.completions[-1].completed_by

        return TaskData(
            subentry_id=subentry_id,
            subentry_type=subentry_type,
            name=title,
            description=data.get("description"),
            assignees=assignees,
            current_assignee=current_assignee,
            rotation_mode=rotation_mode,
            interval_days=interval_days,
            icon=data.get("icon"),
            last_completed=last_completed,
            last_completed_by=last_completed_by,
            next_due=next_due,
            days_until_due=days_until_due,
            overdue=overdue,
            device_id=data.get(CONF_DEVICE_ID),
        )

    async def _async_update_data(self) -> TaskCoordinatorData:
        """Compute derived state for all tasks and maintenance items."""
        entry = self.config_entry
        area_id = entry.data[CONF_AREA_ID]

        area_reg = ar.async_get(self.hass)
        area_entry = area_reg.async_get_area(area_id)
        area_name = area_entry.name if area_entry else area_id

        today = dt_util.now().date()
        tasks: dict[str, TaskData] = {}
        maintenance: dict[str, TaskData] = {}

        for subentry in entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_TYPE_TASK:
                tasks[subentry.subentry_id] = self._compute_subentry_data(
                    subentry.subentry_id,
                    SUBENTRY_TYPE_TASK,
                    dict(subentry.data),
                    subentry.title,
                    today,
                )
            elif subentry.subentry_type == SUBENTRY_TYPE_MAINTENANCE:
                maintenance[subentry.subentry_id] = self._compute_subentry_data(
                    subentry.subentry_id,
                    SUBENTRY_TYPE_MAINTENANCE,
                    dict(subentry.data),
                    subentry.title,
                    today,
                )

        all_items = {**tasks, **maintenance}
        current_overdue = {sid for sid, t in all_items.items() if t.overdue}
        newly_overdue = current_overdue - self._previous_overdue
        for sid in newly_overdue:
            item = all_items[sid]
            event_type = (
                "task_overdue"
                if item.subentry_type == SUBENTRY_TYPE_TASK
                else "maintenance_overdue"
            )
            event_data = {
                "subentry_id": sid,
                "task_name": item.name,
                "area_id": area_id,
                "area_name": area_name,
                "days_overdue": abs(item.days_until_due) if item.days_until_due else 0,
                "current_assignee": item.current_assignee,
            }
            if item.device_id:
                event_data["device_id"] = item.device_id
            self.hass.bus.async_fire(event_type, event_data)
        self._previous_overdue = current_overdue

        return TaskCoordinatorData(
            area_id=area_id,
            area_name=area_name,
            tasks=tasks,
            maintenance=maintenance,
        )

    def _find_item(self, subentry_id: str) -> TaskData | None:
        """Find a task or maintenance item by subentry ID."""
        if not self.data:
            return None
        item = self.data.tasks.get(subentry_id)
        if item is None:
            item = self.data.maintenance.get(subentry_id)
        return item

    def complete_task(
        self, subentry_id: str, completed_by: str | None = None
    ) -> None:
        """Record completion and advance the assignee rotation."""
        item = self._find_item(subentry_id)
        assignees: list[str] = []
        rotation_mode = RotationMode.ROUND_ROBIN

        if item:
            assignees = item.assignees
            rotation_mode = item.rotation_mode

        now = dt_util.utcnow()
        self.store.record_completion(subentry_id, completed_by=completed_by)
        self.store.clear_claim(subentry_id)
        if assignees:
            self.store.advance_rotation(subentry_id, assignees, rotation_mode)

        next_assignee = (
            self._compute_current_assignee(subentry_id, assignees, rotation_mode)
            if assignees
            else None
        )
        interval_days = item.interval_days if item else 7
        next_due = (now + datetime.timedelta(days=interval_days)).date()

        event_type = (
            "task_completed"
            if not item or item.subentry_type == SUBENTRY_TYPE_TASK
            else "maintenance_completed"
        )
        event_data = {
            "subentry_id": subentry_id,
            "task_name": item.name if item else None,
            "area_id": self.data.area_id if self.data else None,
            "area_name": self.data.area_name if self.data else None,
            "completed_by": completed_by,
            "completed_at": now.isoformat(),
            "next_due": next_due.isoformat(),
            "next_assignee": next_assignee,
        }
        if item and item.device_id:
            event_data["device_id"] = item.device_id
        self.hass.bus.async_fire(event_type, event_data)

    def assign_to(self, subentry_id: str, person_id: str | None) -> None:
        """Override the current assignee for a task or maintenance item."""
        item = self._find_item(subentry_id)
        if not item or not person_id:
            return

        if not item.assignees:
            self.store.claim_task(subentry_id, person_id)
            return

        if person_id in item.assignees:
            if item.rotation_mode == RotationMode.ROUND_ROBIN:
                index = item.assignees.index(person_id)
                history = self.store.get_history(subentry_id)
                history.current_assignee_index = index
                self.store._schedule_save()
            else:
                history = self.store.get_history(subentry_id)
                remaining = [a for a in history.remaining_assignees if a != person_id]
                history.remaining_assignees = [person_id] + remaining
                self.store._schedule_save()
