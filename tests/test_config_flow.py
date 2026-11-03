"""Config flow: area, task subentry and warn days."""

from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.task.const import DOMAIN

from .common import setup_entry, status_sensor, task_subentry


async def _start_area_flow(hass: HomeAssistant):
    """Open the add flow and choose "Area" from the menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["area", "household"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "area"}
    )


async def test_area_flow_stores_warn_days(hass: HomeAssistant) -> None:
    """The area entry keeps the warn days, defaulting to 7."""
    result = await _start_area_flow(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area_id": "kitchen"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["area_id"] == "kitchen"
    assert result["data"]["warn_days"] == 7


async def test_area_flow_custom_warn_days(hass: HomeAssistant) -> None:
    """A chosen value is stored as an integer."""
    result = await _start_area_flow(hass)
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
        {"name": "Vacuum", "interval_value": 7, "unassigned": True, **user_input},
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
        {"name": "Vacuum", "interval_value": 7, "unassigned": True, **user_input},
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


async def test_task_points_default_to_one(hass: HomeAssistant) -> None:
    """A task without a chosen effort counts as one point."""
    entry = await setup_entry(hass, [])

    result = await _add_task(hass, entry)

    assert result["data"]["points"] == 1


async def test_task_with_points(hass: HomeAssistant) -> None:
    """The effort is stored as an integer."""
    entry = await setup_entry(hass, [])

    result = await _add_task(hass, entry, points=8.0)

    assert result["data"]["points"] == 8


async def test_workload_rotation_can_be_chosen(hass: HomeAssistant) -> None:
    """The assignees step offers the workload mode next to round-robin and random."""
    entry = await setup_entry(hass, [])
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, "task"), context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"name": "Vacuum", "interval_value": 7, "unassigned": False},
    )
    assert result["step_id"] == "assignees"
    schema = {str(key): key for key in result["data_schema"].schema}
    selector = result["data_schema"].schema[schema["rotation_mode"]]
    values = [option["value"] for option in selector.config["options"]]

    assert values == ["round_robin", "random", "workload"]


async def test_task_with_a_month_interval_and_active_months(hass: HomeAssistant) -> None:
    """The interval keeps its unit, active months are stored sorted as numbers."""
    entry = await setup_entry(hass, [])

    result = await _add_task(
        hass,
        entry,
        interval_value=3.0,
        interval_unit="months",
        active_months=["5", "3", "4"],
    )

    assert result["data"]["interval_value"] == 3
    assert result["data"]["interval_unit"] == "months"
    assert result["data"]["interval_days"] == 91, "kept in days for everything that only knows days"
    assert result["data"]["active_months"] == [3, 4, 5]


async def test_task_without_active_months_stores_none(hass: HomeAssistant) -> None:
    """Leaving the months empty means all year."""
    entry = await setup_entry(hass, [])

    result = await _add_task(hass, entry, interval_value=2.0, interval_unit="weeks")

    assert result["data"]["interval_days"] == 14
    assert "active_months" not in result["data"]


async def test_reconfigure_can_clear_the_active_months(hass: HomeAssistant) -> None:
    """Emptying the field makes the task active all year again."""
    entry = await setup_entry(
        hass, [task_subentry("t1", "Vacuum", active_months=[3, 4], interval_unit="days")]
    )

    result = await _reconfigure_task(hass, entry)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert "active_months" not in entry.subentries["t1"].data


async def _area_flow_result(hass: HomeAssistant, **user_input):
    result = await _start_area_flow(hass)
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area_id": "kitchen", **user_input}
    )


async def test_area_reminders_default_to_off_with_a_morning_time(
    hass: HomeAssistant,
) -> None:
    """Without a target nothing is sent; the time defaults to 08:00."""
    result = await _area_flow_result(hass)

    assert "reminder_targets" not in result["data"]
    assert "reminder_service" not in result["data"]
    assert result["data"]["reminder_due_soon"] is True
    assert result["data"]["reminder_overdue"] is True
    assert result["data"]["reminder_time"] == "08:00:00"


async def test_area_reminders_are_stored(hass: HomeAssistant) -> None:
    """Targets, kinds and time are kept."""
    result = await _area_flow_result(
        hass,
        reminder_targets=["notify.phone"],
        reminder_service="notify.mobile_app_pixel",
        reminder_due_soon=False,
        reminder_time="07:30:00",
    )

    assert result["data"]["reminder_targets"] == ["notify.phone"]
    assert result["data"]["reminder_service"] == "notify.mobile_app_pixel"
    assert result["data"]["reminder_due_soon"] is False
    assert result["data"]["reminder_time"] == "07:30:00"


async def test_an_invalid_notify_service_is_rejected(hass: HomeAssistant) -> None:
    """The service has to look like notify.<name>."""
    result = await _area_flow_result(hass, reminder_service="light.turn_on")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"reminder_service": "invalid_notify_service"}


async def test_reminders_can_be_turned_off_again_by_reconfiguring(
    hass: HomeAssistant,
) -> None:
    """Emptying the targets removes them."""
    entry = await setup_entry(hass, [], reminder_targets=["notify.phone"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area_id": "kitchen"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert "reminder_targets" not in entry.data


async def test_task_reminders_default_to_on(hass: HomeAssistant) -> None:
    """A new task sends reminders unless turned off."""
    entry = await setup_entry(hass, [])

    on = await _add_task(hass, entry)
    off = await _add_task(hass, entry, reminders=False)

    assert on["data"]["reminders"] is True
    assert off["data"]["reminders"] is False
