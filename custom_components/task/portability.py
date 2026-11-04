"""Export and import of the task configuration (a backup, or a move to another instance)."""

from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from homeassistant.util import yaml as yaml_util

from .const import (
    CONF_ACTIVE_MONTHS,
    CONF_AREA_ID,
    CONF_ASSIGNEE,
    CONF_ASSIGNEES,
    CONF_CALENDAR_NAME,
    CONF_DESCRIPTION,
    CONF_DEVICE_ID,
    CONF_ICON,
    CONF_INTERVAL_DAYS,
    CONF_INTERVAL_UNIT,
    CONF_INTERVAL_VALUE,
    CONF_POINTS,
    CONF_REMINDER_DUE_SOON,
    CONF_REMINDER_OVERDUE,
    CONF_REMINDER_SERVICE,
    CONF_REMINDER_TARGETS,
    CONF_REMINDER_TIME,
    CONF_REMINDERS,
    CONF_ROTATION_MODE,
    CONF_UNIFIED_CALENDAR,
    CONF_WARN_DAYS,
    DEFAULT_POINTS,
    DOMAIN,
    SUBENTRY_TYPE_MAINTENANCE,
    SUBENTRY_TYPE_TASK,
    RotationMode,
)
from .household import household_entry, is_household
from .schedule import INTERVAL_UNITS, nominal_days
from .store import CompletionEntry

_LOGGER = logging.getLogger(__name__)

EXPORT_VERSION = 1
MAX_REPORTED_ERRORS = 15

# Area entry settings that are exported and imported.
SETTING_KEYS = (
    CONF_CALENDAR_NAME,
    CONF_UNIFIED_CALENDAR,
    CONF_WARN_DAYS,
    CONF_REMINDER_TARGETS,
    CONF_REMINDER_SERVICE,
    CONF_REMINDER_DUE_SOON,
    CONF_REMINDER_OVERDUE,
    CONF_REMINDER_TIME,
)

_SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CALENDAR_NAME): str,
        vol.Optional(CONF_UNIFIED_CALENDAR): cv.boolean,
        vol.Optional(CONF_WARN_DAYS): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
        vol.Optional(CONF_REMINDER_TARGETS): [cv.entity_domain("notify")],
        vol.Optional(CONF_REMINDER_SERVICE): vol.Match(r"^notify\.[a-z0-9_]+$"),
        vol.Optional(CONF_REMINDER_DUE_SOON): cv.boolean,
        vol.Optional(CONF_REMINDER_OVERDUE): cv.boolean,
        vol.Optional(CONF_REMINDER_TIME): vol.Match(r"^\d{2}:\d{2}(:\d{2})?$"),
    }
)

def _datetime(value: Any) -> datetime.datetime:
    """Parse a date and time, rejecting anything that is not one."""
    parsed = dt_util.parse_datetime(str(value))
    if parsed is None:
        raise vol.Invalid("not a valid date and time")
    return parsed


_COMPLETION_SCHEMA = vol.Schema(
    {
        vol.Required("completed_at"): _datetime,
        vol.Optional("completed_by"): vol.Any(None, cv.entity_domain("person")),
        vol.Optional("points", default=DEFAULT_POINTS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
    }
)

_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=120)),
        vol.Optional("type", default=SUBENTRY_TYPE_TASK): vol.In(
            [SUBENTRY_TYPE_TASK, SUBENTRY_TYPE_MAINTENANCE]
        ),
        vol.Optional("interval_value", default=7): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=730)
        ),
        vol.Optional("interval_unit", default="days"): vol.In(list(INTERVAL_UNITS)),
        vol.Optional("active_months", default=list): [
            vol.All(vol.Coerce(int), vol.Range(min=1, max=12))
        ],
        vol.Optional("points", default=DEFAULT_POINTS): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional("description"): vol.Any(None, str),
        vol.Optional("icon"): vol.Any(None, str),
        vol.Optional("assignees", default=list): [cv.entity_domain("person")],
        vol.Optional("rotation_mode", default=RotationMode.ROUND_ROBIN): vol.In(
            [mode.value for mode in RotationMode]
        ),
        vol.Optional("warn_days"): vol.Any(
            None, vol.All(vol.Coerce(int), vol.Range(min=0, max=365))
        ),
        vol.Optional("reminders", default=True): cv.boolean,
        vol.Optional("device_id"): vol.Any(None, str),
        vol.Optional("device_name"): vol.Any(None, str),
        vol.Optional("completions"): [_COMPLETION_SCHEMA],
    }
)

