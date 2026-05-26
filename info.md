# Task — Household Task Management

Manage recurring household tasks and device maintenance schedules directly in Home Assistant. Organize by area, assign to household members with automatic rotation, and track completion history.

## Highlights

- **Recurring tasks** with configurable intervals (1–365 days)
- **Device maintenance** linked to specific HA devices (1–730 days)
- **Assignee rotation** — round-robin or random across household members
- **Overdue binary sensors** per task and per area
- **Calendar** integration showing upcoming due dates
- **Todo list** for native HA todo panel interaction
- **Completion history** with per-person statistics
- **Automation events** — `task_completed`, `task_overdue`, `maintenance_completed`, `maintenance_overdue`
- **Two Lovelace cards** with built-in visual editors:
  - `task-card` — multi-task area overview with filtering and sorting
  - `task-single-card` — single task detail view

## Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration** → search **Task**.
2. Select the area to manage.
3. Add tasks or maintenance items from the integration's config entry.

No YAML configuration needed — everything is managed through the UI.

## Lovelace Card Quick Start

```yaml
type: custom:task-card
area: kitchen
show_history: true
```

See the [full documentation](https://github.com/Kogoro/ha-task) for all card options, automation examples, and configuration details.
