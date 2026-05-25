"""Config flow for the Task integration."""

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    AreaSelector,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    PersonSelector,
    TextSelector,
)

from .const import (
    CONF_AREA_ID,
    CONF_ASSIGNEE,
    CONF_DESCRIPTION,
    CONF_ICON,
    CONF_INTERVAL_DAYS,
    DOMAIN,
    SUBENTRY_TYPE_TASK,
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
        return {SUBENTRY_TYPE_TASK: TaskSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step to select an area."""
        if user_input is not None:
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


class TaskSubentryFlow(ConfigSubentryFlow):
    """Handle a subentry flow for adding/editing tasks."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle creating a new task."""
        if user_input is not None:
            return self.async_create_entry(
                title=user_input["name"],
                data={
                    CONF_INTERVAL_DAYS: int(user_input[CONF_INTERVAL_DAYS]),
                    CONF_ASSIGNEE: user_input.get(CONF_ASSIGNEE),
                    CONF_DESCRIPTION: user_input.get(CONF_DESCRIPTION),
                    CONF_ICON: user_input.get(CONF_ICON),
                },
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): TextSelector(),
                    vol.Required(CONF_INTERVAL_DAYS, default=7): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=365,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(CONF_ASSIGNEE): PersonSelector(),
                    vol.Optional(CONF_DESCRIPTION): TextSelector(),
                    vol.Optional(CONF_ICON): IconSelector(),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguration of an existing task."""
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            return self.async_update_and_abort(
                self._get_reconfigure_entry(),
                subentry,
                title=user_input.get("name", subentry.title),
                data={
                    CONF_INTERVAL_DAYS: int(user_input[CONF_INTERVAL_DAYS]),
                    CONF_ASSIGNEE: user_input.get(CONF_ASSIGNEE),
                    CONF_DESCRIPTION: user_input.get(CONF_DESCRIPTION),
                    CONF_ICON: user_input.get(CONF_ICON),
                },
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "name", default=subentry.title
                    ): TextSelector(),
                    vol.Required(
                        CONF_INTERVAL_DAYS,
                        default=subentry.data.get(CONF_INTERVAL_DAYS, 7),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=365,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_ASSIGNEE,
                        default=subentry.data.get(CONF_ASSIGNEE),
                    ): PersonSelector(),
                    vol.Optional(
                        CONF_DESCRIPTION,
                        default=subentry.data.get(CONF_DESCRIPTION),
                    ): TextSelector(),
                    vol.Optional(
                        CONF_ICON,
                        default=subentry.data.get(CONF_ICON),
                    ): IconSelector(),
                }
            ),
        )
