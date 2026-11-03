"""Config flow for the Task integration."""

import re
from contextlib import suppress
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    AreaSelector,
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    TimeSelector,
)

from .const import (
    CONF_ACTIVE_MONTHS,
    CONF_AREA_ID,
    CONF_ASSIGNEE,
    CONF_ASSIGNEES,
    CONF_CALENDAR_NAME,
    CONF_DESCRIPTION,
    CONF_DEVICE_ID,
    CONF_ENTRY_TYPE,
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
    DEFAULT_HOUSEHOLD_CALENDAR_NAME,
    DEFAULT_POINTS,
    DEFAULT_REMINDER_TIME,
    DEFAULT_WARN_DAYS,
    DOMAIN,
    ENTRY_TYPE_HOUSEHOLD,
    HOUSEHOLD_UNIQUE_ID,
    SUBENTRY_TYPE_IMPORT,
    SUBENTRY_TYPE_MAINTENANCE,
    SUBENTRY_TYPE_TASK,
    RotationMode,
)
from .household import household_entry, is_household
from .schedule import INTERVAL_UNITS, nominal_days


class TaskConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Task."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler (none for the household)."""
        if is_household(config_entry):
            return {}
        return {
            SUBENTRY_TYPE_TASK: TaskSubentryFlow,
            SUBENTRY_TYPE_MAINTENANCE: MaintenanceSubentryFlow,
            SUBENTRY_TYPE_IMPORT: ImportSubentryFlow,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer an area or the household; only an area once a household exists."""
        if household_entry(self.hass) is None:
            return self.async_show_menu(
                step_id="user", menu_options=["area", "household"]
            )
        return await self.async_step_area()

    async def async_step_household(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set up the household entry: totals and the unified calendar."""
        await self.async_set_unique_id(HOUSEHOLD_UNIQUE_ID)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title="Household", data=_household_data(user_input)
            )

        return self.async_show_form(
            step_id="household",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CALENDAR_NAME, default=DEFAULT_HOUSEHOLD_CALENDAR_NAME
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                }
            ),
        )

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Create the household entry (upgrade) or an area entry (config import)."""
        if area_id := import_data.get(CONF_AREA_ID):
            await self.async_set_unique_id(area_id)
            self._abort_if_unique_id_configured()
            area_entry = ar.async_get(self.hass).async_get_area(area_id)
            return self.async_create_entry(
                title=area_entry.name if area_entry else area_id,
                data=dict(import_data),
            )
        await self.async_set_unique_id(HOUSEHOLD_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Household", data=_household_data(import_data))

    async def async_step_area(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the step to select an area."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_AREA_ID):
                errors[CONF_AREA_ID] = "area_required"
            errors.update(_reminder_errors(user_input))

            if not errors:
                area_id = user_input[CONF_AREA_ID]
                area_reg = ar.async_get(self.hass)
                area_entry = area_reg.async_get_area(area_id)
                title = area_entry.name if area_entry else area_id

                await self.async_set_unique_id(area_id)
                self._abort_if_unique_id_configured()

                data: dict[str, Any] = {CONF_AREA_ID: area_id}
                calendar_name = user_input.get(CONF_CALENDAR_NAME)
                if calendar_name and calendar_name.strip():
                    data[CONF_CALENDAR_NAME] = calendar_name.strip()
                data[CONF_UNIFIED_CALENDAR] = bool(
                    user_input.get(CONF_UNIFIED_CALENDAR, False)
                )
                data[CONF_WARN_DAYS] = int(
                    user_input.get(CONF_WARN_DAYS, DEFAULT_WARN_DAYS)
                )
                data.update(_reminder_data(user_input))

                return self.async_create_entry(
                    title=title,
                    data=data,
                )

        schema: dict[Any, Any] = {
            vol.Required(CONF_AREA_ID): AreaSelector(),
            vol.Optional(CONF_CALENDAR_NAME): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
        }
        if household_entry(self.hass) is not None:
            schema[vol.Optional(CONF_UNIFIED_CALENDAR, default=False)] = BooleanSelector()
        schema[vol.Optional(CONF_WARN_DAYS, default=DEFAULT_WARN_DAYS)] = (
            _warn_days_selector()
        )
        _add_reminder_fields(schema, user_input or {})
        return self.async_show_form(
            step_id="area", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an area, or of the household."""
        if is_household(self._get_reconfigure_entry()):
            return await self.async_step_reconfigure_household(user_input)

        errors: dict[str, str] = {}
        if user_input is not None:
            errors.update(_reminder_errors(user_input))

        if user_input is not None and not errors:
            area_id = user_input[CONF_AREA_ID]
            area_reg = ar.async_get(self.hass)
            area_entry = area_reg.async_get_area(area_id)
            title = area_entry.name if area_entry else area_id

            data: dict[str, Any] = {CONF_AREA_ID: area_id}
            calendar_name = user_input.get(CONF_CALENDAR_NAME)
            if calendar_name and calendar_name.strip():
                data[CONF_CALENDAR_NAME] = calendar_name.strip()
            # Without a household entry the option is hidden, so keep what is set.
            data[CONF_UNIFIED_CALENDAR] = bool(
                user_input.get(
                    CONF_UNIFIED_CALENDAR,
                    self._get_reconfigure_entry().data.get(CONF_UNIFIED_CALENDAR, False),
                )
            )
            data[CONF_WARN_DAYS] = int(
                user_input.get(CONF_WARN_DAYS, DEFAULT_WARN_DAYS)
            )
            data.update(_reminder_data(user_input))

            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                title=title,
                data=data,
            )

        entry = self._get_reconfigure_entry()
        cal_name_default = entry.data.get(CONF_CALENDAR_NAME)
        cal_name_schema = (
            vol.Optional(CONF_CALENDAR_NAME, default=cal_name_default)
            if cal_name_default
            else vol.Optional(CONF_CALENDAR_NAME)
        )
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_AREA_ID, default=entry.data.get(CONF_AREA_ID)
            ): AreaSelector(),
            cal_name_schema: TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
        }
        if household_entry(self.hass) is not None:
            schema[
                vol.Optional(
                    CONF_UNIFIED_CALENDAR,
                    default=entry.data.get(CONF_UNIFIED_CALENDAR, False),
                )
            ] = BooleanSelector()
        schema[
            vol.Optional(
                CONF_WARN_DAYS,
                default=entry.data.get(CONF_WARN_DAYS, DEFAULT_WARN_DAYS),
            )
        ] = _warn_days_selector()
        _add_reminder_fields(schema, user_input or dict(entry.data))
        return self.async_show_form(
            step_id="reconfigure", data_schema=vol.Schema(schema), errors=errors
        )

    async def async_step_reconfigure_household(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure the household entry (the unified calendar's name)."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry, data=_household_data(user_input)
            )
        return self.async_show_form(
            step_id="reconfigure_household",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_CALENDAR_NAME,
                        default=entry.data.get(
                            CONF_CALENDAR_NAME, DEFAULT_HOUSEHOLD_CALENDAR_NAME
                        ),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                }
            ),
        )


