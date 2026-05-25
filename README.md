# Task — Recurring Household Tasks for Home Assistant

A HACS custom integration that manages recurring household tasks and chores with area-based organization, optional assignees, and completion tracking.

## Features

- **Area-based organization** — group tasks by Home Assistant area (kitchen, bathroom, etc.)
- **Recurring schedules** — define interval in days for each task
- **Completion tracking** — record who completed a task and when
- **Multiple entity platforms:**
  - **Sensor** — days until each task is due (negative when overdue)
  - **Button** — one-tap completion
  - **Todo list** — all tasks for an area as a checklist
  - **Calendar** — recurring events for task scheduling

## Installation

### HACS

1. Open HACS in Home Assistant
2. Add this repository as a custom repository (Integration type)
3. Search for "Task" and install
4. Restart Home Assistant

### Manual

Copy the `custom_components/task` folder to your Home Assistant `config/custom_components/` directory and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Task**
3. Select an area to manage tasks for
4. Add individual tasks via the **Configure** button on the integration entry

Each task has:

| Field | Required | Description |
|---|---|---|
| Name | Yes | Name of the task |
| Interval (days) | Yes | How often the task should be done |
| Assignee | No | Person entity responsible |
| Description | No | Additional details |
| Icon | No | MDI icon override |

## Services

| Service | Description |
|---|---|
| `task.complete_task` | Mark a task as completed |
| `task.reset_task` | Reset completion history for a task |

## Entity Platforms

### Sensor

One sensor per task. State is the number of days until due (negative if overdue).

**Attributes:** `assignee`, `interval_days`, `last_completed`, `next_due`, `area_id`, `overdue`

### Button

One button per task. Press to mark the task as complete.

### Todo

One todo list per area. Tasks appear as items with status reflecting due/overdue state.

### Calendar

One calendar per area. Tasks appear as recurring all-day events based on their interval.

## License

MIT
