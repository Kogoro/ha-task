"""Config flow: area, task subentry and warn days."""

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.task.const import DOMAIN

from .common import setup_entry, status_sensor, task_subentry


async def test_area_flow_stores_warn_days(hass: HomeAssistant) -> None:
    """The area entry keeps the warn days, defaulting to 7."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area_id": "kitchen"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["area_id"] == "kitchen"
    assert result["data"]["warn_days"] == 7


async def test_area_flow_custom_warn_days(hass: HomeAssistant) -> None:
    """A chosen value is stored as an integer."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area_id": "kitchen", "warn_days": 3.0}
    )

    assert result["data"]["warn_days"] == 3


async def _add_task(hass: HomeAssistant, entry: MockConfigEntry, **user_input):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Vacuum", "interval_days": 7, "unassigned": True, **user_input},
    )


async def test_task_with_warn_days(hass: HomeAssistant) -> None:
    """A task can set its own warn days."""
    entry = await setup_entry(hass, [])

    result = await _add_task(hass, entry, warn_days=2.0)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["warn_days"] == 2


async def test_task_without_warn_days(hass: HomeAssistant) -> None:
    """Leaving the field empty stores nothing, so the area value applies."""
    entry = await setup_entry(hass, [])

    result = await _add_task(hass, entry)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "warn_days" not in result["data"]


async def _reconfigure_task(hass: HomeAssistant, entry: MockConfigEntry, **user_input):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": "t1"},
    )
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Vacuum", "interval_days": 7, "unassigned": True, **user_input},
    )


async def test_reconfigure_changes_warn_days(hass: HomeAssistant) -> None:
    """Editing a task can change its own warn days."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum", warn_days=2)])

    result = await _reconfigure_task(hass, entry, warn_days=5.0)

    assert result["type"] is FlowResultType.ABORT
    assert entry.subentries["t1"].data["warn_days"] == 5


async def test_reconfigure_can_clear_warn_days(hass: HomeAssistant) -> None:
    """Emptying the field removes the override, so the area value applies again."""
    entry = await setup_entry(
        hass, [task_subentry("t1", "Vacuum", warn_days=2)], warn_days=4
    )

    result = await _reconfigure_task(hass, entry)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert "warn_days" not in entry.subentries["t1"].data
    status = hass.states.get(status_sensor(hass, entry, "t1"))
    assert status.attributes["warn_days"] == 4