def _household_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return the data of a household entry."""
    data: dict[str, Any] = {CONF_ENTRY_TYPE: ENTRY_TYPE_HOUSEHOLD}
    name = (user_input.get(CONF_CALENDAR_NAME) or "").strip()
    if name:
        data[CONF_CALENDAR_NAME] = name
    return data


def _warn_days_selector() -> NumberSelector:
    """Return the selector for a warning window in days."""
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=365,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="days",
        )
    )


def _add_warn_days(schema: dict, defaults: dict[str, Any]) -> None:
    """Add the optional per-item warning window that overrides the area value.

    A suggested value is used instead of a default so the field can be cleared
    to fall back to the area value again.
    """
    warn_days = defaults.get(CONF_WARN_DAYS)
    schema[
        vol.Optional(
            CONF_WARN_DAYS,
            description=(
                {"suggested_value": warn_days} if warn_days is not None else None
            ),
        )
    ] = _warn_days_selector()


def _add_reminder_fields(schema: dict, defaults: dict[str, Any]) -> None:
    """Add where and when reminders are sent for an area.

    Suggested values (not defaults) are used for the targets so they can be
    emptied again to turn reminders off.
    """
    targets = defaults.get(CONF_REMINDER_TARGETS) or []
    schema[
        vol.Optional(
            CONF_REMINDER_TARGETS,
            description={"suggested_value": targets} if targets else None,
        )
    ] = EntitySelector(EntitySelectorConfig(domain="notify", multiple=True))
    service = defaults.get(CONF_REMINDER_SERVICE)
    schema[
        vol.Optional(
            CONF_REMINDER_SERVICE,
            description={"suggested_value": service} if service else None,
        )
    ] = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
    schema[
        vol.Optional(
            CONF_REMINDER_DUE_SOON, default=defaults.get(CONF_REMINDER_DUE_SOON, True)
        )
    ] = BooleanSelector()
    schema[
        vol.Optional(
            CONF_REMINDER_OVERDUE, default=defaults.get(CONF_REMINDER_OVERDUE, True)
        )
    ] = BooleanSelector()
    schema[
        vol.Optional(
            CONF_REMINDER_TIME,
            default=defaults.get(CONF_REMINDER_TIME, DEFAULT_REMINDER_TIME),
        )
    ] = TimeSelector()


def _reminder_errors(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate the reminder fields."""
    service = (user_input.get(CONF_REMINDER_SERVICE) or "").strip()
    if service and not re.fullmatch(r"notify\.[a-z0-9_]+", service):
        return {CONF_REMINDER_SERVICE: "invalid_notify_service"}
    return {}


