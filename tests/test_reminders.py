"""Built-in reminders when a task is due soon or overdue."""

import datetime

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.task.const import DOMAIN, STORAGE_KEY
from custom_components.task.store import TaskStore

from .common import refresh, setup_entry, task_sensor, task_subentry

# 10:00 local time (the test instance runs in US/Pacific)
NOW = "2026-11-03 18:00:00+00:00"
TARGET = ["notify.phone"]


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


@pytest.fixture
def sent(hass: HomeAssistant) -> list[ServiceCall]:
    """Collect what is sent through notify.send_message."""
    return async_mock_service(hass, "notify", "send_message")


async def area(hass: HomeAssistant, tasks: list, **data):
    """Set up an area that sends reminders to a notify entity."""
    data.setdefault("reminder_targets", TARGET)
    return await setup_entry(hass, tasks, **data)


async def done(hass: HomeAssistant, entry, sid: str, days_ago: int) -> None:
    """Complete a task as it was done some days ago."""
    when = datetime.date(2026, 11, 3) - datetime.timedelta(days=days_ago)
    await hass.services.async_call(
        DOMAIN,
        "complete_task",
        {
            "entity_id": task_sensor(hass, entry, sid),
            "completed_at": f"{when} 12:00:00+00:00",
        },
        blocking=True,
    )
    await hass.async_block_till_done()


# --- when reminders are sent -----------------------------------------------


async def test_a_task_that_is_due_soon_is_reminded_once(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Entering the warn days sends one reminder, not one per update."""
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=5)  # due in 2 days

    assert len(sent) == 1
    assert sent[0].data["entity_id"] == TARGET
    assert sent[0].data["title"] == "Task due soon"
    assert "Vacuum" in sent[0].data["message"]
    assert "in 2 days" in sent[0].data["message"]

    await refresh(hass, entry)
    await refresh(hass, entry)
    assert len(sent) == 1


async def test_an_overdue_task_is_reminded(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Becoming overdue sends its own reminder."""
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=10)  # due 3 days ago

    assert len(sent) == 1
    assert sent[0].data["title"] == "Task overdue"
    assert "3 day(s) overdue" in sent[0].data["message"]


async def test_each_due_date_is_reminded_once(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """The next cycle gets a new reminder, but the same due date never repeats."""
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=5)  # due 5 Nov
    assert len(sent) == 1

    await done(hass, entry, "t1", days_ago=0)  # new due date 10 Nov: in 7 days = warn days
    assert len(sent) == 2
    assert "in 7 days" in sent[1].data["message"]

    await done(hass, entry, "t1", days_ago=0)  # same due date again
    await refresh(hass, entry)
    assert len(sent) == 2


async def test_nothing_is_sent_before_the_reminder_time(
    hass: HomeAssistant, sent: list[ServiceCall], freezer: FrozenDateTimeFactory
) -> None:
    """The reminder waits until the configured time of day."""
    freezer.move_to("2026-11-03 14:00:00+00:00")  # 06:00 local
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=5)
    assert sent == []

    freezer.move_to("2026-11-03 17:30:00+00:00")  # 09:30 local
    await refresh(hass, entry)
    assert len(sent) == 1


async def test_a_custom_reminder_time(
    hass: HomeAssistant, sent: list[ServiceCall], freezer: FrozenDateTimeFactory
) -> None:
    """The time is configurable."""
    entry = await area(hass, [task_subentry("t1", "Vacuum")], reminder_time="12:00:00")
    await done(hass, entry, "t1", days_ago=5)
    assert sent == [], "10:00 is before 12:00"

    freezer.move_to("2026-11-03 21:00:00+00:00")  # 13:00 local
    await refresh(hass, entry)
    assert len(sent) == 1


async def test_it_survives_a_restart_without_repeating(
    hass: HomeAssistant, sent: list[ServiceCall], hass_storage
) -> None:
    """What was reminded is stored."""
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=5)
    assert len(sent) == 1

    store: TaskStore = hass.data[DOMAIN]["store"]
    hass_storage[STORAGE_KEY] = {"version": 1, "data": store._serialize()}
    reloaded = TaskStore(hass)
    await reloaded.async_load()
    due = datetime.date(2026, 11, 5)
    assert reloaded.reminder_sent("t1", "due_soon", due)
    assert not reloaded.reminder_sent("t1", "due_soon", datetime.date(2026, 11, 12))

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(sent) == 1


async def test_old_data_without_reminders_loads(hass: HomeAssistant, hass_storage) -> None:
    """Storage from before reminders existed still loads."""
    hass_storage[STORAGE_KEY] = {"version": 1, "data": {"tasks": {}}}
    store = TaskStore(hass)
    await store.async_load()

    assert not store.reminder_sent("t1", "overdue", datetime.date(2026, 11, 3))


