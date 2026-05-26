# Task — Household Task Management for Home Assistant

[![HACS][hacs-badge]][hacs-url]
[![License][license-badge]][license-url]

A custom Home Assistant integration for managing recurring household tasks and device maintenance schedules. Organize tasks by area, assign them to household members with automatic rotation, track completion history, and get notified when tasks are overdue.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.][hacs-my-badge]][hacs-my-url]

## Features

- **Recurring tasks** — Define tasks with customizable intervals (1–365 days) and track due dates automatically.
- **Device maintenance** — Link maintenance tasks to specific devices (filter changes, cleaning, descaling) with intervals up to 730 days.
- **Assignee rotation** — Assign multiple household members and rotate responsibility using round-robin or random mode.
- **"Assign to me" button** — Any user can claim an unassigned task directly from the UI.
- **Overdue detection** — Binary sensors indicate when individual tasks or any task in an area is overdue.
- **Calendar integration** — View all task due dates on a Home Assistant calendar with recurring events.
- **Todo list** — Interact with tasks as native HA todo items; create tasks and mark them complete from the todo panel.
- **Completion history** — Persistent per-task history tracks who completed what and when, with per-person statistics.
- **Events** — Fires `task_completed`, `task_overdue`, `maintenance_completed`, and `maintenance_overdue` events for use in automations.
- **Lovelace cards** — Includes `task-card` (multi-task area view) and `task-single-card` (single task view) with a built-in visual editor.
- **Area-based organization** — Each config entry maps to a Home Assistant area; tasks and maintenance items are managed as config subentries.

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance.
2. Click **Integrations** → **⋮** (three dots) → **Custom repositories**.
3. Add `https://github.com/Kogoro/ha-task` with category **Integration**.
4. Search for "Task" in HACS and install it.
5. Restart Home Assistant.

Or click the button above to add via [My Home Assistant](https://my.home-assistant.io/).

### Manual Installation

1. Download the latest release from the [Releases](https://github.com/Kogoro/ha-task/releases) page.
2. Copy the `custom_components/task/` directory to your Home Assistant `config/custom_components/` directory.
3. Restart Home Assistant.

## Configuration

Task is configured entirely through the Home Assistant UI — no YAML needed.

### Adding an Area

1. Go to **Settings** → **Devices & Services** → **Add Integration**.
2. Search for **Task** and select it.
3. Choose the area you want to manage tasks for. Each area gets its own config entry.

### Adding Tasks

1. Navigate to the Task integration entry for an area.
2. Click **Add task** to create a recurring household task.
3. Provide:
   - **Task name** — e.g., "Vacuum living room" or "Water plants"
   - **Repeat every (days)** — interval between occurrences (1–365)
   - **Description** — optional notes or instructions
   - **Icon** — optional MDI icon
   - **Assignees** — optionally assign people with a rotation mode (round-robin or random)

### Adding Maintenance Tasks

1. Click **Add maintenance task** from the integration entry.
2. Provide:
   - **Task name** — e.g., "Replace filter" or "Descale"
   - **Device** — the device this maintenance applies to
   - **Repeat every (days)** — interval between occurrences (1–730)
   - **Description**, **Icon**, and **Assignees** — same as regular tasks

### Entities Created

For each task or maintenance item:

| Entity | Description |
|--------|-------------|
| `sensor.<name>` | Days until due (negative when overdue) |
| `binary_sensor.<name>_overdue` | `on` when the task is past due |
| `button.<name>_complete` | Press to record a completion |
| `button.<name>_assign_to_me` | Press to claim the task |

Per area:

| Entity | Description |
|--------|-------------|
| `binary_sensor.<area>_tasks_overdue` | `on` when any task in the area is overdue |
| `calendar.<area>_tasks` | Calendar with all task due dates |
| `todo.<area>_tasks` | Todo list of all tasks in the area |

### Services

| Service | Description |
|---------|-------------|
| `task.complete_task` | Mark a task as completed and advance assignee rotation |
| `task.reset_task` | Reset a task's completion history and rotation state |

## Lovelace Cards

The integration includes two custom Lovelace cards that are registered automatically.

### `task-card` — Area Task Overview

Shows all tasks for one or more areas with filtering, sorting, and completion history.

```yaml
type: custom:task-card
area: kitchen
```

#### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `area` | string or list | — | Area ID(s) to show tasks for |
| `areas` | list | — | Alternative to `area`; list of area IDs |
| `entities` | list | — | Explicit list of task sensor entity IDs |
| `title` | string | auto | Custom card title (default: area name + "Tasks") |
| `icon` | string | `mdi:home-floor-1` | Header icon |
| `show_history` | boolean | `true` | Show recent activity section |
| `default_filter` | string | `all` | Initial filter: `all`, `tasks`, or `maintenance` |
| `sort_by` | string | `due_date` | Sort order: `due_date`, `name`, or `type` |
| `show_overdue_first` | boolean | `true` | Pin overdue tasks to the top |
| `compact` | boolean | `false` | Compact mode with less detail |
| `show_device_info` | boolean | `true` | Show device name for maintenance tasks |

#### Examples

Multiple areas:

```yaml
type: custom:task-card
areas:
  - kitchen
  - bathroom
title: Household Tasks
show_history: true
sort_by: due_date
```

Compact mode with specific entities:

```yaml
type: custom:task-card
entities:
  - sensor.vacuum_living_room
  - sensor.water_plants
compact: true
show_history: false
```

### `task-single-card` — Single Task View

A focused card for a single task, useful for device dashboards or per-room views.

```yaml
type: custom:task-single-card
entity: sensor.vacuum_living_room
```

#### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `entity` | string | — | Task sensor entity ID |
| `device` | string | — | Alternative: device name or slug to auto-find sensor |
| `show_device_info` | boolean | `true` | Show device badge for maintenance tasks |

Both cards include a built-in visual editor accessible from the Lovelace card configuration UI.

## Automation Examples

Notify when a task becomes overdue:

```yaml
automation:
  - alias: "Notify overdue task"
    triggers:
      - trigger: event
        event_type: task_overdue
    actions:
      - action: notify.mobile_app
        data:
          title: "Task overdue"
          message: >
            {{ trigger.event.data.task_name }} in {{ trigger.event.data.area_name }}
            is {{ trigger.event.data.days_overdue }} days overdue.
```

## Screenshots

*Screenshots coming soon.*

## License

This project is licensed under the Apache License 2.0 — see the [LICENSE](LICENSE) file for details.

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-orange.svg
[hacs-url]: https://hacs.xyz
[license-badge]: https://img.shields.io/github/license/Kogoro/ha-task
[license-url]: https://github.com/Kogoro/ha-task/blob/main/LICENSE
[hacs-my-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[hacs-my-url]: https://my.home-assistant.io/redirect/hacs_repository/?owner=Kogoro&repository=ha-task&category=integration
