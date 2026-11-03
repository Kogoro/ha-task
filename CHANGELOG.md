# Changelog

## Unreleased

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
