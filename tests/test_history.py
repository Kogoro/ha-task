"""Undoing a completion and the completion history."""

import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.task.const import DOMAIN
from custom_components.task.store import TaskStore

from .common import setup_entry, task_sensor, task_subentry

NOW = "2026-11-03 12:00:00+00:00"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


async def call(hass: HomeAssistant, service: str, entity: str, **data):
    """Call a task service and return its response, if any."""
    return await hass.services.async_call(
        DOMAIN,
        service,
        {"entity_id": entity, **data},
        blocking=True,
        return_response=service == "get_history",
    )


async def complete_at(hass: HomeAssistant, entity: str, when: str | None = None) -> None:
    """Complete a task, optionally at a given UTC time like "2026-10-30"."""
    data = {"completed_at": f"{when} 12:00:00+00:00"} if when else {}
    await call(hass, "complete_task", entity, **data)


def attrs(hass: HomeAssistant, entity: str) -> dict:
    """Return the attributes of a task sensor."""
    return hass.states.get(entity).attributes


# --- undo ------------------------------------------------------------------


async def test_undo_removes_the_last_completion(hass: HomeAssistant) -> None:
    """The previous completion becomes the last one again."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor, "2026-10-31")
    await complete_at(hass, sensor)
    assert hass.states.get(sensor).state == "7"

    await call(hass, "undo_completion", sensor)

    state = hass.states.get(sensor)
    assert state.state == "4", "due date counts from the earlier completion again"
    assert state.attributes["total_completions"] == 1
    assert state.attributes["can_undo"] is False


async def test_undo_the_only_completion_makes_the_task_new_again(
    hass: HomeAssistant,
) -> None:
    """A task that was never completed is due immediately."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor)

    await call(hass, "undo_completion", sensor)

    state = hass.states.get(sensor)
    assert state.state == "0"
    assert state.attributes["total_completions"] == 0
    assert state.attributes["last_completed"] is None


async def test_undo_restores_who_is_responsible(hass: HomeAssistant) -> None:
    """The rotation steps back to the person who was up."""
    entry = await setup_entry(
        hass,
        [
            task_subentry(
                "t1",
                "Vacuum",
                assignees=["person.anna", "person.ben"],
                rotation_mode="round_robin",
            )
        ],
    )
    sensor = task_sensor(hass, entry, "t1")
    assert attrs(hass, sensor)["current_assignee"] == "person.anna"

    await complete_at(hass, sensor)
    assert attrs(hass, sensor)["current_assignee"] == "person.ben"

    await call(hass, "undo_completion", sensor)
    assert attrs(hass, sensor)["current_assignee"] == "person.anna"


async def test_undo_restores_a_postponement(hass: HomeAssistant) -> None:
    """Completing cleared the postponement; undoing brings it back."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await call(hass, "postpone_task", sensor, days=5)
    assert hass.states.get(sensor).state == "5"
    await complete_at(hass, sensor)
    assert hass.states.get(sensor).state == "7"

    await call(hass, "undo_completion", sensor)

    assert hass.states.get(sensor).state == "5"


async def test_undo_works_only_once(hass: HomeAssistant) -> None:
    """Only the most recently recorded completion can be undone."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor, "2026-10-30")
    await complete_at(hass, sensor)
    await call(hass, "undo_completion", sensor)

    with pytest.raises(ServiceValidationError):
        await call(hass, "undo_completion", sensor)
    assert attrs(hass, sensor)["total_completions"] == 1


async def test_nothing_to_undo_on_a_new_task(hass: HomeAssistant) -> None:
    """There is nothing to undo before anything was recorded."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])

    with pytest.raises(ServiceValidationError):
        await call(hass, "undo_completion", task_sensor(hass, entry, "t1"))


async def test_no_undo_after_a_reset(hass: HomeAssistant) -> None:
    """Resetting a task clears the history, including the undo step."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor)
    await call(hass, "reset_task", sensor)

    with pytest.raises(ServiceValidationError):
        await call(hass, "undo_completion", sensor)


