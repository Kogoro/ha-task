---
id: "2026-05-25-001"
title: "Household Task Integration — Implementation Plan"
type: feature
domain: task
status: draft
created: 2026-05-25
author: christopher
tags: [hacs, integration, task-management, recurring-tasks, area-based]
phases:
  - id: phase-1
    title: "Area-Based Tasks"
    units: [U1, U2, U3, U4, U5, U6, U7, U8, U9, U10]
    status: planned
  - id: phase-2
    title: "Device Maintenance"
    units: []
    status: deferred
---

# Household Task Integration — Implementation Plan

## Summary

A HACS custom component for Home Assistant that manages recurring household tasks and chores (vacuuming, window cleaning, home maintenance) with area-based organization, optional assignees, and completion tracking.

**Bounded Context:** `task` — recurring obligation lifecycle (creation, scheduling, due-date computation, completion recording, history).

**Ubiquitous Language:**

| Term | Meaning |
|---|---|
| Task | A named recurring obligation with an interval, optional assignee, and completion history |
| Area Group | A config entry scoped to one HA area, acting as a container for tasks |
| Completion | The act of marking a task done, recorded with timestamp and actor |
| Interval | The number of days between expected completions |
| Due Date | `last_completed + interval_days`; absent completion history → due immediately |
| Overdue | `now > due_date` |

## Design Decisions (Resolved)

| Decision | Choice | Rationale |
|---|---|---|
| Integration type | Self-contained HACS component | No upstream dependency; ships independently |
| Config model | Config entry per area, ConfigSubentry per task | Mirrors HA's area→device→entity hierarchy |
| Assignee model | Optional `person.` entity_id | Leverages existing HA person registry |
| Recurrence model | `interval_days: int` | Simplest correct model; cron/RRULE deferred |
| Persistence | `Store` in `.storage/task.history` | Standard HA pattern; survives restarts |
| Structural reference | Battery Notes by andrew-codechimp | Proven HACS pattern for coordinator + store + config flow |
| Python target | 3.14+ (no `from __future__ import annotations`) | Aligns with HA direction |

## Architecture Overview

```
Config Entry (area_id)
├── ConfigSubentry "task" (name, interval_days, assignee, description, icon)
├── ConfigSubentry "task" ...
└── ...

TaskStore (.storage/task.history)
├── {subentry_id}: {last_completed, completions: [{completed_at, completed_by}]}
└── ...

TaskCoordinator (per config entry)
├── loads subentries + store
├── computes derived state (due dates, overdue flags)
└── feeds entity platforms

Entity Platforms
├── sensor   — one per task (days until due)
├── button   — one per task (mark complete)
├── todo     — one per area (task list)
└── calendar — one per area (recurring events)
```

## Dependency Graph

```
U1 (scaffolding)
 └─► U2 (store)
      └─► U3 (config flow)
           └─► U4 (coordinator)
                ├─► U5 (sensor)
                ├─► U6 (button)
                ├─► U7 (todo)
                ├─► U8 (calendar)
                └─► U9 (services)
                     └─► U10 (init — wires everything)
```

U1→U2→U3→U4 are strictly sequential. U5–U9 can be developed in parallel once U4 is stable. U10 integrates everything.

---

## Phase 1: Area-Based Tasks

### U1: Project Scaffolding

**Goal:** Establish the HACS-compatible project structure with all required metadata and constants.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/__init__.py` | Placeholder (wired in U10) |
| `custom_components/task/manifest.json` | Integration manifest |
| `custom_components/task/const.py` | Domain constant, storage keys, defaults |
| `custom_components/task/strings.json` | User-facing strings for config flow and services |
| `custom_components/task/icons.json` | Default icons for entity platforms |
| `hacs.json` | HACS repository metadata |
| `README.md` | Repository readme |

**manifest.json shape:**

```json
{
  "domain": "task",
  "name": "Household Tasks",
  "codeowners": [],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/.../ha-task",
  "iot_class": "calculated",
  "version": "0.1.0"
}
```

**const.py exports:**

```python
DOMAIN = "task"
STORAGE_KEY = "task.history"
STORAGE_VERSION = 1
DEFAULT_INTERVAL_DAYS = 7
CONF_AREA_ID = "area_id"
CONF_INTERVAL_DAYS = "interval_days"
CONF_ASSIGNEE = "assignee"
CONF_DESCRIPTION = "description"
CONF_ICON = "icon"
PLATFORMS = ["sensor", "button", "todo", "calendar"]
```

**Test scenarios:**

- `manifest.json` parses without error and contains required keys
- `const.py` exports are importable and have expected types

---

### U2: Store Layer

**Goal:** Persist per-task completion history across HA restarts using the standard `Store` helper.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/store.py` | `TaskStore` class |

