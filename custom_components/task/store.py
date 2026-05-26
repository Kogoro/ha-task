"""Completion history store for the Task integration."""

import datetime
from dataclasses import dataclass, field
import random
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import STORAGE_KEY, STORAGE_VERSION, RotationMode


@dataclass
class CompletionEntry:
    """A single completion record."""

    completed_at: datetime.datetime
    completed_by: str | None = None


@dataclass
class TaskHistory:
    """History for a single task."""

    last_completed: datetime.datetime | None = None
    completions: list[CompletionEntry] = field(default_factory=list)
    current_assignee_index: int = 0
    remaining_assignees: list[str] = field(default_factory=list)
    claimed_by: str | None = None


class TaskStore:
    """Manages persistence of task completion history."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the task store."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, TaskHistory] = {}

    async def async_load(self) -> None:
        """Load data from storage."""
        raw = await self._store.async_load()
        if raw is None:
            self._data = {}
            return

        self._data = {}
        for subentry_id, history_data in raw.get("tasks", {}).items():
            completions = []
            for entry in history_data.get("completions", []):
                completions.append(
                    CompletionEntry(
                        completed_at=dt_util.parse_datetime(entry["completed_at"]),
                        completed_by=entry.get("completed_by"),
                    )
                )
            last_completed = None
            if history_data.get("last_completed"):
                last_completed = dt_util.parse_datetime(
                    history_data["last_completed"]
                )
            self._data[subentry_id] = TaskHistory(
                last_completed=last_completed,
                completions=completions,
                current_assignee_index=history_data.get(
                    "current_assignee_index", 0
                ),
                remaining_assignees=history_data.get(
                    "remaining_assignees", []
                ),
                claimed_by=history_data.get("claimed_by"),
            )

    @callback
    def get_history(self, subentry_id: str) -> TaskHistory:
        """Get history for a task subentry."""
        if subentry_id not in self._data:
            self._data[subentry_id] = TaskHistory()
        return self._data[subentry_id]

    @callback
    def record_completion(
        self, subentry_id: str, completed_by: str | None = None
    ) -> None:
        """Record a task completion."""
        now = dt_util.utcnow()
        history = self.get_history(subentry_id)
        history.last_completed = now
        history.completions.append(
            CompletionEntry(completed_at=now, completed_by=completed_by)
        )
        self._schedule_save()

    @callback
    def advance_rotation(
        self,
        subentry_id: str,
        assignees: list[str],
        rotation_mode: str,
    ) -> None:
        """Advance to the next assignee after completion."""
        history = self.get_history(subentry_id)

        if not assignees:
            return

        if rotation_mode == RotationMode.ROUND_ROBIN:
            history.current_assignee_index = (
                (history.current_assignee_index + 1) % len(assignees)
            )
        else:
            if history.remaining_assignees:
                history.remaining_assignees.pop(0)
            if not history.remaining_assignees:
                pool = list(assignees)
                random.shuffle(pool)
                history.remaining_assignees = pool

        self._schedule_save()

    @callback
    def init_random_pool(
        self, subentry_id: str, assignees: list[str]
    ) -> None:
        """Initialize the random assignee pool if empty or stale."""
        history = self.get_history(subentry_id)
        valid = [a for a in history.remaining_assignees if a in assignees]
        if not valid:
            pool = list(assignees)
            random.shuffle(pool)
            history.remaining_assignees = pool
        elif len(valid) != len(history.remaining_assignees):
            history.remaining_assignees = valid
        else:
            return
        self._schedule_save()

    @callback
    def claim_task(self, subentry_id: str, person_id: str) -> None:
        """Set claimed_by for an unassigned task."""
        history = self.get_history(subentry_id)
        history.claimed_by = person_id
        self._schedule_save()

    @callback
    def clear_claim(self, subentry_id: str) -> None:
        """Clear claimed_by so the task returns to unassigned."""
        history = self.get_history(subentry_id)
        if history.claimed_by is not None:
            history.claimed_by = None
            self._schedule_save()

    @callback
    def reset_history(self, subentry_id: str) -> None:
        """Reset completion history for a task."""
        self._data[subentry_id] = TaskHistory()
        self._schedule_save()

    @callback
    def remove_history(self, subentry_id: str) -> None:
        """Remove history for a deleted task."""
        self._data.pop(subentry_id, None)
        self._schedule_save()

    @callback
    def _schedule_save(self) -> None:
        """Schedule saving data to disk."""
        self._store.async_delay_save(self._serialize, 60)

    @callback
    def _serialize(self) -> dict[str, Any]:
        """Serialize store data."""
        tasks: dict[str, Any] = {}
        for subentry_id, history in self._data.items():
            tasks[subentry_id] = {
                "last_completed": (
                    history.last_completed.isoformat()
                    if history.last_completed
                    else None
                ),
                "completions": [
                    {
                        "completed_at": entry.completed_at.isoformat(),
                        "completed_by": entry.completed_by,
                    }
                    for entry in history.completions
                ],
                "current_assignee_index": history.current_assignee_index,
                "remaining_assignees": history.remaining_assignees,
                "claimed_by": history.claimed_by,
            }
        return {"tasks": tasks}
