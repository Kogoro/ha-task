"""Exporting and importing the configuration."""

import json
from pathlib import Path

import pytest
import voluptuous as vol
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.task.const import DOMAIN

from .common import entity_id, setup_entry, task_sensor, task_subentry

NOW = "2026-11-03 12:00:00+00:00"


@pytest.fixture(autouse=True)
def frozen_time(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    """Run every test at a fixed time."""
    freezer.move_to(NOW)
    return freezer


async def export(hass: HomeAssistant, **data) -> dict:
    """Call task.export_config."""
    return await hass.services.async_call(
        DOMAIN, "export_config", data, blocking=True, return_response=True
    )


async def import_(hass: HomeAssistant, data=None, **extra) -> dict:
    """Call task.import_config."""
    payload = dict(extra)
    if data is not None:
        payload["data"] = data
    response = await hass.services.async_call(
        DOMAIN, "import_config", payload, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return response


def area_entries(hass: HomeAssistant) -> list:
    """Return the area config entries."""
    return [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get("entry_type") != "household"
    ]


def device(hass: HomeAssistant, name: str = "Dishwasher") -> dr.DeviceEntry:
    """Create a device to attach maintenance to."""
    owner = MockConfigEntry(domain="other")
    owner.add_to_hass(hass)
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("other", name)}, name=name
    )


@pytest.fixture(autouse=True)
async def component(hass: HomeAssistant) -> None:
    """The services exist once the integration is set up (as soon as it has an entry)."""
    assert await async_setup_component(hass, DOMAIN, {})


@pytest.fixture
def kitchen(hass: HomeAssistant) -> str:
    """Create the Kitchen area."""
    return ar.async_get(hass).async_create("Kitchen").id


async def full_setup(hass: HomeAssistant, kitchen: str):
    """A kitchen with a rich task and a maintenance item."""
    dishwasher = device(hass)
    entry = await setup_entry(
        hass,
        [
            task_subentry(
                "t1",
                "Windows",
                interval_value=2,
                interval_unit="weeks",
                active_months=[3, 4, 5],
                points=5,
                description="Inside and out",
                icon="mdi:window-closed",
                assignees=["person.anna", "person.ben"],
                rotation_mode="workload",
                warn_days=3,
                reminders=False,
            ),
            {
                "subentry_type": "maintenance",
                "title": "Descale",
                "subentry_id": "m1",
                "unique_id": None,
                "data": {"interval_days": 90, "device_id": dishwasher.id},
            },
        ],
        area_id=kitchen,
        warn_days=5,
        reminder_service="notify.mobile_app_pixel",
        reminder_time="07:30:00",
    )
    return entry, dishwasher


# --- export ----------------------------------------------------------------


async def test_export_has_everything_needed_to_recreate_the_tasks(
    hass: HomeAssistant, kitchen: str
) -> None:
    """Areas, their settings, tasks and maintenance, but no history by default."""
    await full_setup(hass, kitchen)

    data = await export(hass)

    assert data["version"] == 1
    assert len(data["areas"]) == 1
    area = data["areas"][0]
    assert area["area_id"] == kitchen
    assert area["area_name"] == "Kitchen"
    assert area["settings"]["warn_days"] == 5
    assert area["settings"]["reminder_service"] == "notify.mobile_app_pixel"
    tasks = {t["name"]: t for t in area["tasks"]}
    windows = tasks["Windows"]
    assert windows["type"] == "task"
    assert windows["interval_value"] == 2
    assert windows["interval_unit"] == "weeks"
    assert windows["active_months"] == [3, 4, 5]
    assert windows["points"] == 5
    assert windows["assignees"] == ["person.anna", "person.ben"]
    assert windows["rotation_mode"] == "workload"
    assert windows["warn_days"] == 3
    assert windows["reminders"] is False
    assert windows["description"] == "Inside and out"
    descale = tasks["Descale"]
    assert descale["type"] == "maintenance"
    assert descale["interval_value"] == 90
    assert descale["device_name"] == "Dishwasher"
    assert all("completions" not in t for t in area["tasks"])