**Data shape (`.storage/task.history`):**

```json
{
  "version": 1,
  "data": {
    "<subentry_id>": {
      "last_completed": "2026-05-20T14:30:00+00:00",
      "completions": [
        {
          "completed_at": "2026-05-20T14:30:00+00:00",
          "completed_by": "person.alice"
        }
      ]
    }
  }
}
```

**TaskStore interface:**

```python
@dataclasses.dataclass
class CompletionRecord:
    completed_at: datetime
    completed_by: str | None

@dataclasses.dataclass
class TaskHistory:
    last_completed: datetime | None
    completions: list[CompletionRecord]

class TaskStore:
    def __init__(self, hass: HomeAssistant) -> None: ...
    async def async_load(self) -> dict[str, TaskHistory]: ...
    async def async_save(self) -> None: ...
    def record_completion(
        self, subentry_id: str, completed_by: str | None = None
    ) -> None: ...
    def reset_task(self, subentry_id: str) -> None: ...
    def remove_task(self, subentry_id: str) -> None: ...
    def get_history(self, subentry_id: str) -> TaskHistory: ...
```

**Design notes:**

- Uses `homeassistant.helpers.storage.Store` with `async_delay_save` to batch writes
- Returns a default empty `TaskHistory` for unknown subentry_ids (no KeyError)
- `record_completion` timestamps with `dt_util.utcnow()` when no explicit time given
- Completion list capped at a configurable max (default 100) per task to bound storage growth
- Single store instance shared across all config entries (keyed by subentry_id which is globally unique)

**Test scenarios:**

- Load from empty store returns empty dict
- `record_completion` persists and is retrievable via `get_history`
- `reset_task` clears history for one task without affecting others
- `remove_task` deletes all data for a subentry_id
- Completion list respects max cap (oldest trimmed)
- Round-trip: save → reload → data matches
- Concurrent completions on different tasks do not interfere

---

### U3: Config Flow

**Goal:** ConfigFlow creates area-scoped config entries; ConfigSubentryFlow adds/edits individual tasks within each entry.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/config_flow.py` | `TaskConfigFlow`, `TaskSubentryFlowHandler` |

**Config Entry data:**

```python
{"area_id": "living_room"}  # area registry ID
```

**ConfigSubentry data (`subentry_type="task"`):**

```python
{
    "name": "Vacuum",               # str, required
    "interval_days": 7,             # int, required, min=1
    "assignee": "person.alice",     # str | None, optional
    "description": "Vacuum all rooms including under furniture",  # str | None
    "icon": "mdi:vacuum"            # str | None
}
```

**TaskConfigFlow:**

- Step `user`: `AreaSelector` to pick an area → creates config entry with `area_id`
- Title set to area name from AreaRegistry
- Validates that no existing config entry already targets the same area

**TaskSubentryFlowHandler:**

- `subentry_type = "task"`
- Step `user`: form with `name` (TextSelector), `interval_days` (NumberSelector, min=1), `assignee` (EntitySelector filtering `person` domain, optional), `description` (TextSelector, optional), `icon` (IconSelector, optional)
- Creates subentry; coordinator picks it up on next refresh
- Reconfigure step reuses the same form, pre-filled with current values

**HA patterns to use:**

- `ConfigFlow` with `async_step_user`
- `ConfigSubentryFlow` with `_get_entry()` to access parent config entry
- `AreaSelector()` from `homeassistant.helpers.selector`
- `EntitySelector(EntitySelectorConfig(domain="person"))` for assignee
- `vol.Required` / `vol.Optional` schema validation

**Test scenarios:**

- Happy path: create area config entry → entry has correct `area_id` and title
- Duplicate area rejected with appropriate error
- Add task subentry → subentry appears in config entry with correct data
- All optional fields can be omitted
- `interval_days` < 1 rejected
- Reconfigure task subentry → values updated
- Remove task subentry → subentry removed, store cleanup triggered

---

### U4: Coordinator

**Goal:** `TaskCoordinator` extends `DataUpdateCoordinator`, loads subentries + store data, and computes derived state for all entity platforms.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/coordinator.py` | `TaskCoordinator`, `TaskData`, `TaskItem` |