async def test_undo_fires_an_event(hass: HomeAssistant) -> None:
    """Automations can react to a completion being undone."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor, "2026-11-01")
    events = async_capture_events(hass, "task_completion_undone")

    await call(hass, "undo_completion", sensor)
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["task_name"] == "Vacuum"
    assert events[0].data["completed_at"].startswith("2026-11-01T12:00:00")


async def test_undo_card_attribute_points_at_the_recorded_completion(
    hass: HomeAssistant,
) -> None:
    """The card puts its undo button on the completion that would be undone."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor, "2026-11-01")

    state = hass.states.get(sensor)
    assert state.attributes["undo_completed_at"] == (
        state.attributes["recent_completions"][-1]["completed_at"]
    )


async def test_undo_step_is_stored_and_survives_a_restart(
    hass: HomeAssistant, hass_storage
) -> None:
    """The snapshot is persisted; data from before it existed still loads."""
    from custom_components.task.const import STORAGE_KEY

    store = TaskStore(hass)
    history = store.get_history("t1")
    history.current_assignee_index = 1
    history.postponed_until = datetime.date(2026, 12, 1)
    store.record_completion(
        "t1", completed_at=datetime.datetime(2026, 11, 1, 12, tzinfo=datetime.UTC)
    )
    hass_storage[STORAGE_KEY] = {"version": 1, "data": store._serialize()}

    reloaded = TaskStore(hass)
    await reloaded.async_load()
    assert reloaded.undo_last_completion("t1") is not None
    restored = reloaded.get_history("t1")
    assert restored.completions == []
    assert restored.current_assignee_index == 1
    assert restored.postponed_until == datetime.date(2026, 12, 1)

    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {"tasks": {"t1": {"completions": [], "last_completed": None}}},
    }
    legacy = TaskStore(hass)
    await legacy.async_load()
    assert legacy.get_history("t1").undo is None
    assert legacy.undo_last_completion("t1") is None


# --- history and statistics ------------------------------------------------


async def test_cycle_statistics(hass: HomeAssistant) -> None:
    """Actual cycle lengths are compared with the planned interval."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum", interval_days=7)])
    sensor = task_sensor(hass, entry, "t1")
    for day in ("2026-10-14", "2026-10-24", "2026-10-30", "2026-11-03"):
        await complete_at(hass, sensor, day)

    a = attrs(hass, sensor)
    assert a["last_cycle_days"] == 4.0
    assert a["average_cycle_days"] == 6.7  # (10 + 6 + 4) / 3
    assert a["on_time_percent"] == 67  # 6 and 4 within 7 days, 10 is not


async def test_no_statistics_before_two_completions(hass: HomeAssistant) -> None:
    """One completion has no cycle yet."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete_at(hass, sensor)

    a = attrs(hass, sensor)
    assert a["average_cycle_days"] is None
    assert a["last_cycle_days"] is None
    assert a["on_time_percent"] is None


async def test_get_history_returns_newest_first(hass: HomeAssistant) -> None:
    """The service returns the history without it living in the attributes."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum", interval_days=7)])
    sensor = task_sensor(hass, entry, "t1")
    for day in ("2026-10-24", "2026-10-30", "2026-11-03"):
        await complete_at(hass, sensor, day)

    response = await call(hass, "get_history", sensor)

    assert response["task"] == "Vacuum"
    assert response["interval_days"] == 7
    assert response["total_completions"] == 3
    assert [c["days_since_previous"] for c in response["completions"]] == [4.0, 6.0, None]
    assert response["completions"][0]["completed_at"].startswith("2026-11-03")
    assert response["on_time_percent"] == 100


async def test_get_history_limit(hass: HomeAssistant) -> None:
    """Only the newest completions are returned when a limit is given."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    for day in ("2026-10-24", "2026-10-30", "2026-11-03"):
        await complete_at(hass, sensor, day)

    response = await call(hass, "get_history", sensor, limit=2)

    assert len(response["completions"]) == 2
    assert response["total_completions"] == 3


async def test_history_services_reject_other_entities(hass: HomeAssistant) -> None:
    """They only work for the task entities of this integration."""
    await setup_entry(hass, [task_subentry("t1", "Vacuum")])

    with pytest.raises(ServiceValidationError):
        await call(hass, "get_history", "sensor.does_not_exist")
    with pytest.raises(ServiceValidationError):
        await call(hass, "undo_completion", "sensor.does_not_exist")