async def test_export_can_include_the_history(
    hass: HomeAssistant, kitchen: str
) -> None:
    """History is optional."""
    entry, _ = await full_setup(hass, kitchen)
    await hass.services.async_call(
        DOMAIN,
        "complete_task",
        {
            "entity_id": task_sensor(hass, entry, "t1"),
            "completed_at": "2026-10-30 12:00:00+00:00",
        },
        blocking=True,
    )

    data = await export(hass, include_history=True)

    windows = next(t for t in data["areas"][0]["tasks"] if t["name"] == "Windows")
    assert [c["completed_at"][:10] for c in windows["completions"]] == ["2026-10-30"]
    assert windows["completions"][0]["points"] == 5


async def test_export_includes_the_household(hass: HomeAssistant, kitchen: str) -> None:
    """The household entry's calendar name travels along."""
    await full_setup(hass, kitchen)
    household = MockConfigEntry(
        domain=DOMAIN,
        unique_id="household",
        data={"entry_type": "household", "calendar_name": "Everything"},
    )
    household.add_to_hass(hass)
    await hass.config_entries.async_setup(household.entry_id)
    await hass.async_block_till_done()

    data = await export(hass)

    assert data["household"] == {"calendar_name": "Everything"}
    assert len(data["areas"]) == 1


# --- round trip ------------------------------------------------------------


async def test_what_is_exported_can_be_imported_again(
    hass: HomeAssistant, kitchen: str
) -> None:
    """Remove the area, import the export, and the export is the same."""
    entry, _ = await full_setup(hass, kitchen)
    before = await export(hass)
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert area_entries(hass) == []

    result = await import_(hass, before)

    assert result["areas_created"] == ["Kitchen"]
    assert result["tasks_created"] == 2
    after = await export(hass)
    before.pop("exported_at")
    after.pop("exported_at")
    assert after == before


async def test_imported_tasks_work(hass: HomeAssistant, kitchen: str) -> None:
    """They become entities with the imported interval and season."""
    entry, _ = await full_setup(hass, kitchen)
    data = await export(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    await import_(hass, data)

    new = area_entries(hass)[0]
    windows = next(s for s in new.subentries.values() if s.title == "Windows")
    sensor = task_sensor(hass, new, windows.subentry_id)
    attrs = hass.states.get(sensor).attributes
    assert attrs["interval_unit"] == "weeks"
    assert attrs["active_months"] == [3, 4, 5]
    assert attrs["points"] == 5
    assert attrs["warn_days"] == 3 if "warn_days" in attrs else True
    assert new.data["warn_days"] == 5
    assert new.data["reminder_time"] == "07:30:00"
    assert new.unique_id == kitchen
    assert new.title == "Kitchen"


async def test_history_is_restored_when_it_is_in_the_export(
    hass: HomeAssistant, kitchen: str
) -> None:
    """Completions come back and the due date follows from them."""
    entry, _ = await full_setup(hass, kitchen)
    await hass.services.async_call(
        DOMAIN,
        "complete_task",
        {
            "entity_id": task_sensor(hass, entry, "t1"),
            "completed_at": "2026-10-30 12:00:00+00:00",
        },
        blocking=True,
    )
    data = await export(hass, include_history=True)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    await import_(hass, data)

    new = area_entries(hass)[0]
    windows = next(s for s in new.subentries.values() if s.title == "Windows")
    attrs = hass.states.get(task_sensor(hass, new, windows.subentry_id)).attributes
    assert attrs["total_completions"] == 1
    assert attrs["last_completed"].startswith("2026-10-30")


# --- duplicates, dry run, existing data ------------------------------------


async def test_importing_twice_creates_nothing_the_second_time(
    hass: HomeAssistant, kitchen: str
) -> None:
    """Tasks with the same type and name in the same area are skipped."""
    await full_setup(hass, kitchen)
    data = await export(hass)

    result = await import_(hass, data)

    assert result["tasks_created"] == 0
    assert sorted(result["tasks_skipped"]) == ["Kitchen: Descale", "Kitchen: Windows"]
    assert len(area_entries(hass)[0].subentries) == 2


async def test_names_are_compared_without_regard_to_case(
    hass: HomeAssistant, kitchen: str
) -> None:
    """"windows" is the same task as "Windows"."""
    await full_setup(hass, kitchen)

    result = await import_(
        hass,
        {"version": 1, "areas": [{"area_id": kitchen, "tasks": [{"name": "windows"}]}]},
    )

    assert result["tasks_created"] == 0
    assert result["tasks_skipped"] == ["Kitchen: windows"]


async def test_an_existing_area_gets_the_new_tasks_and_keeps_its_settings(
    hass: HomeAssistant, kitchen: str
) -> None:
    """Only what is missing is added; settings stay as they are."""
    entry, _ = await full_setup(hass, kitchen)

    result = await import_(
        hass,
        {
            "version": 1,
            "areas": [
                {
                    "area_id": kitchen,
                    "settings": {"warn_days": 1},
                    "tasks": [{"name": "Wipe counters", "interval_value": 3}],
                }
            ],
        },
    )

    assert result["tasks_created"] == 1
    assert entry.data["warn_days"] == 5
    assert "Wipe counters" in [s.title for s in entry.subentries.values()]


async def test_a_dry_run_changes_nothing(hass: HomeAssistant, kitchen: str) -> None:
    """It reports what would happen."""
    entry, _ = await full_setup(hass, kitchen)
    data = await export(hass)
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    result = await import_(hass, data, dry_run=True)

    assert result["dry_run"] is True
    assert result["areas_created"] == ["Kitchen"]
    assert result["tasks_created"] == 2
    assert area_entries(hass) == []


async def test_household_is_created_when_missing_and_not_duplicated(
    hass: HomeAssistant, kitchen: str
) -> None:
    """An imported household entry is created once."""
    data = {"version": 1, "household": {"calendar_name": "Everything"}, "areas": []}

    first = await import_(hass, data)
    second = await import_(hass, data)

    households = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get("entry_type") == "household"
    ]
    assert first["household_created"] is True
    assert second["household_created"] is False
    assert len(households) == 1
    assert households[0].data["calendar_name"] == "Everything"