def _reminder_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Return the reminder settings for the area entry."""
    data: dict[str, Any] = {
        CONF_REMINDER_DUE_SOON: bool(user_input.get(CONF_REMINDER_DUE_SOON, True)),
        CONF_REMINDER_OVERDUE: bool(user_input.get(CONF_REMINDER_OVERDUE, True)),
        CONF_REMINDER_TIME: str(user_input.get(CONF_REMINDER_TIME) or DEFAULT_REMINDER_TIME),
    }
    if targets := user_input.get(CONF_REMINDER_TARGETS):
        data[CONF_REMINDER_TARGETS] = list(targets)
    if service := (user_input.get(CONF_REMINDER_SERVICE) or "").strip():
        data[CONF_REMINDER_SERVICE] = service
    return data


def _interval_unit_selector() -> SelectSelector:
    """Return the selector for the unit of an interval."""
    return SelectSelector(
        SelectSelectorConfig(
            options=list(INTERVAL_UNITS),
            translation_key="interval_unit",
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _add_active_months(schema: dict, defaults: dict[str, Any]) -> None:
    """Add the optional months in which the task is active.

    A suggested value is used so the field can be emptied to mean "all year".
    """
    months = [str(m) for m in defaults.get(CONF_ACTIVE_MONTHS) or []]
    schema[
        vol.Optional(
            CONF_ACTIVE_MONTHS,
            description={"suggested_value": months} if months else None,
        )
    ] = SelectSelector(
        SelectSelectorConfig(
            options=[str(m) for m in range(1, 13)],
            multiple=True,
            translation_key="month",
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def _interval_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return the interval and active months for the subentry data.

    ``interval_days`` stays as the interval in days (months count as 30.44 days)
    so everything that only knows days keeps working.
    """
    unit = data.get(CONF_INTERVAL_UNIT) or "days"
    value = int(data.get(CONF_INTERVAL_VALUE) or data.get(CONF_INTERVAL_DAYS) or 7)
    result: dict[str, Any] = {
        CONF_INTERVAL_VALUE: value,
        CONF_INTERVAL_UNIT: unit,
        CONF_INTERVAL_DAYS: nominal_days(value, unit),
    }
    months = sorted(int(m) for m in data.get(CONF_ACTIVE_MONTHS) or [])
    if months:
        result[CONF_ACTIVE_MONTHS] = months
    return result


def _add_points(schema: dict, defaults: dict[str, Any]) -> None:
    """Add the effort of a task in points (used by the ranking and the workload rotation)."""
    schema[
        vol.Optional(CONF_POINTS, default=defaults.get(CONF_POINTS, DEFAULT_POINTS))
    ] = NumberSelector(
        NumberSelectorConfig(min=1, max=100, step=1, mode=NumberSelectorMode.BOX)
    )


def _points_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return the effort for the subentry data."""
    return {CONF_POINTS: int(data.get(CONF_POINTS) or DEFAULT_POINTS)}


def _warn_days_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return the warning window for the subentry data, if one is set."""
    warn_days = data.get(CONF_WARN_DAYS)
    return {CONF_WARN_DAYS: int(warn_days)} if warn_days is not None else {}


