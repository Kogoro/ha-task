"""Constants for the Task integration."""

DOMAIN = "task"

CONF_AREA_ID = "area_id"
CONF_ASSIGNEE = "assignee"
CONF_INTERVAL_DAYS = "interval_days"
CONF_DESCRIPTION = "description"
CONF_ICON = "icon"

SUBENTRY_TYPE_TASK = "task"

STORAGE_KEY = "task.history"
STORAGE_VERSION = 1

ATTR_ASSIGNEE = "assignee"
ATTR_INTERVAL_DAYS = "interval_days"
ATTR_LAST_COMPLETED = "last_completed"
ATTR_NEXT_DUE = "next_due"
ATTR_OVERDUE = "overdue"
ATTR_AREA_ID = "area_id"

SERVICE_COMPLETE_TASK = "complete_task"
SERVICE_RESET_TASK = "reset_task"