**Data model:**

```python
@dataclasses.dataclass
class TaskItem:
    subentry_id: str
    name: str
    interval_days: int
    assignee: str | None
    description: str | None
    icon: str | None
    area_id: str
    last_completed: datetime | None
    next_due: datetime | None
    days_until_due: int | None
    overdue: bool
    completions: list[CompletionRecord]

@dataclasses.dataclass
class TaskData:
    area_id: str
    area_name: str
    tasks: dict[str, TaskItem]  # keyed by subentry_id
```

**TaskCoordinator behavior:**

- One coordinator instance per config entry
- `_async_update_data` reads subentries from the config entry, merges with `TaskStore` history
- Computes `next_due = last_completed + timedelta(days=interval_days)` (None if never completed → due immediately)
- Computes `days_until_due = (next_due - now).days` (negative when overdue; None if never completed treated as -∞ or a sentinel like -9999)
- Computes `overdue = days_until_due is not None and days_until_due < 0`, or `True` if never completed
- Update interval: 15 minutes (derived state changes with clock, but 15 min is sufficient granularity)
- Exposes `async_complete_task(subentry_id, completed_by)` and `async_reset_task(subentry_id)` as convenience methods that write to store and trigger refresh

**Test scenarios:**

- Coordinator loads tasks from subentries and merges store history
- `days_until_due` computed correctly for: never completed, completed today, completed and overdue, completed and not yet due
- `overdue` flag correct for each case above
- `async_complete_task` updates store and triggers coordinator refresh
- `async_reset_task` clears history and triggers refresh
- Adding/removing subentries reflected after coordinator refresh
- Empty config entry (no tasks) produces empty `TaskData.tasks`

---

### U5: Sensor Platform

**Goal:** One sensor entity per task showing days until due, with rich attributes.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/sensor.py` | `TaskSensor` entity, `async_setup_entry` |

**Entity details:**

| Property | Value |
|---|---|
| Unique ID | `{config_entry_id}_{subentry_id}_sensor` |
| Name | Task name (from subentry) |
| State | `days_until_due` (int); negative if overdue |
| Device class | None (custom) |
| State class | `measurement` |
| Unit | `days` (native) |
| Icon | Task icon or `mdi:checkbox-marked-circle-outline` |

**Extra state attributes:**

```python
{
    "assignee": "person.alice",
    "interval_days": 7,
    "last_completed": "2026-05-20T14:30:00+00:00",
    "next_due": "2026-05-27T14:30:00+00:00",
    "area_id": "living_room",
    "overdue": False,
}
```

**Implementation notes:**

- Extends `CoordinatorEntity` with `TaskCoordinator`
- Uses `entity_platform.async_get_current_platform()` or manual `async_setup_entry` with `async_add_entities`
- Listens for subentry add/remove to dynamically add/remove sensor entities
- Entity tied to config entry + subentry via `entity_registry` associations

**Test scenarios:**

- Sensor state reflects `days_until_due` from coordinator
- Attributes contain all expected fields
- Sensor updates when coordinator refreshes
- Sensor added dynamically when new task subentry created
- Sensor removed when task subentry deleted
- Never-completed task shows appropriate overdue state

---

### U6: Button Platform

**Goal:** One button entity per task for quick "mark complete" action.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/button.py` | `TaskCompleteButton` entity, `async_setup_entry` |

**Entity details:**