def _build_task_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build step 1 schema for a task."""
    d = defaults or {}
    has_assignees = bool(d.get(CONF_ASSIGNEES))

    schema: dict[vol.Optional | vol.Required, Any] = {
        vol.Required("name", default=d.get("name")): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(
            CONF_INTERVAL_VALUE,
            default=d.get(CONF_INTERVAL_VALUE, d.get(CONF_INTERVAL_DAYS, 7)),
        ): NumberSelector(
            NumberSelectorConfig(
                min=1, max=365, step=1, mode=NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_INTERVAL_UNIT, default=d.get(CONF_INTERVAL_UNIT, "days")
        ): _interval_unit_selector(),
    }

    desc = d.get(CONF_DESCRIPTION)
    if desc:
        schema[vol.Optional(CONF_DESCRIPTION, default=desc)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )
    else:
        schema[vol.Optional(CONF_DESCRIPTION)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )

    icon = d.get(CONF_ICON)
    if icon:
        schema[vol.Optional(CONF_ICON, default=icon)] = IconSelector()
    else:
        schema[vol.Optional(CONF_ICON)] = IconSelector()

    _add_active_months(schema, d)
    _add_warn_days(schema, d)
    _add_points(schema, d)
    schema[vol.Optional(CONF_REMINDERS, default=d.get(CONF_REMINDERS, True))] = (
        BooleanSelector()
    )

    schema[vol.Required(CONF_UNASSIGNED, default=not has_assignees)] = (
        BooleanSelector()
    )

    return vol.Schema(schema)


class TaskSubentryFlow(ConfigSubentryFlow):
    """Handle a subentry flow for adding/editing tasks."""

    def __init__(self) -> None:
        """Initialize the task subentry flow."""
        super().__init__()
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: basic task details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get("name", "").strip():
                errors["name"] = "name_required"

            if not errors:
                unassigned = user_input.pop(CONF_UNASSIGNED, True)
                self._data = user_input
                if not unassigned:
                    return await self.async_step_assignees()
                return self._create_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_task_schema(),
            errors=errors,
        )

    async def async_step_assignees(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: optional assignees and rotation mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_ASSIGNEES):
                errors[CONF_ASSIGNEES] = "assignees_required"

            if not errors:
                self._data[CONF_ASSIGNEES] = user_input[CONF_ASSIGNEES]
                self._data[CONF_ROTATION_MODE] = user_input.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                )
                return self._create_entry()

        return self.async_show_form(
            step_id="assignees",
            data_schema=_build_assignees_schema(),
            errors=errors,
        )

    def _create_entry(self) -> SubentryFlowResult:
        """Create the subentry from collected data."""
        return self.async_create_entry(
            title=self._data["name"],
            data={
                **_interval_data(self._data),
                **_warn_days_data(self._data),
                **_points_data(self._data),
                CONF_REMINDERS: bool(self._data.get(CONF_REMINDERS, True)),
                CONF_ASSIGNEES: self._data.get(CONF_ASSIGNEES, []),
                CONF_ROTATION_MODE: self._data.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                ),
                CONF_DESCRIPTION: self._data.get(CONF_DESCRIPTION),
                CONF_ICON: self._data.get(CONF_ICON),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1 of reconfiguration."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get("name", "").strip():
                errors["name"] = "name_required"

            if not errors:
                unassigned = user_input.pop(CONF_UNASSIGNED, True)
                self._data = user_input
                if not unassigned:
                    return await self.async_step_reconfigure_assignees()
                return self._update_entry(subentry)

        defaults = dict(subentry.data)
        defaults["name"] = subentry.title

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_task_schema(defaults),
            errors=errors,
        )

    async def async_step_reconfigure_assignees(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2 of reconfiguration: assignees."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_ASSIGNEES):
                errors[CONF_ASSIGNEES] = "assignees_required"

            if not errors:
                self._data[CONF_ASSIGNEES] = user_input[CONF_ASSIGNEES]
                self._data[CONF_ROTATION_MODE] = user_input.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                )
                return self._update_entry(subentry)

        defaults = dict(subentry.data)
        return self.async_show_form(
            step_id="reconfigure_assignees",
            data_schema=_build_assignees_schema(defaults),
            errors=errors,
        )

    def _update_entry(self, subentry) -> SubentryFlowResult:
        """Update the subentry from collected data."""
        entry = self._get_entry()
        new_title = self._data.get("name", subentry.title)
        if new_title != subentry.title:
            dev_reg = dr.async_get(self.hass)
            dev_reg.async_clear_config_subentry(
                entry.entry_id, subentry.subentry_id
            )
        return self.async_update_and_abort(
            entry,
            subentry,
            title=new_title,
            data={
                **_interval_data(self._data),
                **_warn_days_data(self._data),
                **_points_data(self._data),
                CONF_REMINDERS: bool(self._data.get(CONF_REMINDERS, True)),
                CONF_ASSIGNEES: self._data.get(CONF_ASSIGNEES, []),
                CONF_ROTATION_MODE: self._data.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                ),
                CONF_DESCRIPTION: self._data.get(CONF_DESCRIPTION),
                CONF_ICON: self._data.get(CONF_ICON),
            },
        )


CONF_UNASSIGNED = "unassigned"


def _build_maintenance_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build step 1 schema for a maintenance task."""
    d = defaults or {}
    has_assignees = bool(d.get(CONF_ASSIGNEES))

    schema: dict[vol.Optional | vol.Required, Any] = {
        vol.Required("name", default=d.get("name")): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(
            CONF_DEVICE_ID, default=d.get(CONF_DEVICE_ID)
        ): DeviceSelector(DeviceSelectorConfig()),
        vol.Required(
            CONF_INTERVAL_VALUE,
            default=d.get(CONF_INTERVAL_VALUE, d.get(CONF_INTERVAL_DAYS, 30)),
        ): NumberSelector(
            NumberSelectorConfig(
                min=1, max=730, step=1, mode=NumberSelectorMode.BOX
            )
        ),
        vol.Required(
            CONF_INTERVAL_UNIT, default=d.get(CONF_INTERVAL_UNIT, "days")
        ): _interval_unit_selector(),
    }

    desc = d.get(CONF_DESCRIPTION)
    if desc:
        schema[vol.Optional(CONF_DESCRIPTION, default=desc)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )
    else:
        schema[vol.Optional(CONF_DESCRIPTION)] = TextSelector(
            TextSelectorConfig(multiline=True)
        )

    icon = d.get(CONF_ICON)
    if icon:
        schema[vol.Optional(CONF_ICON, default=icon)] = IconSelector()
    else:
        schema[vol.Optional(CONF_ICON)] = IconSelector()

    _add_active_months(schema, d)
    _add_warn_days(schema, d)
    _add_points(schema, d)
    schema[vol.Optional(CONF_REMINDERS, default=d.get(CONF_REMINDERS, True))] = (
        BooleanSelector()
    )

    schema[vol.Required(CONF_UNASSIGNED, default=not has_assignees)] = (
        BooleanSelector()
    )

    return vol.Schema(schema)


