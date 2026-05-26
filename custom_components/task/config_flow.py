"""Config flow for the Task integration."""

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
)

from .const import (
    CONF_AREA_ID,
    CONF_ASSIGNEE,
    CONF_ASSIGNEES,
    CONF_DESCRIPTION,
    CONF_DEVICE_ID,
    CONF_ICON,
    CONF_INTERVAL_DAYS,
    CONF_ROTATION_MODE,
    DOMAIN,
    SUBENTRY_TYPE_IMPORT,
    SUBENTRY_TYPE_MAINTENANCE,
    SUBENTRY_TYPE_TASK,
    RotationMode,
)


class TaskConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Task."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            SUBENTRY_TYPE_TASK: TaskSubentryFlow,
            SUBENTRY_TYPE_MAINTENANCE: MaintenanceSubentryFlow,
            SUBENTRY_TYPE_IMPORT: ImportSubentryFlow,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step to select an area."""
        errors: dict[str, str] = {}

        if user_input is not None:
            if not user_input.get(CONF_AREA_ID):
                errors[CONF_AREA_ID] = "area_required"

            if not errors:
                area_id = user_input[CONF_AREA_ID]
                area_reg = ar.async_get(self.hass)
                area_entry = area_reg.async_get_area(area_id)
                title = area_entry.name if area_entry else area_id

                await self.async_set_unique_id(area_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=title,
                    data={CONF_AREA_ID: area_id},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AREA_ID): AreaSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of the area."""
        if user_input is not None:
            area_id = user_input[CONF_AREA_ID]
            area_reg = ar.async_get(self.hass)
            area_entry = area_reg.async_get_area(area_id)
            title = area_entry.name if area_entry else area_id

            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                title=title,
                data={CONF_AREA_ID: area_id},
            )

        entry = self._get_reconfigure_entry()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_AREA_ID, default=entry.data.get(CONF_AREA_ID)
                    ): AreaSelector(),
                }
            ),
        )


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
            CONF_INTERVAL_DAYS,
            default=d.get(CONF_INTERVAL_DAYS, 7),
        ): NumberSelector(
            NumberSelectorConfig(
                min=1,
                max=365,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="days",
            )
        ),
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
                CONF_INTERVAL_DAYS: int(self._data[CONF_INTERVAL_DAYS]),
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
        return self.async_update_and_abort(
            self._get_entry(),
            subentry,
            title=self._data.get("name", subentry.title),
            data={
                CONF_INTERVAL_DAYS: int(self._data[CONF_INTERVAL_DAYS]),
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
            CONF_INTERVAL_DAYS,
            default=d.get(CONF_INTERVAL_DAYS, 30),
        ): NumberSelector(
            NumberSelectorConfig(
                min=1,
                max=730,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="days",
            )
        ),
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
                CONF_INTERVAL_DAYS: int(self._data[CONF_INTERVAL_DAYS]),
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
        return self.async_update_and_abort(
            self._get_entry(),
            subentry,
            title=self._data.get("name", subentry.title),
            data={
                CONF_DEVICE_ID: self._data[CONF_DEVICE_ID],
                CONF_INTERVAL_DAYS: int(self._data[CONF_INTERVAL_DAYS]),
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
            from homeassistant.helpers.http import current_request  # noqa: PLC0415

            if (request := current_request.get()) is not None:
                user = request.get("hass_user")
                if user is not None:
                    from homeassistant.components.frontend import (  # noqa: PLC0415
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
