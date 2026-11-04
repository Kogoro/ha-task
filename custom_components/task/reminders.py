"""Built-in reminders: notify when a task is due soon or overdue."""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_REMINDER_DUE_SOON,
    CONF_REMINDER_OVERDUE,
    CONF_REMINDER_SERVICE,
    CONF_REMINDER_TARGETS,
    CONF_REMINDER_TIME,
    CONF_REMINDERS,
    DEFAULT_REMINDER_TIME,
    REMINDER_GROUP_SIZE,
    TaskStatus,
)

if TYPE_CHECKING:
    from .coordinator import TaskCoordinator, TaskData

_LOGGER = logging.getLogger(__name__)

KIND_DUE_SOON = "due_soon"
KIND_OVERDUE = "overdue"

_TEXT = {
    "en": {
        "due_soon_title": "Task due soon",
        "overdue_title": "Task overdue",
        "today": "today",
        "tomorrow": "tomorrow",
        "in_days": "in {n} days",
        "due": "{task} ({area}) is due {when}.",
        "late": "{task} ({area}) is {n} day(s) overdue.",
        "assigned": " Assigned to {who}.",
        "group_due_soon": "{n} tasks due soon",
        "group_overdue": "{n} tasks overdue",
        "more": "+{n} more",
    },
    "de": {
        "due_soon_title": "Aufgabe bald fällig",
        "overdue_title": "Aufgabe überfällig",
        "today": "heute",
        "tomorrow": "morgen",
        "in_days": "in {n} Tagen",
        "due": "{task} ({area}) ist {when} fällig.",
        "late": "{task} ({area}) ist seit {n} Tag(en) überfällig.",
        "assigned": " Zuständig: {who}.",
        "group_due_soon": "{n} Aufgaben bald fällig",
        "group_overdue": "{n} Aufgaben überfällig",
        "more": "+{n} weitere",
    },
}


def _text(language: str) -> dict[str, str]:
    """Return the message texts for a language (English as the fallback)."""
    return _TEXT["de" if language.lower().startswith("de") else "en"]


def _reminder_time(value: object) -> datetime.time:
    """Parse the configured time of day."""
    try:
        return datetime.time.fromisoformat(str(value or DEFAULT_REMINDER_TIME))
    except ValueError:
        return datetime.time.fromisoformat(DEFAULT_REMINDER_TIME)


async def _notify(
    coordinator: TaskCoordinator, title: str, message: str
) -> bool:
    """Send a message to the configured targets; return False if any failed."""
    hass = coordinator.hass
    data = coordinator.config_entry.data
    ok = True
    if targets := data.get(CONF_REMINDER_TARGETS):
        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": list(targets), "title": title, "message": message},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not send a task reminder to %s: %s", targets, err)
            ok = False
    if service := data.get(CONF_REMINDER_SERVICE):
        try:
            await hass.services.async_call(
                "notify",
                service.split(".", 1)[-1],
                {"title": title, "message": message},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Could not send a task reminder via %s: %s", service, err)
            ok = False
    return ok


def _assignee(coordinator: TaskCoordinator, item: TaskData) -> str | None:
    """Return the display name of the person responsible, if any."""
    person = item.current_assignee
    if not person:
        return None
    state = coordinator.hass.states.get(person)
    return state.name if state else person


def _single_message(
    coordinator: TaskCoordinator, item: TaskData, kind: str, area_name: str
) -> tuple[str, str]:
    """Return title and message for one task."""
    t = _text(coordinator.hass.config.language)
    if kind == KIND_DUE_SOON:
        days = item.days_until_due or 0
        when = (
            t["today"]
            if days <= 0
            else t["tomorrow"] if days == 1 else t["in_days"].format(n=days)
        )
        message = t["due"].format(task=item.name, area=area_name, when=when)
        title = t["due_soon_title"]
    else:
        message = t["late"].format(
            task=item.name, area=area_name, n=abs(item.days_until_due or 0)
        )
        title = t["overdue_title"]
    if who := _assignee(coordinator, item):
        message += t["assigned"].format(who=who)
    return title, message


def _group_message(
    coordinator: TaskCoordinator, items: list[TaskData], kind: str
) -> tuple[str, str]:
    """Return title and message summarising several tasks."""
    t = _text(coordinator.hass.config.language)
    title = t["group_due_soon" if kind == KIND_DUE_SOON else "group_overdue"].format(
        n=len(items)
    )
    names = [i.name for i in items[:5]]
    message = ", ".join(names)
    if len(items) > len(names):
        message += f" ({t['more'].format(n=len(items) - len(names))})"
    return title, message


async def async_send_reminders(
    coordinator: TaskCoordinator, items: dict[str, TaskData], area_name: str
) -> None:
    """Send reminders for tasks that are due soon or overdue and not yet reminded.

    Each task is reminded once per due date and kind; that is stored, so a
    restart does not repeat it. Nothing is sent before the configured time of
    day, and tasks that were never completed are skipped (they have no schedule
    yet, and importing many tasks would otherwise cause a flood). More than a few
    at once are sent as one summary.
    """
    entry = coordinator.config_entry
    data = entry.data
    if not data.get(CONF_REMINDER_TARGETS) and not data.get(CONF_REMINDER_SERVICE):
        return
    if dt_util.now().time() < _reminder_time(data.get(CONF_REMINDER_TIME)):
        return

    store = coordinator.store
    wanted = {
        KIND_DUE_SOON: data.get(CONF_REMINDER_DUE_SOON, True),
        KIND_OVERDUE: data.get(CONF_REMINDER_OVERDUE, True),
    }
    status_for = {KIND_DUE_SOON: TaskStatus.DUE_SOON, KIND_OVERDUE: TaskStatus.OVERDUE}

    for kind in (KIND_OVERDUE, KIND_DUE_SOON):
        if not wanted[kind]:
            continue
        pending: list[TaskData] = []
        for subentry_id, item in items.items():
            subentry = entry.subentries.get(subentry_id)
            if subentry is None or subentry.data.get(CONF_REMINDERS, True) is False:
                continue
            if item.last_completed is None or item.status is not status_for[kind]:
                continue
            if store.reminder_sent(subentry_id, kind, item.next_due):
                continue
            pending.append(item)
        if not pending:
            continue

        if len(pending) > REMINDER_GROUP_SIZE:
            sent = await _notify(coordinator, *_group_message(coordinator, pending, kind))
            if sent:
                for item in pending:
                    store.mark_reminder_sent(item.subentry_id, kind, item.next_due)
            continue

        for item in pending:
            title, message = _single_message(coordinator, item, kind, area_name)
            if await _notify(coordinator, title, message):
                store.mark_reminder_sent(item.subentry_id, kind, item.next_due)