def _build_assignees_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build step 2 schema for assignees/rotation."""
    d = defaults or {}

    assignees_default = d.get(CONF_ASSIGNEES, [])
    if not assignees_default:
        old = d.get(CONF_ASSIGNEE)
        if old:
            assignees_default = [old]

    return vol.Schema(
        {
            vol.Required(
                CONF_ASSIGNEES, default=assignees_default
            ): EntitySelector(
                EntitySelectorConfig(domain="person", multiple=True)
            ),
            vol.Optional(
                CONF_ROTATION_MODE,
                default=d.get(CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN),
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        {"value": RotationMode.ROUND_ROBIN, "label": "Round Robin"},
                        {"value": RotationMode.RANDOM, "label": "Random"},
                        {"value": RotationMode.WORKLOAD, "label": "Least workload"},
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


class MaintenanceSubentryFlow(ConfigSubentryFlow):
    """Handle a subentry flow for adding/editing maintenance tasks."""

    def __init__(self) -> None:
        """Initialize the maintenance subentry flow."""
        super().__init__()
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: basic maintenance task details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get("name", "").strip():
                errors["name"] = "name_required"
            if not user_input.get(CONF_DEVICE_ID):
                errors[CONF_DEVICE_ID] = "device_required"

            if not errors:
                unassigned = user_input.pop(CONF_UNASSIGNED, True)
                self._data = user_input
                if not unassigned:
                    return await self.async_step_assignees()
                return self._create_entry()

        return self.async_show_form(
            step_id="user",
            data_schema=_build_maintenance_schema(),
            errors=errors,
        )

    async def async_step_assignees(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: optional assignees and rotation mode."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_ASSIGNEES):
                errors[CONF_ASSIGNEES] = "assignees_required"

            if not errors:
                self._data[CONF_ASSIGNEES] = user_input[CONF_ASSIGNEES]
                self._data[CONF_ROTATION_MODE] = user_input.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                )
                return self._create_entry()

        return self.async_show_form(
            step_id="assignees",
            data_schema=_build_assignees_schema(),
            errors=errors,
        )

    def _create_entry(self) -> SubentryFlowResult:
        """Create the subentry from collected data."""
        return self.async_create_entry(
            title=self._data["name"],
            data={
                CONF_DEVICE_ID: self._data[CONF_DEVICE_ID],
                **_interval_data(self._data),
                **_warn_days_data(self._data),
                **_points_data(self._data),
                CONF_REMINDERS: bool(self._data.get(CONF_REMINDERS, True)),
                CONF_ASSIGNEES: self._data.get(CONF_ASSIGNEES, []),
                CONF_ROTATION_MODE: self._data.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                ),
                CONF_DESCRIPTION: self._data.get(CONF_DESCRIPTION),
                CONF_ICON: self._data.get(CONF_ICON),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1 of reconfiguration."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get("name", "").strip():
                errors["name"] = "name_required"
            if not user_input.get(CONF_DEVICE_ID):
                errors[CONF_DEVICE_ID] = "device_required"

            if not errors:
                unassigned = user_input.pop(CONF_UNASSIGNED, True)
                self._data = user_input
                if not unassigned:
                    return await self.async_step_reconfigure_assignees()
                return self._update_entry(subentry)

        defaults = dict(subentry.data)
        defaults["name"] = subentry.title

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_maintenance_schema(defaults),
            errors=errors,
        )

    async def async_step_reconfigure_assignees(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2 of reconfiguration: assignees."""
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_ASSIGNEES):
                errors[CONF_ASSIGNEES] = "assignees_required"

            if not errors:
                self._data[CONF_ASSIGNEES] = user_input[CONF_ASSIGNEES]
                self._data[CONF_ROTATION_MODE] = user_input.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                )
                return self._update_entry(subentry)

        defaults = dict(subentry.data)
        return self.async_show_form(
            step_id="reconfigure_assignees",
            data_schema=_build_assignees_schema(defaults),
            errors=errors,
        )

    def _update_entry(self, subentry) -> SubentryFlowResult:
        """Update the subentry from collected data."""
        entry = self._get_entry()
        old_device_id = subentry.data.get(CONF_DEVICE_ID)
        new_device_id = self._data[CONF_DEVICE_ID]

        if old_device_id and old_device_id != new_device_id:
            dev_reg = dr.async_get(self.hass)
            dev_reg.async_clear_config_subentry(
                entry.entry_id, subentry.subentry_id
            )

        return self.async_update_and_abort(
            entry,
            subentry,
            title=self._data.get("name", subentry.title),
            data={
                CONF_DEVICE_ID: new_device_id,
                **_interval_data(self._data),
                **_warn_days_data(self._data),
                **_points_data(self._data),
                CONF_REMINDERS: bool(self._data.get(CONF_REMINDERS, True)),
                CONF_ASSIGNEES: self._data.get(CONF_ASSIGNEES, []),
                CONF_ROTATION_MODE: self._data.get(
                    CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
                ),
                CONF_DESCRIPTION: self._data.get(CONF_DESCRIPTION),
                CONF_ICON: self._data.get(CONF_ICON),
            },
        )