# --- validation ------------------------------------------------------------


async def test_an_invalid_file_changes_nothing_and_lists_the_problems(
    hass: HomeAssistant, kitchen: str
) -> None:
    """All problems are reported together, with where they are."""
    bad = {
        "version": 1,
        "areas": [
            {
                "area_id": kitchen,
                "tasks": [
                    {"name": "Fine"},
                    {"name": "Zero", "interval_value": 0},
                    {"name": "Unit", "interval_unit": "fortnights"},
                    {"name": "Months", "active_months": [13]},
                    {"name": "Person", "assignees": ["light.kitchen"]},
                    {"interval_value": 3},
                    {"name": "Typo", "intervall_value": 3},
                ],
            }
        ],
    }

    with pytest.raises(ServiceValidationError) as err:
        await import_(hass, bad)

    message = str(err.value)
    for expected in (
        "areas[0].tasks[1].interval_value",
        "areas[0].tasks[2].interval_unit",
        "areas[0].tasks[3].active_months[0]",
        "areas[0].tasks[4].assignees[0]",
        "areas[0].tasks[5].name",
        "areas[0].tasks[6].intervall_value",
    ):
        assert expected in message, expected
    assert area_entries(hass) == [], "nothing was created, not even the valid task"


async def test_an_unknown_version_is_refused(hass: HomeAssistant) -> None:
    """A file from a future format is not guessed at."""
    with pytest.raises(ServiceValidationError) as err:
        await import_(hass, {"version": 99, "areas": []})

    assert "version" in str(err.value)


async def test_the_data_must_be_an_export(hass: HomeAssistant) -> None:
    """Something else entirely is reported, not crashed on."""
    with pytest.raises(ServiceValidationError):
        await import_(hass, {"hello": "world"})


async def test_an_area_that_does_not_exist_is_reported(hass: HomeAssistant) -> None:
    """The area has to exist in Home Assistant first."""
    with pytest.raises(ServiceValidationError) as err:
        await import_(
            hass,
            {"version": 1, "areas": [{"area_id": "attic", "area_name": "Attic", "tasks": []}]},
        )

    assert "Attic" in str(err.value)
    assert "Settings > Areas" in str(err.value)