| Property | Value |
|---|---|
| Unique ID | `{config_entry_id}_{subentry_id}_button` |
| Name | `"Complete {task_name}"` |
| Icon | `mdi:check-circle` or task icon |
| Device class | None |

**Behavior:**

- `async_press()` calls `coordinator.async_complete_task(subentry_id)`
- Optionally passes `completed_by` from HA context user if available
- Extends `CoordinatorEntity` for consistent lifecycle

**Test scenarios:**

- Button press records completion in store
- Button press triggers coordinator refresh
- Sensor state updates after button press
- Button added/removed with subentry lifecycle
- Press without authenticated user context → `completed_by` is None

---

### U7: Todo Platform

**Goal:** One `TodoListEntity` per area config entry, with tasks as `TodoItem`s. Status reflects due/overdue state.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/todo.py` | `TaskTodoList` entity, `async_setup_entry` |

**Entity details:**

| Property | Value |
|---|---|
| Unique ID | `{config_entry_id}_todo` |
| Name | `"{area_name} Tasks"` |
| Supported features | `TodoListEntityFeature.UPDATE_TODO_ITEM` |

**TodoItem mapping:**

```python
TodoItem(
    uid=subentry_id,
    summary=task.name,
    description=task.description,
    due=task.next_due.date() if task.next_due else None,
    status=(
        TodoItemStatus.COMPLETED
        if task.last_completed and not task.overdue
        else TodoItemStatus.NEEDS_ACTION
    ),
)
```

**Behavior:**

- `async_update_todo_item`: when status changed to COMPLETED → `coordinator.async_complete_task(uid)`
- Does NOT support `CREATE_TODO_ITEM` or `DELETE_TODO_ITEM` (tasks managed via config subentries)
- Items sorted by: overdue first (most overdue first), then by next_due ascending

**Test scenarios:**

- Todo list contains all tasks from coordinator
- Overdue task has `NEEDS_ACTION` status
- Completed and not-yet-due task has `COMPLETED` status
- Never-completed task has `NEEDS_ACTION` status
- Marking item complete via todo `async_update_todo_item` records completion
- Todo list updates when coordinator refreshes
- Correct item count and ordering

---

### U8: Calendar Platform

**Goal:** One `CalendarEntity` per area, with tasks as recurring calendar events.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/calendar.py` | `TaskCalendar` entity, `async_setup_entry` |

**Entity details:**

| Property | Value |
|---|---|
| Unique ID | `{config_entry_id}_calendar` |
| Name | `"{area_name} Task Schedule"` |

**CalendarEvent mapping:**

For each task, generate recurring events based on `last_completed` and `interval_days`:

```python
CalendarEvent(
    summary=task.name,
    start=next_due_date,  # date (all-day event)
    end=next_due_date + timedelta(days=1),
    description=task.description,
    uid=subentry_id,
)
```

**Behavior:**

- `event` property: returns the next upcoming (or current overdue) event across all tasks
- `async_get_events(start_date, end_date)`: generates synthetic recurring events within the requested range for each task, projecting forward from `last_completed` (or entry creation) by `interval_days`
- All-day events (date, not datetime)

**Test scenarios:**

- Calendar returns events within requested date range
- Event recurrence matches `interval_days` for each task
- `event` property returns the soonest due/overdue task
- No events for empty task list
- Events update after completion (next occurrence shifts)

---

### U9: Services

**Goal:** Register `task.complete_task` and `task.reset_task` as HA services with proper schemas.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/services.py` | Service registration helpers |
| `custom_components/task/services.yaml` | Service descriptions (if not using strings.json) |

**Service schemas:**

```python
# task.complete_task
{
    vol.Required("config_entry_id"): str,
    vol.Required("subentry_id"): str,
    vol.Optional("completed_by"): str,  # person entity_id
}