class ImportSubentryFlow(ConfigSubentryFlow):
    """Handle a subentry flow for importing tasks from the catalog."""

    def __init__(self) -> None:
        """Initialize the import subentry flow."""
        super().__init__()
        self._selected_categories: list[str] = []
        self._selected_task_ids: list[str] = []
        self._resolved_lang: str | None = None

    async def _resolve_lang(self) -> str:
        """Resolve the catalog language from the requesting user's frontend preference.

        Falls back to the HA system language, then to English.
        """
        if self._resolved_lang is not None:
            return self._resolved_lang

        lang: str | None = None
        with suppress(Exception):
            from homeassistant.helpers.http import current_request

            if (request := current_request.get()) is not None:
                user = request.get("hass_user")
                if user is not None:
                    from homeassistant.components.frontend import (
                        storage as frontend_store,
                    )

                    store = await frontend_store.async_user_store(
                        self.hass, user.id
                    )
                    if (
                        "language" in store.data
                        and "language" in store.data["language"]
                    ):
                        lang = store.data["language"]["language"]

        if not lang:
            lang = self.hass.config.language or "en"

        self._resolved_lang = lang.split("-", 1)[0]
        return self._resolved_lang

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: select categories from the task catalog."""
        from .catalog import get_categories

        errors: dict[str, str] = {}
        if user_input is not None:
            selected = user_input.get("categories", [])
            if not selected:
                errors["categories"] = "no_categories_selected"

            if not errors:
                self._selected_categories = selected
                return await self.async_step_select_tasks()

        categories = await get_categories(await self._resolve_lang())

        if not categories:
            return self.async_abort(reason="catalog_empty")

        options = [
            {"value": cat["id"], "label": cat["name"]} for cat in categories
        ]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("categories"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_select_tasks(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: select specific tasks from the chosen categories."""
        from .catalog import get_tasks_for_categories

        errors: dict[str, str] = {}
        tasks = await get_tasks_for_categories(self._selected_categories, await self._resolve_lang())

        if not tasks:
            return self.async_abort(reason="no_tasks_found")

        if user_input is not None:
            selected_ids = user_input.get("tasks", [])
            if not selected_ids:
                errors["tasks"] = "no_tasks_selected"

            if not errors:
                self._selected_task_ids = selected_ids
                return await self.async_step_configure()

        entry = self._get_entry()
        existing_titles = {
            sub.title for sub in entry.subentries.values()
        }

        options = []
        for task in tasks:
            label = f"{task['name']} ({task['default_interval_days']}d)"
            if task["name"] in existing_titles:
                label += " \u2022 exists"
            options.append({"value": task["id"], "label": label})

        return self.async_show_form(
            step_id="select_tasks",
            data_schema=vol.Schema(
                {
                    vol.Required("tasks"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 3: optional bulk configuration for imported tasks."""
        if user_input is not None:
            return await self._create_imported_subentries(user_input)

        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Optional("interval_override"): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=365,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="days",
                        )
                    ),
                    vol.Optional(CONF_ASSIGNEES): EntitySelector(
                        EntitySelectorConfig(domain="person", multiple=True)
                    ),
                    vol.Optional(
                        CONF_ROTATION_MODE,
                        default=RotationMode.ROUND_ROBIN,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": RotationMode.ROUND_ROBIN,
                                    "label": "Round Robin",
                                },
                                {
                                    "value": RotationMode.RANDOM,
                                    "label": "Random",
                                },
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def _create_imported_subentries(
        self, user_input: dict[str, Any]
    ) -> SubentryFlowResult:
        """Create task/maintenance subentries for each selected catalog task."""
        from .catalog import get_task_by_id

        entry = self._get_entry()
        interval_override = user_input.get("interval_override")
        assignees = user_input.get(CONF_ASSIGNEES, [])
        rotation_mode = user_input.get(
            CONF_ROTATION_MODE, RotationMode.ROUND_ROBIN
        )

        count = 0
        for task_id in self._selected_task_ids:
            task = await get_task_by_id(task_id, await self._resolve_lang())
            if task is None:
                continue
            subentry_type = (
                SUBENTRY_TYPE_MAINTENANCE
                if task.get("type") == "maintenance"
                else SUBENTRY_TYPE_TASK
            )

            data: dict[str, Any] = {
                CONF_INTERVAL_DAYS: int(
                    interval_override or task["default_interval_days"]
                ),
                CONF_ASSIGNEES: assignees,
                CONF_ROTATION_MODE: rotation_mode,
                CONF_DESCRIPTION: task.get("description"),
                CONF_ICON: task.get("icon"),
            }

            if subentry_type == SUBENTRY_TYPE_MAINTENANCE:
                data[CONF_DEVICE_ID] = None

            subentry = ConfigSubentry(
                data=data,
                subentry_type=subentry_type,
                title=task["name"],
                unique_id=None,
            )
            self.hass.config_entries.async_add_subentry(entry, subentry)
            count += 1

        return self.async_abort(
            reason="import_success",
            description_placeholders={"count": str(count)},
        )
