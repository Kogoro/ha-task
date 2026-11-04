"""Effort in points, the ranking data and the workload rotation."""

import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import Context, HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.task.const import DOMAIN, STORAGE_KEY
from custom_components.task.store import TaskStore

from .common import setup_entry, task_sensor, task_subentry

NOW = "2026-11-03 12:00:00+00:00"
USERS = {"person.anna": "uid-anna", "person.ben": "uid-ben"}


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


async def complete_as(
    hass: HomeAssistant, sensor: str, person: str, when: str | None = None
) -> None:
    """Complete a task the way a user does, so it is attributed to a person."""
    for entity_id, user_id in USERS.items():
        hass.states.async_set(entity_id, "home", {"user_id": user_id})
    data = {"entity_id": sensor}
    if when:
        data["completed_at"] = f"{when} 12:00:00+00:00"
    await hass.services.async_call(
        DOMAIN,
        "complete_task",
        data,
        blocking=True,
        context=Context(user_id=USERS[person]),
    )


def attrs(hass: HomeAssistant, sensor: str) -> dict:
    """Return the attributes of a task sensor."""
    return hass.states.get(sensor).attributes


def assignee(hass: HomeAssistant, sensor: str) -> str | None:
    """Return who is responsible."""
    return attrs(hass, sensor)["current_assignee"]


async def two_tasks(hass: HomeAssistant, mode: str = "workload"):
    """Set up a big and a small task shared by Anna and Ben."""
    people = ["person.anna", "person.ben"]
    entry = await setup_entry(
        hass,
        [
            task_subentry("big", "Big", points=5, assignees=people, rotation_mode=mode),
            task_subentry("small", "Small", assignees=people, rotation_mode=mode),
        ],
    )
    return entry, task_sensor(hass, entry, "big"), task_sensor(hass, entry, "small")


# --- points ----------------------------------------------------------------


async def test_points_default_to_one(hass: HomeAssistant) -> None:
    """A task without points counts as one."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")

    await hass.services.async_call(
        DOMAIN, "complete_task", {"entity_id": sensor}, blocking=True
    )

    assert attrs(hass, sensor)["points"] == 1
    assert attrs(hass, sensor)["recent_completions"][-1]["points"] == 1


async def test_a_completion_records_the_points_of_the_task(
    hass: HomeAssistant,
) -> None:
    """The ranking can weight completions, and the event carries the points."""
    entry = await setup_entry(hass, [task_subentry("t1", "Windows", points=8)])
    sensor = task_sensor(hass, entry, "t1")
    events = async_capture_events(hass, "task_completed")

    await hass.services.async_call(
        DOMAIN, "complete_task", {"entity_id": sensor}, blocking=True
    )
    await hass.async_block_till_done()

    assert attrs(hass, sensor)["points"] == 8
    assert attrs(hass, sensor)["recent_completions"][-1]["points"] == 8
    assert events[0].data["points"] == 8

    history = await hass.services.async_call(
        DOMAIN, "get_history", {"entity_id": sensor}, blocking=True, return_response=True
    )
    assert history["completions"][0]["points"] == 8


async def test_points_are_stored_and_old_data_counts_as_one(
    hass: HomeAssistant, hass_storage
) -> None:
    """Completions recorded before points existed count as one."""
    store = TaskStore(hass)
    store.record_completion(
        "t1", completed_at=datetime.datetime(2026, 11, 1, 12, tzinfo=datetime.UTC), points=5
    )
    hass_storage[STORAGE_KEY] = {"version": 1, "data": store._serialize()}

    reloaded = TaskStore(hass)
    await reloaded.async_load()
    assert reloaded.get_history("t1").completions[0].points == 5

    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            "tasks": {
                "t1": {
                    "last_completed": "2026-11-01T12:00:00+00:00",
                    "completions": [
                        {"completed_at": "2026-11-01T12:00:00+00:00", "completed_by": None}
                    ],
                }
            }
        },
    }
    legacy = TaskStore(hass)
    await legacy.async_load()
    assert legacy.get_history("t1").completions[0].points == 1


# --- workload rotation -----------------------------------------------------


async def test_workload_gives_the_task_to_whoever_did_least(
    hass: HomeAssistant,
) -> None:
    """After Anna did the big task, the small one goes to Ben."""
    _, big, small = await two_tasks(hass)
    assert assignee(hass, small) == "person.anna", "a tie goes to the first in the list"

    await complete_as(hass, big, "person.anna")

    assert assignee(hass, small) == "person.ben"
    assert assignee(hass, big) == "person.ben", "Anna just did it"


async def test_workload_counts_points_not_completions(hass: HomeAssistant) -> None:
    """Ben did two small tasks, but Anna's big one outweighs them."""
    _, big, small = await two_tasks(hass)
    await complete_as(hass, big, "person.anna")
    await complete_as(hass, small, "person.ben")
    await complete_as(hass, small, "person.ben")

    assert assignee(hass, small) == "person.ben", "Ben has 2 points, Anna 5"


