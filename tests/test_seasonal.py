"""Month intervals and active months in the running integration."""

import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.task.const import DOMAIN

from .common import (
    entity_id,
    refresh,
    setup_entry,
    status_sensor,
    task_sensor,
    task_subentry,
)

NOW = "2026-11-03 12:00:00+00:00"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


async def complete(hass: HomeAssistant, sensor: str, when: str | None = None) -> None:
    """Complete a task, optionally at a UTC date like "2026-10-31"."""
    data = {"entity_id": sensor}
    if when:
        data["completed_at"] = f"{when} 12:00:00+00:00"
    await hass.services.async_call(DOMAIN, "complete_task", data, blocking=True)


def attrs(hass: HomeAssistant, sensor: str) -> dict:
    """Return the attributes of a task sensor."""
    return hass.states.get(sensor).attributes


async def test_a_month_interval_counts_calendar_months(hass: HomeAssistant) -> None:
    """31 October + 1 month is 30 November, 27 days from now."""
    entry = await setup_entry(
        hass, [task_subentry("t1", "Filter", interval_value=1, interval_unit="months")]
    )
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor, "2026-10-31")

    assert hass.states.get(sensor).state == "27"
    assert attrs(hass, sensor)["interval_unit"] == "months"
    assert attrs(hass, sensor)["interval_value"] == 1


async def test_a_week_interval(hass: HomeAssistant) -> None:
    """Two weeks from three days ago is eleven days away."""
    entry = await setup_entry(
        hass, [task_subentry("t1", "Bins", interval_value=2, interval_unit="weeks")]
    )
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor, "2026-10-31")

    assert hass.states.get(sensor).state == "11"


async def test_tasks_with_only_days_are_unchanged(hass: HomeAssistant) -> None:
    """Data from before units existed still means days."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum", interval_days=10)])
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor)

    state = hass.states.get(sensor)
    assert state.state == "10"
    assert state.attributes["interval_unit"] == "days"
    assert state.attributes["interval_value"] == 10
    assert state.attributes["active_months"] == []
    assert state.attributes["in_season"] is True


async def test_never_done_outside_the_season_is_not_overdue(
    hass: HomeAssistant,
) -> None:
    """A spring task is not due in November."""
    entry = await setup_entry(
        hass, [task_subentry("t1", "Windows", active_months=[3, 4, 5])]
    )
    sensor = task_sensor(hass, entry, "t1")

    state = hass.states.get(sensor)
    assert state.state == "118", "days until the season opens on 1 March"
    assert state.attributes["overdue"] is False
    assert state.attributes["in_season"] is False
    assert hass.states.get(status_sensor(hass, entry, "t1")).state == "ok"
    overdue = entity_id(hass, entry, "binary_sensor", "t1_overdue")
    assert hass.states.get(overdue).state == "off"


async def test_never_done_inside_the_season_is_due(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """In season it behaves as before: due immediately."""
    freezer.move_to("2026-04-10 12:00:00+00:00")
    entry = await setup_entry(
        hass, [task_subentry("t1", "Windows", active_months=[3, 4, 5])]
    )
    state = hass.states.get(task_sensor(hass, entry, "t1"))

    assert state.state == "0"
    assert state.attributes["overdue"] is True
    assert state.attributes["in_season"] is True


async def test_the_next_due_date_waits_for_the_next_season(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Done at the end of the season, the next one is due when it reopens."""
    freezer.move_to("2026-09-25 12:00:00+00:00")
    entry = await setup_entry(
        hass,
        [task_subentry("t1", "Garden", active_months=[4, 5, 6, 7, 8, 9])],
    )
    sensor = task_sensor(hass, entry, "t1")
    events = async_capture_events(hass, "task_completed")

    await complete(hass, sensor)
    await hass.async_block_till_done()

    assert attrs(hass, sensor)["next_due"] == "2027-04-01"
    assert events[0].data["next_due"] == "2027-04-01"


async def test_a_missed_window_is_not_overdue_after_it_closed(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Due on 29 September but not done: after the season it just waits."""
    freezer.move_to("2026-09-22 12:00:00+00:00")
    entry = await setup_entry(
        hass, [task_subentry("t1", "Garden", active_months=[4, 5, 6, 7, 8, 9])]
    )
    sensor = task_sensor(hass, entry, "t1")
    await complete(hass, sensor)
    assert attrs(hass, sensor)["next_due"] == "2026-09-29"

    freezer.move_to("2026-10-02 12:00:00+00:00")
    await refresh(hass, entry)

    state = hass.states.get(sensor)
    assert state.attributes["overdue"] is False
    assert state.attributes["next_due"] == "2027-04-01"


async def test_out_of_season_tasks_are_not_counted(hass: HomeAssistant) -> None:
    """The area totals ignore tasks that are not in season."""
    entry = await setup_entry(
        hass,
        [
            task_subentry("t1", "Windows", active_months=[3, 4, 5]),
            task_subentry("t2", "Vacuum"),
        ],
    )

    overdue = hass.states.get(entity_id(hass, entry, "sensor", "overdue_count"))
    assert overdue.state == "1", "only the vacuum"
    assert overdue.attributes["tasks"] == ["Vacuum"]


async def test_the_calendar_only_has_events_in_the_season(hass: HomeAssistant) -> None:
    """No events in November for a spring task, but some in April."""
    entry = await setup_entry(
        hass,
        [task_subentry("t1", "Windows", interval_value=1, interval_unit="weeks", active_months=[4, 5])],
    )
    calendar = er.async_get(hass).async_get_entity_id(
        "calendar", DOMAIN, f"{entry.entry_id}_calendar"
    )

    async def titles(start: datetime.datetime, end: datetime.datetime) -> list[str]:
        result = await hass.services.async_call(
            "calendar",
            "get_events",
            {"entity_id": calendar, "start_date_time": start, "end_date_time": end},
            blocking=True,
            return_response=True,
        )
        return [event["start"] for event in result[calendar]["events"]]

    utc = datetime.UTC
    assert await titles(datetime.datetime(2026, 11, 1, tzinfo=utc), datetime.datetime(2026, 12, 15, tzinfo=utc)) == []
    april = await titles(datetime.datetime(2027, 4, 1, tzinfo=utc), datetime.datetime(2027, 4, 30, tzinfo=utc))
    assert april
    assert all(day.startswith("2027-04") for day in april)