_AREA_SCHEMA = vol.Schema(
    {
        vol.Optional("area_id"): str,
        vol.Optional("area_name"): str,
        vol.Optional("settings", default=dict): _SETTINGS_SCHEMA,
        vol.Optional("tasks", default=list): [_TASK_SCHEMA],
    }
)

_ROOT_SCHEMA = vol.Schema(
    {
        vol.Required("version"): vol.In([EXPORT_VERSION]),
        vol.Optional("exported_at"): str,
        vol.Optional("household"): vol.Schema({vol.Optional(CONF_CALENDAR_NAME): str}),
        vol.Optional("areas", default=list): [_AREA_SCHEMA],
    }
)


# --- export ----------------------------------------------------------------


def _export_task(
    hass: HomeAssistant, entry: ConfigEntry, subentry: ConfigSubentry, include_history: bool
) -> dict[str, Any]:
    """Return one task or maintenance item as it is exported."""
    data = subentry.data
    assignees = list(data.get(CONF_ASSIGNEES) or [])
    if not assignees and data.get(CONF_ASSIGNEE):
        assignees = [data[CONF_ASSIGNEE]]
    task: dict[str, Any] = {
        "name": subentry.title,
        "type": subentry.subentry_type,
        "interval_value": int(
            data.get(CONF_INTERVAL_VALUE) or data.get(CONF_INTERVAL_DAYS) or 7
        ),
        "interval_unit": data.get(CONF_INTERVAL_UNIT) or "days",
        "points": int(data.get(CONF_POINTS) or DEFAULT_POINTS),
        "assignees": assignees,
        "rotation_mode": data.get(CONF_ROTATION_MODE) or RotationMode.ROUND_ROBIN.value,
        "reminders": bool(data.get(CONF_REMINDERS, True)),
    }
    if months := data.get(CONF_ACTIVE_MONTHS):
        task["active_months"] = sorted(int(m) for m in months)
    if data.get(CONF_DESCRIPTION):
        task["description"] = data[CONF_DESCRIPTION]
    if data.get(CONF_ICON):
        task["icon"] = data[CONF_ICON]
    if data.get(CONF_WARN_DAYS) is not None:
        task["warn_days"] = int(data[CONF_WARN_DAYS])
    if device_id := data.get(CONF_DEVICE_ID):
        task["device_id"] = device_id
        if device := dr.async_get(hass).async_get(device_id):
            task["device_name"] = device.name_by_user or device.name
    if include_history:
        history = hass.data[DOMAIN]["store"].get_history(subentry.subentry_id)
        task["completions"] = [
            {
                "completed_at": completion.completed_at.isoformat(),
                "completed_by": completion.completed_by,
                "points": completion.points,
            }
            for completion in history.completions
        ]
    return task


async def async_export(hass: HomeAssistant, include_history: bool = False) -> dict[str, Any]:
    """Return all areas, tasks and maintenance items (and optionally their history)."""
    area_reg = ar.async_get(hass)
    result: dict[str, Any] = {
        "version": EXPORT_VERSION,
        "exported_at": dt_util.utcnow().isoformat(),
        "areas": [],
    }
    for entry in hass.config_entries.async_entries(DOMAIN):
        if is_household(entry):
            result["household"] = {
                key: entry.data[key] for key in (CONF_CALENDAR_NAME,) if key in entry.data
            }
            continue
        area_id = entry.data[CONF_AREA_ID]
        area = area_reg.async_get_area(area_id)
        result["areas"].append(
            {
                "area_id": area_id,
                "area_name": area.name if area else area_id,
                "settings": {k: entry.data[k] for k in SETTING_KEYS if k in entry.data},
                "tasks": [
                    _export_task(hass, entry, subentry, include_history)
                    for subentry in entry.subentries.values()
                    if subentry.subentry_type in (SUBENTRY_TYPE_TASK, SUBENTRY_TYPE_MAINTENANCE)
                ],
            }
        )
    return result


# --- files -----------------------------------------------------------------


EXPORT_DIR = "task_exports"


