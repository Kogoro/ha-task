"""Completion history store for the Task integration."""

import datetime
import random
from dataclasses import dataclass, field
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
    points: int = 1


@dataclass
class UndoSnapshot:
    """The state before the most recently recorded completion, to undo it."""

    completed_at: datetime.datetime
    current_assignee_index: int
    remaining_assignees: list[str]
    claimed_by: str | None
    postponed_until: datetime.date | None
    workload_assignee: str | None = None


@dataclass
class AwayPeriod:
    """A person is away from ``start`` through ``end`` (inclusive); no end means until cleared."""

    start: datetime.date
    end: datetime.date | None = None

    def covers(self, day: datetime.date) -> bool:
        """Return True if the person is away on the given day."""
        return self.start <= day and (self.end is None or day <= self.end)


@dataclass
class TaskHistory:
    """History for a single task."""

    last_completed: datetime.datetime | None = None
    completions: list[CompletionEntry] = field(default_factory=list)
    current_assignee_index: int = 0
    remaining_assignees: list[str] = field(default_factory=list)
    claimed_by: str | None = None
    postponed_until: datetime.date | None = None
    undo: UndoSnapshot | None = None
    workload_assignee: str | None = None


class TaskStore:
    """Manages persistence of task completion history."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the task store."""
        self._hass = hass
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY
        )
        self._data: dict[str, TaskHistory] = {}
        self._away: dict[str, AwayPeriod] = {}

    async def async_load(self) -> None:
        """Load data from storage."""
        raw = await self._store.async_load()
        self._away = {}
        if raw is None:
            self._data = {}
            return

        for person, period in raw.get("away", {}).items():
            self._away[person] = AwayPeriod(
                start=datetime.date.fromisoformat(period["start"]),
                end=(
                    datetime.date.fromisoformat(period["end"])
                    if period.get("end")
                    else None
                ),
            )

        self._data = {}
        for subentry_id, history_data in raw.get("tasks", {}).items():
            completions = []
            for entry in history_data.get("completions", []):
                completions.append(
                    CompletionEntry(
                        completed_at=dt_util.parse_datetime(entry["completed_at"]),
                        completed_by=entry.get("completed_by"),
                        points=entry.get("points", 1),
                    )
                )
            last_completed = None
            if history_data.get("last_completed"):
                last_completed = dt_util.parse_datetime(
                    history_data["last_completed"]
                )
            postponed_until = None
            if history_data.get("postponed_until"):
                postponed_until = datetime.date.fromisoformat(
                    history_data["postponed_until"]
                )
            undo = None
            if undo_data := history_data.get("undo"):
                undo = UndoSnapshot(
                    completed_at=dt_util.parse_datetime(undo_data["completed_at"]),
                    current_assignee_index=undo_data.get("current_assignee_index", 0),
                    remaining_assignees=list(undo_data.get("remaining_assignees", [])),
                    claimed_by=undo_data.get("claimed_by"),
                    workload_assignee=undo_data.get("workload_assignee"),
                    postponed_until=(
                        datetime.date.fromisoformat(undo_data["postponed_until"])
                        if undo_data.get("postponed_until")
                        else None
                    ),
                )
            self._data[subentry_id] = TaskHistory(
                undo=undo,
                postponed_until=postponed_until,
                last_completed=last_completed,
                completions=completions,
                current_assignee_index=history_data.get(
                    "current_assignee_index", 0
                ),
                remaining_assignees=history_data.get(
                    "remaining_assignees", []
                ),
                claimed_by=history_data.get("claimed_by"),
                workload_assignee=history_data.get("workload_assignee"),
            )

    @callback
    def get_history(self, subentry_id: str) -> TaskHistory:
        """Get history for a task subentry."""
        if subentry_id not in self._data:
            self._data[subentry_id] = TaskHistory()
        return self._data[subentry_id]

    @callback
    def record_completion(
        self,
        subentry_id: str,
        completed_by: str | None = None,
        completed_at: datetime.datetime | None = None,
        points: int = 1,
    ) -> None:
        """Record a task completion, optionally at an earlier time."""
        completed_at = completed_at or dt_util.utcnow()
        history = self.get_history(subentry_id)
        history.undo = UndoSnapshot(
            completed_at=completed_at,
            current_assignee_index=history.current_assignee_index,
            remaining_assignees=list(history.remaining_assignees),
            claimed_by=history.claimed_by,
            postponed_until=history.postponed_until,
            workload_assignee=history.workload_assignee,
        )
        history.completions.append(
            CompletionEntry(
                completed_at=completed_at, completed_by=completed_by, points=points
            )
        )
        history.completions.sort(key=lambda entry: entry.completed_at)
        history.last_completed = history.completions[-1].completed_at
        history.postponed_until = None
        self._schedule_save()

    @callback
    def undo_last_completion(self, subentry_id: str) -> CompletionEntry | None:
        """Undo the most recently recorded completion.

        Removes it and restores who was responsible, the rotation and a
        postponement. Returns the removed completion, or None if there is
        nothing to undo (nothing recorded, already undone, or after a reset).
        """
        history = self.get_history(subentry_id)
        snapshot = history.undo
        if snapshot is None:
            return None
        history.undo = None
        removed = next(
            (e for e in history.completions if e.completed_at == snapshot.completed_at),
            None,
        )
        if removed is None:
            self._schedule_save()
            return None
        history.completions.remove(removed)
        history.last_completed = (
            history.completions[-1].completed_at if history.completions else None
        )
        history.current_assignee_index = snapshot.current_assignee_index
        history.remaining_assignees = list(snapshot.remaining_assignees)
        history.claimed_by = snapshot.claimed_by
        history.postponed_until = snapshot.postponed_until
        history.workload_assignee = snapshot.workload_assignee
        self._schedule_save()
        return removed

    @callback
    def postpone(self, subentry_id: str, until: datetime.date) -> None:
        """Push the due date of a task back without recording a completion."""
        self.get_history(subentry_id).postponed_until = until
        self._schedule_save()

    @callback
    def advance_rotation(
        self,
        subentry_id: str,
        assignees: list[str],
        rotation_mode: str,
        done_by: str | None = None,
        away: frozenset[str] | set[str] = frozenset(),
    ) -> None:
        """Advance to the next assignee after completion.

        ``done_by`` is the person who was responsible when the task was
        completed. It can differ from the nominal next one when someone is away,
        and the rotation continues after that person.
        """
        history = self.get_history(subentry_id)

        if not assignees:
            return

        if rotation_mode == RotationMode.WORKLOAD:
            return  # decided from the workload when the task is completed

        if rotation_mode == RotationMode.ROUND_ROBIN:
            base = (
                assignees.index(done_by)
                if done_by in assignees
                else history.current_assignee_index
            )
            history.current_assignee_index = (base + 1) % len(assignees)
        else:
            if done_by in history.remaining_assignees:
                history.remaining_assignees.remove(done_by)
            elif done_by is None and history.remaining_assignees:
                history.remaining_assignees.pop(0)
            # The round is over once nobody who is here is left in the pool.
            if all(p in away for p in history.remaining_assignees):
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
    def workload(self, person: str, since: datetime.datetime) -> int:
        """Return the points a person completed since ``since``, across all tasks."""
        return sum(
            entry.points
            for history in self._data.values()
            for entry in history.completions
            if entry.completed_by == person and entry.completed_at >= since
        )

    @callback
    def last_completion_by(self, person: str) -> datetime.datetime | None:
        """Return when a person last completed any task."""
        times = [
            entry.completed_at
            for history in self._data.values()
            for entry in history.completions
            if entry.completed_by == person
        ]
        return max(times) if times else None

    @callback
    def set_workload_assignee(self, subentry_id: str, person: str | None) -> None:
        """Fix who is next for a task assigned by workload."""
        self.get_history(subentry_id).workload_assignee = person
        self._schedule_save()

    @callback
    def set_away(
        self, person: str, start: datetime.date, end: datetime.date | None
    ) -> None:
        """Mark a person as away from ``start`` through ``end``."""
        self._away[person] = AwayPeriod(start=start, end=end)
        self._schedule_save()

    @callback
    def clear_away(self, person: str) -> bool:
        """Mark a person as present again; return False if they were not away."""
        if self._away.pop(person, None) is None:
            return False
        self._schedule_save()
        return True

    @callback
    def away_persons(self, today: datetime.date) -> set[str]:
        """Return the persons who are away on the given day."""
        return {p for p, period in self._away.items() if period.covers(today)}

    @callback
    def away_periods(self) -> dict[str, AwayPeriod]:
        """Return all stored away periods."""
        return dict(self._away)

    @callback
    def prune_away(self, today: datetime.date) -> None:
        """Forget periods that have ended."""
        ended = [
            p for p, period in self._away.items() if period.end and period.end < today
        ]
        for person in ended:
            del self._away[person]
        if ended:
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
                        "points": entry.points,
                    }
                    for entry in history.completions
                ],
                "current_assignee_index": history.current_assignee_index,
                "remaining_assignees": history.remaining_assignees,
                "claimed_by": history.claimed_by,
                "workload_assignee": history.workload_assignee,
                "postponed_until": (
                    history.postponed_until.isoformat()
                    if history.postponed_until
                    else None
                ),
                "undo": (
                    {
                        "completed_at": history.undo.completed_at.isoformat(),
                        "current_assignee_index": history.undo.current_assignee_index,
                        "remaining_assignees": history.undo.remaining_assignees,
                        "claimed_by": history.undo.claimed_by,
                        "workload_assignee": history.undo.workload_assignee,
                        "postponed_until": (
                            history.undo.postponed_until.isoformat()
                            if history.undo.postponed_until
                            else None
                        ),
                    }
                    if history.undo
                    else None
                ),
            }
        away = {
            person: {
                "start": period.start.isoformat(),
                "end": period.end.isoformat() if period.end else None,
            }
            for person, period in self._away.items()
        }
        return {"tasks": tasks, "away": away}
