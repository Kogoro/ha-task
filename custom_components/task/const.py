"""Constants for the Task integration."""

from enum import StrEnum

DOMAIN = "task"

CONF_AREA_ID = "area_id"
CONF_ASSIGNEE = "assignee"
CONF_ASSIGNEES = "assignees"
CONF_DEVICE_ID = "device_id"
CONF_ROTATION_MODE = "rotation_mode"
CONF_INTERVAL_DAYS = "interval_days"
CONF_DESCRIPTION = "description"
CONF_ICON = "icon"

SUBENTRY_TYPE_TASK = "task"
SUBENTRY_TYPE_MAINTENANCE = "maintenance"

STORAGE_KEY = "task.history"
STORAGE_VERSION = 1


class RotationMode(StrEnum):
    """Mode for rotating through assignees."""

    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


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
SERVICE_RESET_TASK = "reset_task"