def _checked_path(hass: HomeAssistant, filename: str, create: bool = False) -> Path:
    """Return the path of an export file inside the ``task_exports`` folder.

    Only a plain file name ending in .json, .yaml or .yml is accepted, never a
    folder, so a service call can not reach other files such as the
    configuration.
    """
    if (
        not filename
        or filename != Path(filename).name
        or filename.startswith(".")
        or Path(filename).suffix.lower() not in (".json", ".yaml", ".yml")
    ):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="bad_filename"
        )
    directory = Path(hass.config.path(EXPORT_DIR))
    if create:
        directory.mkdir(exist_ok=True)
    return directory / filename


def write_export_file(hass: HomeAssistant, filename: str, data: dict[str, Any]) -> str:
    """Write an export as JSON or YAML (by extension); blocking."""
    path = _checked_path(hass, filename, create=True)
    if path.suffix.lower() == ".json":
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        text = yaml_util.dump(data)
    path.write_text(text, encoding="utf-8")
    return str(path)


def read_export_file(hass: HomeAssistant, filename: str) -> Any:
    """Read an export from a JSON or YAML file (by extension); blocking."""
    path = _checked_path(hass, filename)
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            return json.loads(text)
        return yaml_util.parse_yaml(text)
    except (OSError, ValueError, HomeAssistantError) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="cannot_read_file",
            translation_placeholders={"error": str(err)},
        ) from err


# --- import ----------------------------------------------------------------


def _format_errors(err: vol.Invalid) -> list[str]:
    """Turn voluptuous errors into readable "path: message" lines."""
    errors = err.errors if isinstance(err, vol.MultipleInvalid) else [err]
    lines = []
    for error in errors:
        path = ""
        for part in error.path:
            path += f"[{part}]" if isinstance(part, int) else f".{part}" if path else str(part)
        lines.append(f"{path or 'file'}: {error.msg}")
    return lines


def _area_id_for(hass: HomeAssistant, area: dict[str, Any]) -> str | None:
    """Find the Home Assistant area an exported area belongs to (by ID, else by name)."""
    area_reg = ar.async_get(hass)
    if (area_id := area.get("area_id")) and area_reg.async_get_area(area_id):
        return area_id
    if name := area.get("area_name"):
        for candidate in area_reg.async_list_areas():
            if candidate.name.casefold() == name.casefold():
                return candidate.id
    return None


def _device_id_for(hass: HomeAssistant, task: dict[str, Any]) -> str | None:
    """Find the device of a maintenance item (by ID, else by name)."""
    dev_reg = dr.async_get(hass)
    if (device_id := task.get("device_id")) and dev_reg.async_get(device_id):
        return device_id
    if name := task.get("device_name"):
        for device in dev_reg.devices.values():
            if (device.name_by_user or device.name or "").casefold() == name.casefold():
                return device.id
    return None


