"""Due dates, completion, postponing, status and summary sensors."""

import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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


async def complete(hass: HomeAssistant, entity: str, **data) -> None:
    """Call task.complete_task."""
    await hass.services.async_call(
        DOMAIN, "complete_task", {"entity_id": entity, **data}, blocking=True
    )


async def postpone(hass: HomeAssistant, entity: str, **data) -> None:
    """Call task.postpone_task."""
    await hass.services.async_call(
        DOMAIN, "postpone_task", {"entity_id": entity, **data}, blocking=True
    )


async def test_new_task_is_overdue(hass: HomeAssistant) -> None:
    """A task that was never completed is due immediately."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])

    assert hass.states.get(task_sensor(hass, entry, "t1")).state == "0"
    assert hass.states.get(status_sensor(hass, entry, "t1")).state == "overdue"


async def test_complete_starts_the_interval(hass: HomeAssistant) -> None:
    """Completing sets the next due date one interval ahead."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum", interval_days=10)])
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor)

    state = hass.states.get(sensor)
    assert state.state == "10"
    assert state.attributes["overdue"] is False
    assert state.attributes["total_completions"] == 1


async def test_complete_with_past_date(hass: HomeAssistant) -> None:
    """The next due date counts from completed_at."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor, completed_at="2026-10-31 12:00:00")

    assert hass.states.get(sensor).state == "4"


async def test_complete_with_date_only(hass: HomeAssistant) -> None:
    """A plain date is accepted."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor, completed_at="2026-11-01")

    assert hass.states.get(sensor).state == "5"


async def test_complete_in_the_future_is_rejected(hass: HomeAssistant) -> None:
    """A completion cannot lie in the future."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")

    with pytest.raises(ServiceValidationError):
        await complete(hass, sensor, completed_at="2026-11-10 12:00:00")

    assert hass.states.get(sensor).attributes["total_completions"] == 0


async def test_older_completion_does_not_move_due_date_back(
    hass: HomeAssistant,
) -> None:
    """Backdating an extra completion keeps the latest one authoritative."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")

    await complete(hass, sensor)
    await complete(hass, sensor, completed_at="2026-10-20 12:00:00")

    state = hass.states.get(sensor)
    assert state.state == "7"
    assert state.attributes["total_completions"] == 2
    recent = state.attributes["recent_completions"]
    assert [c["completed_at"] for c in recent] == sorted(
        c["completed_at"] for c in recent
    )


async def test_completed_event_uses_the_given_time(hass: HomeAssistant) -> None:
    """The event reports the backdated completion and the next due date."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    events = async_capture_events(hass, "task_completed")

    await complete(
        hass, task_sensor(hass, entry, "t1"), completed_at="2026-10-31 12:00:00+00:00"
    )
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["completed_at"].startswith("2026-10-31T12:00:00")
    assert events[0].data["next_due"] == "2026-11-07"


async def test_postpone_pushes_the_due_date(hass: HomeAssistant) -> None:
    """Postponing counts from the current due date and keeps the history."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete(hass, sensor)

    await postpone(hass, sensor, days=2)

    state = hass.states.get(sensor)
    assert state.state == "9"
    assert state.attributes["total_completions"] == 1

    await postpone(hass, sensor)
    assert hass.states.get(sensor).state == "10"


async def test_postpone_an_overdue_task_counts_from_today(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """An overdue task is pushed back from today, not from its old date."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await complete(hass, sensor)
    freezer.tick(datetime.timedelta(days=10))
    await refresh(hass, entry)
    assert hass.states.get(sensor).state == "-3"

    await postpone(hass, sensor, days=3)

    state = hass.states.get(sensor)
    assert state.state == "3"
    assert state.attributes["overdue"] is False


async def test_postpone_a_new_task(hass: HomeAssistant) -> None:
    """A task that was never completed can be postponed too."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")

    await postpone(hass, sensor, days=3)

    assert hass.states.get(sensor).state == "3"
    assert hass.states.get(status_sensor(hass, entry, "t1")).state == "due_soon"


