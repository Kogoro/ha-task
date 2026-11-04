"""People who are away are skipped by the rotation."""

import datetime
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.task.const import DOMAIN
from custom_components.task.store import TaskStore

from .common import refresh, setup_entry, task_sensor, task_subentry

NOW = "2026-11-03 12:00:00+00:00"
PEOPLE = ["person.anna", "person.ben", "person.cara"]


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture(autouse=True)
def stable_random_pool():
    """Keep the random pool in the order of the assignees."""
    with patch("custom_components.task.store.random.shuffle", lambda items: None):
        yield


async def setup_task(hass: HomeAssistant, mode: str = "round_robin", people=PEOPLE):
    """Set up one task with the given assignees."""
    entry = await setup_entry(
        hass,
        [task_subentry("t1", "Vacuum", assignees=list(people), rotation_mode=mode)],
    )
    return entry, task_sensor(hass, entry, "t1")


def assignee(hass: HomeAssistant, sensor: str) -> str | None:
    """Return who is responsible."""
    return hass.states.get(sensor).attributes["current_assignee"]


async def away(hass: HomeAssistant, person: str, **data) -> None:
    """Call task.set_away."""
    await hass.services.async_call(
        DOMAIN, "set_away", {"person": person, **data}, blocking=True
    )


async def back(hass: HomeAssistant, person: str) -> None:
    """Call task.clear_away."""
    await hass.services.async_call(
        DOMAIN, "clear_away", {"person": person}, blocking=True
    )


async def complete(hass: HomeAssistant, sensor: str) -> None:
    """Complete the task."""
    await hass.services.async_call(
        DOMAIN, "complete_task", {"entity_id": sensor}, blocking=True
    )


# --- round robin -----------------------------------------------------------


async def test_round_robin_skips_the_person_who_is_away(hass: HomeAssistant) -> None:
    """The turn that would be Ben's goes to Cara."""
    _, sensor = await setup_task(hass)
    await away(hass, "person.ben")
    assert assignee(hass, sensor) == "person.anna"

    await complete(hass, sensor)
    assert assignee(hass, sensor) == "person.cara"

    await complete(hass, sensor)
    assert assignee(hass, sensor) == "person.anna", "continues after Cara, not Ben"


async def test_a_task_goes_to_someone_else_when_its_person_leaves(
    hass: HomeAssistant,
) -> None:
    """A task already assigned to someone who goes away is handed on."""
    _, sensor = await setup_task(hass)
    assert assignee(hass, sensor) == "person.anna"

    await away(hass, "person.anna")

    assert assignee(hass, sensor) == "person.ben"
    assert hass.states.get(sensor).attributes["away_assignees"] == ["person.anna"]


async def test_the_person_gets_the_task_back_when_they_return(
    hass: HomeAssistant,
) -> None:
    """Clearing the absence puts them back in the rotation."""
    _, sensor = await setup_task(hass)
    await away(hass, "person.anna")
    assert assignee(hass, sensor) == "person.ben"

    await back(hass, "person.anna")

    assert assignee(hass, sensor) == "person.anna"
    assert hass.states.get(sensor).attributes["away_assignees"] == []


async def test_everyone_away_keeps_the_nominal_assignee(hass: HomeAssistant) -> None:
    """A task is never left without someone responsible."""
    _, sensor = await setup_task(hass, people=["person.anna", "person.ben"])
    await away(hass, "person.anna")
    await away(hass, "person.ben")

    assert assignee(hass, sensor) == "person.anna"
    assert hass.states.get(sensor).attributes["away_assignees"] == [
        "person.anna",
        "person.ben",
    ]


# --- date range ------------------------------------------------------------