def _area_entry(hass: HomeAssistant, area_id: str) -> ConfigEntry | None:
    """Return the area entry for a Home Assistant area."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if not is_household(entry) and entry.data.get(CONF_AREA_ID) == area_id:
            return entry
    return None


def _plan(hass: HomeAssistant, raw: Any) -> tuple[dict[str, Any], list[str]]:
    """Validate an export and work out what an import would do.

    Returns the plan and a list of problems; with any problem nothing may be
    applied.
    """
    try:
        data = _ROOT_SCHEMA(raw)
    except vol.Invalid as err:
        return {}, _format_errors(err)

    errors: list[str] = []
    areas: list[dict[str, Any]] = []
    skipped: list[str] = []

    for index, area in enumerate(data["areas"]):
        label = area.get("area_name") or area.get("area_id") or f"areas[{index}]"
        if not area.get("area_id") and not area.get("area_name"):
            errors.append(f"areas[{index}]: needs an area_id or an area_name")
            continue
        area_id = _area_id_for(hass, area)
        if area_id is not None:
            found = ar.async_get(hass).async_get_area(area_id)
            label = found.name if found else label
        if area_id is None:
            errors.append(
                f"areas[{index}]: the area '{label}' does not exist; create it under "
                "Settings > Areas first"
            )
            continue

        entry = _area_entry(hass, area_id)
        known = (
            {(s.subentry_type, s.title.casefold()) for s in entry.subentries.values()}
            if entry
            else set()
        )
        new_tasks: list[dict[str, Any]] = []
        for task_index, task in enumerate(area["tasks"]):
            where = f"areas[{index}].tasks[{task_index}]"
            key = (task["type"], task["name"].casefold())
            if key in known:
                skipped.append(f"{label}: {task['name']}")
                continue
            known.add(key)
            if task["type"] == SUBENTRY_TYPE_MAINTENANCE:
                device_id = _device_id_for(hass, task)
                if device_id is None:
                    errors.append(
                        f"{where}: the device of '{task['name']}' was not found "
                        "(by device_id or device_name)"
                    )
                    continue
                task = {**task, "device_id": device_id}
            new_tasks.append(task)
        areas.append(
            {
                "area_id": area_id,
                "label": label,
                "entry": entry,
                "settings": area["settings"],
                "tasks": new_tasks,
            }
        )

    plan = {
        "household": data.get("household"),
        "areas": areas,
        "skipped": skipped,
    }
    return plan, errors


def _subentry_data(task: dict[str, Any]) -> dict[str, Any]:
    """Return the config subentry data for an imported task."""
    value, unit = task["interval_value"], task["interval_unit"]
    data: dict[str, Any] = {
        CONF_INTERVAL_VALUE: value,
        CONF_INTERVAL_UNIT: unit,
        CONF_INTERVAL_DAYS: nominal_days(value, unit),
        CONF_POINTS: task["points"],
        CONF_ASSIGNEES: list(task["assignees"]),
        CONF_ROTATION_MODE: task["rotation_mode"],
        CONF_REMINDERS: task["reminders"],
        CONF_DESCRIPTION: task.get("description"),
        CONF_ICON: task.get("icon"),
    }
    if task["active_months"]:
        data[CONF_ACTIVE_MONTHS] = sorted(task["active_months"])
    if task.get("warn_days") is not None:
        data[CONF_WARN_DAYS] = task["warn_days"]
    if task["type"] == SUBENTRY_TYPE_MAINTENANCE:
        data[CONF_DEVICE_ID] = task["device_id"]
    return data


async def async_import(
    hass: HomeAssistant, raw: Any, dry_run: bool = False
) -> dict[str, Any]:
    """Import an export; everything is validated first and nothing is changed on errors.

    Tasks that already exist in an area (same type and name) are skipped. Areas
    must exist in Home Assistant; the area entry is created if it is missing.
    Settings of an existing area entry are left as they are.
    """
    plan, errors = _plan(hass, raw)
    if errors:
        shown = errors[:MAX_REPORTED_ERRORS]
        if len(errors) > len(shown):
            shown.append(f"... and {len(errors) - len(shown)} more")
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="import_invalid",
            translation_placeholders={"errors": "\n".join(shown)},
        )

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "household_created": False,
        "areas_created": [],
        "tasks_created": 0,
        "tasks_skipped": plan["skipped"],
    }

    create_household = plan["household"] is not None and household_entry(hass) is None
    result["household_created"] = create_household
    for area in plan["areas"]:
        if area["entry"] is None:
            result["areas_created"].append(area["label"])
        result["tasks_created"] += len(area["tasks"])
    if dry_run:
        return result

    store = hass.data[DOMAIN]["store"]
    if create_household:
        await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=dict(plan["household"] or {})
        )

    for area in plan["areas"]:
        entry = area["entry"]
        if entry is None:
            await hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={CONF_AREA_ID: area["area_id"], **area["settings"]},
            )
            entry = _area_entry(hass, area["area_id"])
        if entry is None:
            _LOGGER.warning("Could not create the entry for area %s", area["label"])
            result["tasks_created"] -= len(area["tasks"])
            continue

        for task in area["tasks"]:
            subentry = ConfigSubentry(
                data=_subentry_data(task),
                subentry_type=task["type"],
                title=task["name"],
                unique_id=None,
            )
            hass.config_entries.async_add_subentry(entry, subentry)
            if completions := task.get("completions"):
                store.import_completions(
                    subentry.subentry_id,
                    [
                        CompletionEntry(
                            completed_at=dt_util.as_utc(c["completed_at"]),
                            completed_by=c.get("completed_by"),
                            points=c["points"],
                        )
                        for c in completions
                    ],
                )
    return result
