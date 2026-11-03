"""Due-date arithmetic: day, week and month intervals and active months."""

import calendar
import datetime

INTERVAL_UNITS = ("days", "weeks", "months")

_AVERAGE_DAYS_PER_MONTH = 30.44


def add_months(day: datetime.date, months: int) -> datetime.date:
    """Add (or subtract) calendar months; the day is clamped to the month's end."""
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return day.replace(
        year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1])
    )


def add_interval(
    day: datetime.date, value: int, unit: str, direction: int = 1
) -> datetime.date:
    """Move a date by an interval; ``direction`` -1 goes back."""
    if unit == "months":
        return add_months(day, direction * value)
    days = value * 7 if unit == "weeks" else value
    return day + datetime.timedelta(days=direction * days)


def nominal_days(value: int, unit: str) -> int:
    """Return the interval in days (months count as 30.44 days) for display and statistics."""
    if unit == "months":
        return round(value * _AVERAGE_DAYS_PER_MONTH)
    return value * 7 if unit == "weeks" else value


def in_season(day: datetime.date, active_months: list[int]) -> bool:
    """Return True if the task is active on ``day`` (always, without active months)."""
    return not active_months or day.month in active_months


def next_active_day(day: datetime.date, active_months: list[int]) -> datetime.date:
    """Return ``day`` if it is in season, else the first day of the next active month."""
    if in_season(day, active_months):
        return day
    for offset in range(1, 13):
        candidate = add_months(day.replace(day=1), offset)
        if candidate.month in active_months:
            return candidate
    return day


def due_date(
    last_completed: datetime.date | None,
    value: int,
    unit: str,
    active_months: list[int],
    today: datetime.date,
    postponed_until: datetime.date | None = None,
) -> datetime.date:
    """Return when a task is next due.

    A task that was never completed is due today. A postponement only ever
    pushes the date back. With active months, a date outside them moves to the
    start of the next active month, and a window that was missed is skipped:
    outside the season a task is neither due nor overdue.
    """
    raw = (
        add_interval(last_completed, value, unit) if last_completed else today
    )
    if postponed_until and postponed_until > raw:
        raw = postponed_until
    if not active_months:
        return raw
    due = next_active_day(raw, active_months)
    if due < today and not in_season(today, active_months):
        due = next_active_day(today, active_months)
    return due


def rrule(value: int, unit: str, active_months: list[int]) -> str:
    """Return the iCalendar recurrence rule for an interval and active months."""
    freq = {"days": "DAILY", "weeks": "WEEKLY", "months": "MONTHLY"}.get(unit, "DAILY")
    rule = f"FREQ={freq};INTERVAL={value}"
    if active_months:
        rule += ";BYMONTH=" + ",".join(str(m) for m in sorted(active_months))
    return rule


def occurrences(
    first_due: datetime.date,
    value: int,
    unit: str,
    active_months: list[int],
    start: datetime.date,
    end: datetime.date,
) -> list[datetime.date]:
    """Return the dates in ``[start, end)`` on which the task recurs.

    Starts from the next due date. Later dates step forward by the interval
    (a date outside the season moves to the start of the next one); earlier
    dates step back and are skipped if they lie outside the season.
    """
    if value <= 0:
        return []

    found: set[datetime.date] = set()

    day = next_active_day(first_due, active_months)
    for _ in range(5000):
        if day >= end:
            break
        if day >= start:
            found.add(day)
        following = next_active_day(add_interval(day, value, unit), active_months)
        if following <= day:
            break
        day = following

    day = first_due
    for _ in range(5000):
        day = add_interval(day, value, unit, direction=-1)
        if day < start:
            break
        if day < end and in_season(day, active_months):
            found.add(day)

    return sorted(found)
