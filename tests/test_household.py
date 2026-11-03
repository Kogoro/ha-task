"""The household entry: global totals and the unified calendar."""

import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import (
    SOURCE_IMPORT,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.task.const import DOMAIN

from .common import entity_id, task_sensor, task_subentry

NOW = "2026-11-03 12:00:00+00:00"
CALENDAR_UNIQUE_ID = "task_unified_calendar"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def areas(hass: HomeAssistant) -> dict[str, str]:
    """Create two areas and return their IDs by name."""
    registry = ar.async_get(hass)
    return {
        name: registry.async_create(name).id for name in ("Kitchen", "Bathroom")
    }


async def add_area(
    hass: HomeAssistant, area_id: str, tasks: list, **data
) -> MockConfigEntry:
    """Add and set up an area entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=area_id,
        data={"area_id": area_id, **data},
        subentries_data=tasks,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def add_household(hass: HomeAssistant, **data) -> MockConfigEntry:
    """Add and set up the household entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="household",
        title="Household",
        data={"entry_type": "household", **data},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def value(hass: HomeAssistant, household: MockConfigEntry, key: str):
    """Return the state of a household sensor."""
    return hass.states.get(entity_id(hass, household, "sensor", key))


def unified_calendar(hass: HomeAssistant) -> str | None:
    """Return the entity ID of the unified calendar."""
    return er.async_get(hass).async_get_entity_id("calendar", DOMAIN, CALENDAR_UNIQUE_ID)


def own_calendar(hass: HomeAssistant, area: MockConfigEntry) -> str | None:
    """Return the entity ID of an area's own calendar."""
    return er.async_get(hass).async_get_entity_id(
        "calendar", DOMAIN, f"{area.entry_id}_calendar"
    )


async def calendar_titles(hass: HomeAssistant, entity: str) -> set[str]:
    """Return the event titles of the next 30 days."""
    start = datetime.datetime(2026, 11, 3, tzinfo=datetime.UTC)
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity,
            "start_date_time": start,
            "end_date_time": start + datetime.timedelta(days=30),
        },
        blocking=True,
        return_response=True,
    )
    return {event["summary"] for event in result[entity]["events"]}


# --- config flow -----------------------------------------------------------


async def test_menu_offers_household_and_creates_it(hass: HomeAssistant) -> None:
    """The household entry can be added from the menu."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["menu_options"] == ["area", "household"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "household"}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"calendar_name": " Everything "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"entry_type": "household", "calendar_name": "Everything"}
    assert result["context"]["unique_id"] == "household"


async def test_only_one_household(hass: HomeAssistant) -> None:
    """A second household entry is refused."""
    await add_household(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # the menu is gone: with a household the flow goes straight to the area form
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "area"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data={}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_unified_option_only_with_household(hass: HomeAssistant) -> None:
    """"Hide this area's calendar" is only offered once a household exists."""

    async def area_fields() -> set[str]:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        if result["type"] is FlowResultType.MENU:
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"next_step_id": "area"}
            )
        schema = result["data_schema"].schema
        hass.config_entries.flow.async_abort(result["flow_id"])
        return {str(key) for key in schema}

    assert "unified_calendar" not in await area_fields()
    await add_household(hass)
    assert "unified_calendar" in await area_fields()


async def test_reconfigure_household_renames_the_calendar(
    hass: HomeAssistant, areas
) -> None:
    """The calendar name is changed on the household entry."""
    household = await add_household(hass)
    entity = unified_calendar(hass)
    assert hass.states.get(entity).name == "All Tasks"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": household.entry_id},
    )
    assert result["step_id"] == "reconfigure_household"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"calendar_name": "Whole house"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert household.data["calendar_name"] == "Whole house"
    assert hass.states.get(unified_calendar(hass)).name == "Whole house"


async def test_household_has_no_subentries(hass: HomeAssistant) -> None:
    """Tasks are added to areas, not to the household."""
    household = await add_household(hass)
    from custom_components.task.config_flow import TaskConfigFlow

    assert TaskConfigFlow.async_get_supported_subentry_types(household) == {}


# --- totals ----------------------------------------------------------------


async def test_totals_are_the_sum_of_the_areas(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """The global sensors add up the area sensors."""
    kitchen = await add_area(
        hass,
        areas["Kitchen"],
        [task_subentry("k1", "Oven"), task_subentry("k2", "Fridge", interval_days=30)],
        warn_days=3,
    )
    bathroom = await add_area(
        hass, areas["Bathroom"], [task_subentry("b1", "Shower")], warn_days=3
    )
    household = await add_household(hass)
    # Fridge is done, so it is fine; Oven and Shower were never done, so overdue.
    await hass.services.async_call(
        DOMAIN, "complete_task", {"entity_id": task_sensor(hass, kitchen, "k2")},
        blocking=True,
    )

    overdue = value(hass, household, "overdue_count")
    assert overdue.state == "2"
    assert sorted(overdue.attributes["tasks"]) == ["Bathroom: Shower", "Kitchen: Oven"]
    for key in ("overdue_count", "due_today", "due_this_week", "due_soon"):
        total = sum(
            int(hass.states.get(entity_id(hass, area, "sensor", key)).state)
            for area in (kitchen, bathroom)
        )
        assert int(value(hass, household, key).state) == total, key


async def test_totals_follow_areas_that_come_and_go(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """Adding, unloading and removing an area changes the totals."""
    household = await add_household(hass)
    assert value(hass, household, "overdue_count").state == "0"

    kitchen = await add_area(hass, areas["Kitchen"], [task_subentry("k1", "Oven")])
    assert value(hass, household, "overdue_count").state == "1"

    bathroom = await add_area(hass, areas["Bathroom"], [task_subentry("b1", "Shower")])
    assert value(hass, household, "overdue_count").state == "2"

    assert await hass.config_entries.async_unload(kitchen.entry_id)
    await hass.async_block_till_done()
    assert value(hass, household, "overdue_count").state == "1"
    assert value(hass, household, "overdue_count").attributes["tasks"] == [
        "Bathroom: Shower"
    ]
    assert bathroom.state is ConfigEntryState.LOADED


async def test_totals_update_when_a_task_changes(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """Completing a task in an area is reflected in the totals."""
    kitchen = await add_area(hass, areas["Kitchen"], [task_subentry("k1", "Oven")])
    household = await add_household(hass)
    assert value(hass, household, "overdue_count").state == "1"

    await hass.services.async_call(
        DOMAIN, "complete_task", {"entity_id": task_sensor(hass, kitchen, "k1")},
        blocking=True,
    )

    assert value(hass, household, "overdue_count").state == "0"


# --- unified calendar ------------------------------------------------------


async def test_unified_calendar_has_all_areas(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """The household calendar lists the tasks of every area."""
    await add_area(hass, areas["Kitchen"], [task_subentry("k1", "Oven")])
    await add_area(hass, areas["Bathroom"], [task_subentry("b1", "Shower")])
    await add_household(hass)

    assert await calendar_titles(hass, unified_calendar(hass)) == {"Oven", "Shower"}


async def test_unified_calendar_survives_unloading_an_area(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """It no longer depends on one "owner" area."""
    kitchen = await add_area(hass, areas["Kitchen"], [task_subentry("k1", "Oven")])
    await add_area(hass, areas["Bathroom"], [task_subentry("b1", "Shower")])
    await add_household(hass)

    assert await hass.config_entries.async_unload(kitchen.entry_id)
    await hass.async_block_till_done()

    entity = unified_calendar(hass)
    assert hass.states.get(entity).state != "unavailable"
    assert await calendar_titles(hass, entity) == {"Shower"}


async def test_area_with_the_option_has_no_own_calendar(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """With a household, the area's tasks are only in the household calendar."""
    household = await add_household(hass)
    hidden = await add_area(
        hass, areas["Kitchen"], [task_subentry("k1", "Oven")], unified_calendar=True
    )
    normal = await add_area(hass, areas["Bathroom"], [task_subentry("b1", "Shower")])

    assert own_calendar(hass, hidden) is None
    assert own_calendar(hass, normal) is not None
    assert await calendar_titles(hass, unified_calendar(hass)) == {"Oven", "Shower"}
    assert household.state is ConfigEntryState.LOADED