async def test_the_person_returns_after_the_end_date(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The last day away is inclusive; the next day they are back."""
    entry, sensor = await setup_task(hass)
    await away(hass, "person.anna", end="2026-11-05")
    assert assignee(hass, sensor) == "person.ben"

    freezer.move_to("2026-11-05 20:00:00+00:00")
    await refresh(hass, entry)
    assert assignee(hass, sensor) == "person.ben", "still away on the last day"

    freezer.move_to("2026-11-06 12:00:00+00:00")
    await refresh(hass, entry)
    assert assignee(hass, sensor) == "person.anna"


async def test_a_future_absence_starts_on_its_start_date(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """A planned holiday does not affect the rotation before it starts."""
    entry, sensor = await setup_task(hass)
    await away(hass, "person.anna", start="2026-11-10", end="2026-11-12")
    assert assignee(hass, sensor) == "person.anna"

    freezer.move_to("2026-11-10 12:00:00+00:00")
    await refresh(hass, entry)
    assert assignee(hass, sensor) == "person.ben"


async def test_ended_absences_are_forgotten(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Old periods do not pile up in the store."""
    entry, _ = await setup_task(hass)
    store: TaskStore = hass.data[DOMAIN]["store"]
    await away(hass, "person.anna", end="2026-11-04")
    assert "person.anna" in store.away_periods()

    freezer.move_to("2026-11-06 12:00:00+00:00")
    await refresh(hass, entry)

    assert store.away_periods() == {}


async def test_invalid_periods_are_rejected(hass: HomeAssistant) -> None:
    """The end cannot be before the start or in the past."""
    await setup_task(hass)

    with pytest.raises(ServiceValidationError):
        await away(hass, "person.anna", start="2026-11-10", end="2026-11-08")
    with pytest.raises(ServiceValidationError):
        await away(hass, "person.anna", end="2026-11-01")


# --- random ----------------------------------------------------------------


async def test_random_mode_never_picks_the_person_who_is_away(
    hass: HomeAssistant,
) -> None:
    """Everyone else still gets their turn before the next round."""
    _, sensor = await setup_task(hass, mode="random")
    await away(hass, "person.ben")
    seen = []
    for _ in range(4):
        seen.append(assignee(hass, sensor))
        await complete(hass, sensor)

    assert "person.ben" not in seen
    assert seen == ["person.anna", "person.cara", "person.anna", "person.cara"]


async def test_random_mode_hands_on_when_the_current_person_leaves(
    hass: HomeAssistant,
) -> None:
    """The person at the front of the pool goes away."""
    _, sensor = await setup_task(hass, mode="random")
    assert assignee(hass, sensor) == "person.anna"

    await away(hass, "person.anna")

    assert assignee(hass, sensor) == "person.ben"


# --- interplay -------------------------------------------------------------


async def test_undo_brings_back_the_turn_that_was_skipped_over(
    hass: HomeAssistant,
) -> None:
    """Undoing a completion restores the rotation as it was."""
    _, sensor = await setup_task(hass)
    await away(hass, "person.ben")
    await complete(hass, sensor)
    assert assignee(hass, sensor) == "person.cara"

    await hass.services.async_call(
        DOMAIN, "undo_completion", {"entity_id": sensor}, blocking=True
    )

    assert assignee(hass, sensor) == "person.anna"


async def test_the_completion_event_names_the_next_person_who_is_here(
    hass: HomeAssistant,
) -> None:
    """Automations are told about the person who is actually next."""
    from pytest_homeassistant_custom_component.common import async_capture_events

    _, sensor = await setup_task(hass)
    await away(hass, "person.ben")
    events = async_capture_events(hass, "task_completed")

    await complete(hass, sensor)
    await hass.async_block_till_done()

    assert events[0].data["next_assignee"] == "person.cara"


async def test_absences_are_stored(hass: HomeAssistant, hass_storage) -> None:
    """They survive a restart; data from before they existed still loads."""
    from custom_components.task.const import STORAGE_KEY

    store = TaskStore(hass)
    store.set_away("person.anna", datetime.date(2026, 11, 3), datetime.date(2026, 11, 9))
    store.set_away("person.ben", datetime.date(2026, 11, 3), None)
    hass_storage[STORAGE_KEY] = {"version": 1, "data": store._serialize()}

    reloaded = TaskStore(hass)
    await reloaded.async_load()
    assert reloaded.away_persons(datetime.date(2026, 11, 5)) == {"person.anna", "person.ben"}
    assert reloaded.away_persons(datetime.date(2026, 12, 1)) == {"person.ben"}

    hass_storage[STORAGE_KEY] = {"version": 1, "data": {"tasks": {}}}
    legacy = TaskStore(hass)
    await legacy.async_load()
    assert legacy.away_periods() == {}
