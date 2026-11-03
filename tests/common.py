"""Helpers shared by the Task integration tests."""

from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.task.const import DOMAIN


def task_subentry(
    subentry_id: str, title: str, **data: Any
) -> ConfigSubentryData:
    """Build a task subentry; the interval defaults to 7 days."""
    return ConfigSubentryData(
        subentry_type="task",
        title=title,
        subentry_id=subentry_id,
        unique_id=None,
        data={"interval_days": 7, **data},
    )


async def setup_entry(
    hass: HomeAssistant,
    subentries: list[ConfigSubentryData],
    **entry_data: Any,
) -> MockConfigEntry:
    """Set up an area entry with the given tasks."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="kitchen",
        data={"area_id": "kitchen", **entry_data},
        subentries_data=subentries,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, unique_suffix: str
) -> str:
    """Return the entity ID for the unique ID `<entry_id>_<suffix>`."""
    found = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{unique_suffix}"
    )
    assert found is not None, f"no {platform} entity for {unique_suffix}"
    return found


def task_sensor(hass: HomeAssistant, entry: MockConfigEntry, subentry_id: str) -> str:
    """Return the days-until-due sensor of a task."""
    return entity_id(hass, entry, "sensor", f"{subentry_id}_sensor")


def status_sensor(hass: HomeAssistant, entry: MockConfigEntry, subentry_id: str) -> str:
    """Return the status sensor of a task."""
    return entity_id(hass, entry, "sensor", f"{subentry_id}_status")


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Recompute the coordinator, as the 15 minute update would."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