# --- what is not sent ------------------------------------------------------


async def test_no_target_means_no_reminders(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Areas that do not configure reminders are unchanged."""
    entry = await setup_entry(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=10)

    assert sent == []


async def test_the_kinds_can_be_turned_off(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Only the chosen kinds are sent."""
    entry = await area(
        hass,
        [task_subentry("soon", "Soon"), task_subentry("late", "Late")],
        reminder_due_soon=False,
    )
    await done(hass, entry, "soon", days_ago=5)
    await done(hass, entry, "late", days_ago=10)

    assert [c.data["title"] for c in sent] == ["Task overdue"]


async def test_a_task_can_opt_out(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """A task with reminders turned off is never reminded."""
    entry = await area(
        hass,
        [task_subentry("t1", "Quiet", reminders=False), task_subentry("t2", "Loud")],
    )
    await done(hass, entry, "t1", days_ago=10)
    await done(hass, entry, "t2", days_ago=10)

    assert len(sent) == 1
    assert "Loud" in sent[0].data["message"]


async def test_a_task_that_was_never_completed_is_not_reminded(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """New tasks are overdue at once; that must not send a flood."""
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await refresh(hass, entry)

    assert sent == []


# --- grouping --------------------------------------------------------------


async def test_a_summary_covers_everything_that_was_pending(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Five overdue at once, e.g. after turning reminders on, are one message."""
    tasks = [task_subentry(f"t{i}", f"Task {i}") for i in range(5)]
    entry = await setup_entry(hass, tasks)
    for i in range(5):
        await done(hass, entry, f"t{i}", days_ago=10)
    assert sent == []

    # turn reminders on for the area afterwards
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "reminder_targets": TARGET}
    )
    await hass.async_block_till_done()

    assert len(sent) == 1
    assert sent[0].data["title"] == "5 tasks overdue"
    assert "Task 0" in sent[0].data["message"]
    await refresh(hass, entry)
    assert len(sent) == 1


async def test_a_few_reminders_are_sent_one_by_one(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Up to three stay individual messages."""
    tasks = [task_subentry(f"t{i}", f"Task {i}") for i in range(3)]
    entry = await setup_entry(hass, tasks)
    for i in range(3):
        await done(hass, entry, f"t{i}", days_ago=10)
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "reminder_targets": TARGET}
    )
    await hass.async_block_till_done()

    assert len(sent) == 3


# --- targets and texts -----------------------------------------------------


async def test_a_classic_notify_service_works_too(hass: HomeAssistant) -> None:
    """A notify.* service can be used instead of (or besides) entities."""
    legacy = async_mock_service(hass, "notify", "mobile_test")
    entry = await setup_entry(
        hass,
        [task_subentry("t1", "Vacuum")],
        reminder_service="notify.mobile_test",
    )
    await done(hass, entry, "t1", days_ago=10)

    assert len(legacy) == 1
    assert legacy[0].data["title"] == "Task overdue"
    assert "entity_id" not in legacy[0].data


async def test_the_message_names_the_person_responsible(
    hass: HomeAssistant, sent: list[ServiceCall]
) -> None:
    """Whoever is assigned is mentioned."""
    hass.states.async_set("person.anna", "home", {"friendly_name": "Anna"})
    entry = await area(
        hass, [task_subentry("t1", "Vacuum", assignees=["person.anna"])]
    )
    await done(hass, entry, "t1", days_ago=10)

    assert "Assigned to Anna" in sent[0].data["message"]


async def test_german_texts(hass: HomeAssistant, sent: list[ServiceCall]) -> None:
    """The texts follow the language of the instance."""
    hass.config.language = "de"
    entry = await area(hass, [task_subentry("t1", "Staubsaugen")])
    await done(hass, entry, "t1", days_ago=10)

    assert sent[0].data["title"] == "Aufgabe überfällig"
    assert "seit 3 Tag(en) überfällig" in sent[0].data["message"]


async def test_a_failing_target_does_not_break_updates_and_is_retried(
    hass: HomeAssistant,
) -> None:
    """If sending fails the task is not marked as reminded."""
    calls: list[ServiceCall] = []
    broken = {"on": True}

    async def handler(call: ServiceCall) -> None:
        calls.append(call)
        if broken["on"]:
            raise HomeAssistantError("phone unreachable")

    hass.services.async_register("notify", "send_message", handler)
    entry = await area(hass, [task_subentry("t1", "Vacuum")])
    await done(hass, entry, "t1", days_ago=10)
    assert len(calls) == 1
    assert hass.states.get(task_sensor(hass, entry, "t1")).state == "-3"

    broken["on"] = False
    await refresh(hass, entry)
    assert len(calls) == 2, "retried on the next update"
    await refresh(hass, entry)
    assert len(calls) == 2, "and not again once it worked"