async def test_an_area_is_found_by_name_when_the_id_differs(
    hass: HomeAssistant, kitchen: str
) -> None:
    """On another instance the same room has another ID."""
    await import_(
        hass,
        {
            "version": 1,
            "areas": [
                {
                    "area_id": "some_other_id",
                    "area_name": "KITCHEN",
                    "tasks": [{"name": "Wipe counters"}],
                }
            ],
        },
    )

    assert area_entries(hass)[0].unique_id == kitchen


async def test_a_maintenance_device_is_found_by_name(
    hass: HomeAssistant, kitchen: str
) -> None:
    """The device ID differs between instances; the name still matches."""
    dishwasher = device(hass)

    await import_(
        hass,
        {
            "version": 1,
            "areas": [
                {
                    "area_id": kitchen,
                    "tasks": [
                        {
                            "name": "Descale",
                            "type": "maintenance",
                            "device_id": "not-this-instance",
                            "device_name": "dishwasher",
                        }
                    ],
                }
            ],
        },
    )

    sub = next(iter(area_entries(hass)[0].subentries.values()))
    assert sub.data["device_id"] == dishwasher.id


async def test_a_maintenance_item_without_its_device_is_reported(
    hass: HomeAssistant, kitchen: str
) -> None:
    """It cannot be created without a device."""
    with pytest.raises(ServiceValidationError) as err:
        await import_(
            hass,
            {
                "version": 1,
                "areas": [
                    {
                        "area_id": kitchen,
                        "tasks": [
                            {"name": "Descale", "type": "maintenance", "device_name": "Nope"}
                        ],
                    }
                ],
            },
        )

    assert "Descale" in str(err.value)
    assert "device" in str(err.value)


# --- files -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["task_export.json", "task_export.yaml"])
async def test_export_to_a_file_and_import_from_it(
    hass: HomeAssistant, kitchen: str, name: str
) -> None:
    """JSON and YAML, chosen by the extension."""
    entry, _ = await full_setup(hass, kitchen)

    response = await export(hass, filename=name)
    path = Path(response["file"])
    assert path.exists()
    assert path.name == name
    if name.endswith(".json"):
        assert json.loads(path.read_text())["version"] == 1
    else:
        assert "version: 1" in path.read_text()

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    result = await import_(hass, filename=name)

    assert result["tasks_created"] == 2


@pytest.mark.parametrize(
    "name",
    ["../escape.json", "sub/export.json", "/etc/passwd.json", ".hidden.json", "configuration.txt"],
)
async def test_only_plain_file_names_are_accepted(
    hass: HomeAssistant, kitchen: str, name: str
) -> None:
    """A service call cannot reach other files, such as the configuration."""
    await full_setup(hass, kitchen)

    with pytest.raises(ServiceValidationError):
        await export(hass, filename=name)
    with pytest.raises(ServiceValidationError):
        await import_(hass, filename=name)


async def test_files_live_in_their_own_folder(hass: HomeAssistant, kitchen: str) -> None:
    """Exports go to <config>/task_exports, never next to the configuration."""
    await full_setup(hass, kitchen)

    response = await export(hass, filename="mine.yaml")

    assert Path(response["file"]) == Path(hass.config.path("task_exports")) / "mine.yaml"


async def test_a_missing_file_is_reported(hass: HomeAssistant) -> None:
    """Reading a file that is not there is an error message, not a crash."""
    with pytest.raises(ServiceValidationError):
        await import_(hass, filename="does_not_exist.json")


async def test_either_data_or_a_file_is_needed(hass: HomeAssistant) -> None:
    """Exactly one source."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "import_config", {}, blocking=True)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "import_config",
            {"data": {"version": 1}, "filename": "a.json"},
            blocking=True,
        )


async def test_imported_entities_exist(hass: HomeAssistant, kitchen: str) -> None:
    """After an import the area has its sensors (the entry reloaded)."""
    await import_(
        hass,
        {
            "version": 1,
            "areas": [{"area_id": kitchen, "tasks": [{"name": "Wipe counters"}]}],
        },
    )

    new = area_entries(hass)[0]
    sub = next(iter(new.subentries.values()))
    assert hass.states.get(task_sensor(hass, new, sub.subentry_id)) is not None
    assert hass.states.get(entity_id(hass, new, "sensor", "overdue_count")) is not None