async def test_removing_the_household_gives_the_calendar_back(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """Without a household an area shows its own calendar again."""
    household = await add_household(hass)
    area = await add_area(
        hass, areas["Kitchen"], [task_subentry("k1", "Oven")], unified_calendar=True
    )
    assert own_calendar(hass, area) is None

    assert await hass.config_entries.async_remove(household.entry_id)
    await hass.async_block_till_done()

    assert own_calendar(hass, area) is not None
    assert unified_calendar(hass) is None


# --- upgrade ---------------------------------------------------------------


async def test_upgrade_creates_the_household(
    hass: HomeAssistant, areas: dict[str, str]
) -> None:
    """An install that used the unified calendar keeps it, with its name."""
    ent_reg = er.async_get(hass)
    area = MockConfigEntry(
        domain=DOMAIN,
        unique_id=areas["Kitchen"],
        data={
            "area_id": areas["Kitchen"],
            "unified_calendar": True,
            "calendar_name": "Everything",
        },
        subentries_data=[task_subentry("k1", "Oven")],
    )
    area.add_to_hass(hass)
    # What the old version left behind: the unified calendar owned by the area.
    old = ent_reg.async_get_or_create(
        "calendar", DOMAIN, CALENDAR_UNIQUE_ID, config_entry=area,
        suggested_object_id="everything",
    )
    # ... and the area's own calendar from before it opted in
    ent_reg.async_get_or_create(
        "calendar", DOMAIN, f"{area.entry_id}_calendar", config_entry=area
    )
    # ... on the device it used to share with nothing else
    dev_reg = dr.async_get(hass)
    legacy = dev_reg.async_get_or_create(
        config_entry_id=area.entry_id, identifiers={(DOMAIN, "unified_calendar")}
    )
    ent_reg.async_update_entity(old.entity_id, device_id=legacy.id)

    assert await hass.config_entries.async_setup(area.entry_id)
    await hass.async_block_till_done()
    # entries are set up by Home Assistant's startup; run the migration as it does
    from custom_components.task import _async_migrate_unified_calendar

    _async_migrate_unified_calendar(hass)
    await hass.async_block_till_done()
    await hass.async_block_till_done()

    households = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get("entry_type") == "household"
    ]
    assert len(households) == 1
    household = households[0]
    assert household.state is ConfigEntryState.LOADED
    assert household.data["calendar_name"] == "Everything"

    moved = ent_reg.async_get(old.entity_id)
    assert moved.config_entry_id == household.entry_id, "entity keeps its entity ID"
    assert hass.states.get(old.entity_id).name == "Everything"
    assert await calendar_titles(hass, old.entity_id) == {"Oven"}
    assert own_calendar(hass, area) is None, "the area's own calendar is dropped"
    assert dev_reg.async_get(legacy.id) is None, "the old calendar device is cleaned up"
    assert ent_reg.async_get(old.entity_id).device_id is None