# task.reset_task
{
    vol.Required("config_entry_id"): str,
    vol.Required("subentry_id"): str,
}
```

**Implementation notes:**

- Services look up the coordinator from `hass.data[DOMAIN][config_entry_id]`
- `complete_task` delegates to `coordinator.async_complete_task()`
- `reset_task` delegates to `coordinator.async_reset_task()`
- Validation: raise `ServiceValidationError` if config_entry_id or subentry_id not found

**Alternative targeting (preferred if feasible):** Use entity-targeted services instead of raw IDs. The button entity_id or sensor entity_id could serve as the target, simplifying the schema. Evaluate during implementation whether entity-targeted services are cleaner for automations.

**Test scenarios:**

- `complete_task` with valid IDs records completion
- `complete_task` with invalid config_entry_id raises error
- `complete_task` with invalid subentry_id raises error
- `reset_task` clears history
- Services registered on integration setup and removed on unload

---

### U10: Integration Init

**Goal:** Wire everything together in `__init__.py` — setup coordinators, store, platforms, services, and handle entry lifecycle.

**Files:**

| Path | Purpose |
|---|---|
| `custom_components/task/__init__.py` | `async_setup_entry`, `async_unload_entry`, `async_remove_entry`, subentry lifecycle hooks |

**Setup flow (`async_setup_entry`):**

1. Get or create shared `TaskStore` (singleton in `hass.data[DOMAIN]["store"]`)
2. Load store data if first entry
3. Create `TaskCoordinator` for this config entry
4. Store coordinator in `hass.data[DOMAIN][entry.entry_id]`
5. `await coordinator.async_config_entry_first_refresh()`
6. Forward setup to all platforms: `sensor`, `button`, `todo`, `calendar`
7. Register services (idempotent — only on first entry setup)
8. Register subentry change listeners for dynamic entity add/remove

**Unload flow (`async_unload_entry`):**

1. Unload platforms
2. Remove coordinator from `hass.data`
3. If last entry, unregister services and clean up store reference

**Subentry lifecycle:**

- `async_setup_subentry`: trigger coordinator refresh, platform adds new entities
- `async_unload_subentry`: trigger coordinator refresh, platform removes entities, clean store data

**Test scenarios:**

- Full setup → coordinator created, platforms loaded, services registered
- Unload → platforms unloaded, coordinator removed
- Add subentry at runtime → new entities appear
- Remove subentry at runtime → entities removed, store cleaned
- Multiple config entries coexist independently
- Reload integration → state preserved from store

---

## Phase 2: Device Maintenance (Deferred)

**Scope:** Attach maintenance tasks to specific HA devices (e.g., "clean HVAC filter" on `device.hvac_unit`).

**Planned changes:**

- New config entry type or flow branch: `DeviceSelector` instead of `AreaSelector`
- New `subentry_type="device_task"` with additional `device_id` field
- Coordinator handles both area tasks and device tasks
- Sensor/button entities associated with the device in the device registry
- Device class grouping in config flow (e.g., show all HVAC devices together)

**Not designed yet — requires separate discovery session.**

---

## File Inventory

| Path | Unit | Purpose |
|---|---|---|
| `custom_components/task/__init__.py` | U1, U10 | Integration entry point |
| `custom_components/task/manifest.json` | U1 | Integration metadata |
| `custom_components/task/const.py` | U1 | Constants and configuration keys |
| `custom_components/task/strings.json` | U1 | Translatable strings |
| `custom_components/task/icons.json` | U1 | Entity icons |
| `custom_components/task/store.py` | U2 | Completion history persistence |
| `custom_components/task/config_flow.py` | U3 | Config and subentry flows |
| `custom_components/task/coordinator.py` | U4 | Data coordinator |
| `custom_components/task/sensor.py` | U5 | Sensor platform |
| `custom_components/task/button.py` | U6 | Button platform |
| `custom_components/task/todo.py` | U7 | Todo platform |
| `custom_components/task/calendar.py` | U8 | Calendar platform |
| `custom_components/task/services.py` | U9 | Service registration |
| `hacs.json` | U1 | HACS metadata |
| `tests/` | All | Test modules mirroring source structure |

## Implementation Order

```
U1 → U2 → U3 → U4 → U5 ──┐
                    ├─► U6 ──┤
                    ├─► U7 ──├─► U10
                    ├─► U8 ──┤
                    └─► U9 ──┘
```

Recommended sequence: U1 through U4 sequentially, then U5–U9 in parallel (or any order), then U10 to integrate.
