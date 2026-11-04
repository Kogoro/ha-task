"""Constants for the Task integration."""

from enum import StrEnum

DOMAIN = "task"

CONF_AREA_ID = "area_id"
CONF_ASSIGNEE = "assignee"
CONF_ASSIGNEES = "assignees"
CONF_CALENDAR_NAME = "calendar_name"
CONF_DEVICE_ID = "device_id"
CONF_ROTATION_MODE = "rotation_mode"
CONF_INTERVAL_DAYS = "interval_days"
CONF_DESCRIPTION = "description"
CONF_ICON = "icon"
CONF_UNIFIED_CALENDAR = "unified_calendar"
CONF_WARN_DAYS = "warn_days"
CONF_ENTRY_TYPE = "entry_type"

ENTRY_TYPE_AREA = "area"
ENTRY_TYPE_HOUSEHOLD = "household"
HOUSEHOLD_UNIQUE_ID = "household"
DEFAULT_HOUSEHOLD_CALENDAR_NAME = "All Tasks"
UNIFIED_CALENDAR_UNIQUE_ID = f"{DOMAIN}_unified_calendar"

SIGNAL_AREAS_CHANGED = f"{DOMAIN}_areas_changed"

DEFAULT_WARN_DAYS = 7

SUBENTRY_TYPE_TASK = "task"
SUBENTRY_TYPE_MAINTENANCE = "maintenance"
SUBENTRY_TYPE_IMPORT = "import"

STORAGE_KEY = "task.history"
STORAGE_VERSION = 1


class RotationMode(StrEnum):
    """Mode for rotating through assignees."""

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


class TaskStatus(StrEnum):
    """Status of a task or maintenance item."""

    OK = "ok"
    DUE_SOON = "due_soon"
    OVERDUE = "overdue"


ATTR_ASSIGNEE = "assignee"
ATTR_ASSIGNEES = "assignees"
ATTR_CURRENT_ASSIGNEE = "current_assignee"
ATTR_LAST_COMPLETED_BY = "last_completed_by"
ATTR_ROTATION_MODE = "rotation_mode"
ATTR_INTERVAL_DAYS = "interval_days"
ATTR_LAST_COMPLETED = "last_completed"
ATTR_NEXT_DUE = "next_due"
ATTR_OVERDUE = "overdue"
ATTR_AREA_ID = "area_id"

SERVICE_COMPLETE_TASK = "complete_task"
SERVICE_POSTPONE_TASK = "postpone_task"
SERVICE_UNDO_COMPLETION = "undo_completion"
SERVICE_GET_HISTORY = "get_history"
SERVICE_RESET_TASK = "reset_task"
