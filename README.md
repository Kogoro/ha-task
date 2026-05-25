# ha-task

A Home Assistant custom component (HACS) for managing recurring household tasks and chores.

## Features

- **Area-based task management** — organize tasks by room/area
- **Recurring schedules** — set interval in days for each task
- **Assignees** — optionally assign tasks to HA Person entities
- **Multiple entity platforms**:
  - **Sensor** — shows days until next due (negative if overdue)
  - **Todo** — tasks appear in HA's native todo lists
  - **Calendar** — recurring events on your HA calendar
  - **Button** — one-tap task completion
- **Completion history** — persistent storage of when tasks were completed and by whom
- **Services** — `task.complete_task` and `task.reset_task` for automations

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Install "Task" from HACS
3. Restart Home Assistant

### Manual

1. Copy `custom_components/task/` to your `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "Task"
3. Select an area (e.g., "Living Room")
4. Add tasks as subentries within the config entry

### Adding Tasks

After creating an area config entry, add individual tasks:
- Click the config entry → "Add task"
- Fill in name, interval (days), optional assignee, description, and icon

## Entity Platforms

### Sensor
One sensor per task. State is the number of days until next due date (negative = overdue).

**Attributes:** `assignee`, `interval_days`, `last_completed`, `next_due`, `overdue`, `area_id`

### Todo
One todo list per area. Tasks appear as items — `NEEDS_ACTION` when due/overdue, `COMPLETED` otherwise.

### Calendar
One calendar per area. Tasks appear as recurring all-day events based on their interval.

### Button
One button per task. Press to mark the task as completed.

## Services

### `task.complete_task`
Mark a task as complete. Records the completion timestamp.

| Field | Description |
|-------|-------------|
| `entity_id` | The task sensor or button entity |

### `task.reset_task`
Reset a task's completion history.

| Field | Description |
|-------|-------------|
| `entity_id` | The task sensor or button entity |

## Data Model

- **Config Entry** = an area (links to HA area registry)
- **Config Subentry** = an individual task (name, interval, assignee, etc.)
- **Storage** = completion history (persisted to `.storage/task.history`)

## Requirements

- Home Assistant 2025.12+
- HACS (for automatic installation)
