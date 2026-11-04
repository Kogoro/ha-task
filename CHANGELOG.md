# Changelog

## Unreleased

### Added
- **Reminders** without an automation: set notify entities and/or a notify service, whether to remind when due soon and/or overdue, and the time of day on an area; a task can opt out. Once per due date and kind (also across restarts), a summary when many are pending, never for tasks that were never completed.
- **Month and week intervals** (in addition to days) and **active months** for seasonal tasks: outside the season a task is neither due nor overdue, is not counted and has no calendar events, and it returns at the start of the next active month. New attributes `interval_value`, `interval_unit`, `active_months`, `in_season`; the cards show "out of season". Existing tasks are unchanged (their interval is still stored in days).
- **Effort (points)** per task and a new rotation mode, **least workload**: the person with the fewest completed points over the last 30 days gets the task; who is next is fixed when the task is completed. `task-ranking-card` counts points (option `use_points`, on by default; the same as before while no task has points). The completion event and `task.get_history` include `points`.
- **Away:** `task.set_away` / `task.clear_away` mark a person as away, optionally with a start and end date. The rotation (round-robin and random) skips them, hands their task on at once and continues after the person who took it; they return automatically after the end date. New attribute `away_assignees` on the task sensor.
- **Undo** the most recently recorded completion: `task.undo_completion` and an undo button on that entry in the card's history. It restores who was responsible, the rotation and a postponement. New event `task_completion_undone`.
- **History and statistics:** `task.get_history` returns the history with the days between completions; the task sensor shows `average_cycle_days`, `last_cycle_days` and `on_time_percent`.

## 0.4.0-beta.2 (pre-release)

### Added
- **Household overview:** an optional config entry with totals across all areas (overdue, due today, due this week, due soon) and the unified calendar with the tasks of all areas.

### Changed
- The unified calendar belongs to the household overview instead of the first area that used it, so it no longer disappears when that area is unloaded. Adding the integration now starts with a choice between "Area" and "Household overview". "Use unified calendar" on an area is now "Hide this area's separate calendar" and is offered once a household overview exists.
- Upgrading: if an area used the unified calendar, the household overview is created automatically and keeps the calendar's name and entity ID.

## 0.4.0-beta.1 (pre-release)

### Added
- `task.complete_task` accepts `completed_at` to record a past completion.
- `task.postpone_task` and a postpone button on `task-card` and `task-single-card`.
- Warn days per area, optionally overridden per task, and a status sensor (`ok`, `due_soon`, `overdue`) per task.
- Per-area summary sensors: overdue, due today, due this week, due soon.
- `task_due_soon` / `maintenance_due_soon` events.
- Automated tests and a CI job.
- English and German README with screenshots.

### Fixed
- State updates immediately after a service call or button press instead of up to 10 seconds later.
- Transparent icon, landscape logo and dark logo.

## 0.3.1

- Overdue status refreshes every 15 minutes; "Assign to me" uses the pressing user; action editor offers task entities; documentation link in the card picker.
- Home Assistant 2026.8: each maintenance item gets its own "Device Maintenance" device, linked to the appliance.

## 0.3.0

- Custom calendar name and unified calendar mode, task descriptions in the cards, automation blueprints.

## 0.2.1

- User filtering on the task card; fixes for stale devices and the reconfigure message.

## 0.2.0

- Filter tabs, sorting, compact mode, activity and ranking cards, catalog import with 80 tasks.

## 0.1.0

- Initial release.