async def test_completion_clears_a_postponement(hass: HomeAssistant) -> None:
    """The next completion starts a normal interval again."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    sensor = task_sensor(hass, entry, "t1")
    await postpone(hass, sensor, days=30)

    await complete(hass, sensor)

    assert hass.states.get(sensor).state == "7"


async def test_postponement_survives_a_restart(hass: HomeAssistant, hass_storage) -> None:
    """The postponed date is stored and loaded again."""
    from custom_components.task.const import STORAGE_KEY
    from custom_components.task.store import TaskStore

    store = TaskStore(hass)
    store.postpone("t1", datetime.date(2026, 12, 1))
    hass_storage[STORAGE_KEY] = {"version": 1, "data": store._serialize()}

    reloaded = TaskStore(hass)
    await reloaded.async_load()

    assert reloaded.get_history("t1").postponed_until == datetime.date(2026, 12, 1)


async def test_store_without_postponement_still_loads(
    hass: HomeAssistant, hass_storage
) -> None:
    """Data written before postponing existed loads without it."""
    from custom_components.task.const import STORAGE_KEY
    from custom_components.task.store import TaskStore

    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "data": {
            "tasks": {
                "t1": {
                    "last_completed": "2026-11-01T10:00:00+00:00",
                    "completions": [
                        {"completed_at": "2026-11-01T10:00:00+00:00", "completed_by": None}
                    ],
                }
            }
        },
    }
    store = TaskStore(hass)
    await store.async_load()

    history = store.get_history("t1")
    assert history.postponed_until is None
    assert len(history.completions) == 1


async def test_status_follows_the_warn_days(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """ok -> due_soon -> overdue as the due date approaches and passes."""
    entry = await setup_entry(
        hass, [task_subentry("t1", "Vacuum")], warn_days=3
    )
    status = status_sensor(hass, entry, "t1")
    await complete(hass, task_sensor(hass, entry, "t1"))
    assert hass.states.get(status).state == "ok"

    freezer.tick(datetime.timedelta(days=4))
    await refresh(hass, entry)
    assert hass.states.get(status).state == "due_soon"
    assert hass.states.get(status).attributes["warn_days"] == 3

    freezer.tick(datetime.timedelta(days=4))
    await refresh(hass, entry)
    assert hass.states.get(status).state == "overdue"


async def test_task_warn_days_override_the_area(hass: HomeAssistant) -> None:
    """A task's own warn days win over the area's value."""
    entry = await setup_entry(
        hass,
        [
            task_subentry("t1", "Vacuum"),
            task_subentry("t2", "Windows", warn_days=2),
            task_subentry("t3", "Floors", warn_days=14),
        ],
        warn_days=7,
    )
    for subentry in ("t1", "t2", "t3"):
        await complete(hass, task_sensor(hass, entry, subentry))

    assert hass.states.get(status_sensor(hass, entry, "t1")).state == "due_soon"
    assert hass.states.get(status_sensor(hass, entry, "t2")).state == "ok"
    assert hass.states.get(status_sensor(hass, entry, "t3")).state == "due_soon"
    assert hass.states.get(status_sensor(hass, entry, "t2")).attributes["warn_days"] == 2


async def test_area_without_warn_days_uses_the_default(hass: HomeAssistant) -> None:
    """Entries created before warn days existed use 7 days."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    await complete(hass, task_sensor(hass, entry, "t1"))

    status = hass.states.get(status_sensor(hass, entry, "t1"))
    assert status.attributes["warn_days"] == 7
    assert status.state == "due_soon"


async def test_summary_sensors(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """The area sensors count tasks and list their names."""
    entry = await setup_entry(
        hass,
        [
            task_subentry("t1", "Overdue one"),
            task_subentry("t2", "Due today", interval_days=7),
            task_subentry("t3", "Later", interval_days=30),
            task_subentry("t4", "This week", interval_days=10),
        ],
        warn_days=1,
    )
    await complete(hass, task_sensor(hass, entry, "t2"))
    await complete(hass, task_sensor(hass, entry, "t3"))
    await complete(hass, task_sensor(hass, entry, "t4"))
    freezer.tick(datetime.timedelta(days=7))
    await refresh(hass, entry)

    def sensor(key: str):
        return hass.states.get(entity_id(hass, entry, "sensor", key))

    assert sensor("overdue_count").state == "1"
    assert sensor("overdue_count").attributes["tasks"] == ["Overdue one"]
    assert sensor("due_today").state == "1"
    assert sensor("due_today").attributes["tasks"] == ["Due today"]
    assert sensor("due_this_week").state == "2"
    assert sensor("due_soon").state == "1"


async def test_due_soon_event_fires_once_per_due_date(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Entering the warn window fires the event a single time."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")], warn_days=2)
    events = async_capture_events(hass, "task_due_soon")
    await complete(hass, task_sensor(hass, entry, "t1"))
    await hass.async_block_till_done()
    assert events == []

    freezer.tick(datetime.timedelta(days=5))
    await refresh(hass, entry)
    await refresh(hass, entry)

    assert len(events) == 1
    assert events[0].data["task_name"] == "Vacuum"
    assert events[0].data["next_due"] == "2026-11-10"