async def test_the_assignee_does_not_change_when_others_complete_other_tasks(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Who is next for a task is fixed when the task was completed."""
    _, big, small = await two_tasks(hass)
    await complete_as(hass, big, "person.anna")
    assert assignee(hass, big) == "person.ben"

    # Ben now does a lot elsewhere; his workload passes Anna's.
    for _ in range(6):
        await complete_as(hass, small, "person.ben")

    assert assignee(hass, big) == "person.ben", "still Ben: it was decided earlier"
    await complete_as(hass, big, "person.ben")
    assert assignee(hass, big) == "person.anna", "decided again now: Anna has less"


async def test_a_tie_goes_to_whoever_did_something_longest_ago(
    hass: HomeAssistant,
) -> None:
    """With equal points the person who was last busy longer ago is next."""
    _, big, small = await two_tasks(hass)
    await complete_as(hass, small, "person.anna", when="2026-10-30")
    await complete_as(hass, small, "person.ben", when="2026-11-02")

    assert assignee(hass, big) == "person.anna"


async def test_old_work_does_not_count(hass: HomeAssistant) -> None:
    """Only the last 30 days are compared."""
    _, big, small = await two_tasks(hass)
    await complete_as(hass, big, "person.anna", when="2026-09-01")  # 5 points, 63 days ago
    await complete_as(hass, small, "person.ben", when="2026-11-02")  # 1 point, yesterday

    # Counting everything Ben would be next (1 < 5); within 30 days only he did something.
    assert assignee(hass, small) == "person.anna"


async def test_workload_skips_people_who_are_away(hass: HomeAssistant) -> None:
    """Away persons never get the task, even with the least work."""
    _, big, small = await two_tasks(hass)
    await complete_as(hass, big, "person.anna")
    assert assignee(hass, small) == "person.ben"

    await hass.services.async_call(
        DOMAIN, "set_away", {"person": "person.ben"}, blocking=True
    )

    assert assignee(hass, small) == "person.anna"


async def test_undo_restores_who_was_next(hass: HomeAssistant) -> None:
    """Undoing a completion puts back the earlier decision."""
    _, big, _small = await two_tasks(hass)
    assert assignee(hass, big) == "person.anna"
    await complete_as(hass, big, "person.anna")
    assert assignee(hass, big) == "person.ben"

    await hass.services.async_call(
        DOMAIN, "undo_completion", {"entity_id": big}, blocking=True
    )

    assert assignee(hass, big) == "person.anna"


async def test_assigning_to_me_works_in_workload_mode(hass: HomeAssistant) -> None:
    """A person can still claim a task by hand."""
    entry, _big, small = await two_tasks(hass)
    assert assignee(hass, small) == "person.anna"

    entry.runtime_data.assign_to("small", "person.ben")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert assignee(hass, small) == "person.ben"


async def test_other_rotation_modes_are_unchanged(hass: HomeAssistant) -> None:
    """Round-robin still goes round regardless of the points."""
    _, big, _small = await two_tasks(hass, mode="round_robin")
    await complete_as(hass, big, "person.anna")

    assert assignee(hass, big) == "person.ben"
    await complete_as(hass, big, "person.ben")
    assert assignee(hass, big) == "person.anna"
