"""Due-date arithmetic: units and active months."""

import datetime

import pytest

from custom_components.task.schedule import (
    add_interval,
    add_months,
    due_date,
    in_season,
    next_active_day,
    nominal_days,
    occurrences,
    rrule,
)

D = datetime.date


def test_add_months_keeps_the_day_when_it_exists() -> None:
    """15 January + 1 month is 15 February."""
    assert add_months(D(2026, 1, 15), 1) == D(2026, 2, 15)


def test_add_months_clamps_to_the_end_of_the_month() -> None:
    """31 January + 1 month is the last day of February."""
    assert add_months(D(2026, 1, 31), 1) == D(2026, 2, 28)
    assert add_months(D(2028, 1, 31), 1) == D(2028, 2, 29)
    assert add_months(D(2026, 3, 31), -1) == D(2026, 2, 28)


def test_add_months_crosses_years() -> None:
    """November + 3 months is February of the next year."""
    assert add_months(D(2026, 11, 30), 3) == D(2027, 2, 28)
    assert add_months(D(2026, 1, 10), -2) == D(2025, 11, 10)
    assert add_months(D(2026, 5, 5), 24) == D(2028, 5, 5)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (10, "days", D(2026, 11, 13)),
        (2, "weeks", D(2026, 11, 17)),
        (3, "months", D(2027, 2, 3)),
    ],
)
def test_add_interval(value: int, unit: str, expected: datetime.date) -> None:
    """Days, weeks and calendar months."""
    assert add_interval(D(2026, 11, 3), value, unit) == expected


def test_add_interval_backwards() -> None:
    """The direction can be reversed."""
    assert add_interval(D(2026, 11, 3), 1, "weeks", direction=-1) == D(2026, 10, 27)
    assert add_interval(D(2026, 11, 3), 2, "months", direction=-1) == D(2026, 9, 3)


def test_nominal_days() -> None:
    """Weeks are seven days, months about 30.44."""
    assert nominal_days(10, "days") == 10
    assert nominal_days(2, "weeks") == 14
    assert nominal_days(1, "months") == 30
    assert nominal_days(6, "months") == 183
    assert nominal_days(12, "months") == 365


def test_in_season() -> None:
    """Without active months a task is always in season."""
    assert in_season(D(2026, 12, 1), [])
    assert in_season(D(2026, 4, 30), [3, 4, 5])
    assert not in_season(D(2026, 6, 1), [3, 4, 5])


def test_next_active_day() -> None:
    """A date outside the season moves to the first day of the next active month."""
    assert next_active_day(D(2026, 4, 15), [3, 4, 5]) == D(2026, 4, 15)
    assert next_active_day(D(2026, 6, 15), [3, 4, 5]) == D(2027, 3, 1)
    assert next_active_day(D(2026, 12, 31), [1]) == D(2027, 1, 1)
    assert next_active_day(D(2026, 7, 1), [9, 10]) == D(2026, 9, 1)


class TestDueDate:
    """When a task is next due."""

    def test_without_active_months_it_is_the_plain_interval(self) -> None:
        assert due_date(D(2026, 10, 30), 7, "days", [], D(2026, 11, 3)) == D(2026, 11, 6)

    def test_a_task_never_done_is_due_today(self) -> None:
        assert due_date(None, 7, "days", [], D(2026, 11, 3)) == D(2026, 11, 3)

    def test_months_interval(self) -> None:
        assert due_date(D(2026, 10, 31), 1, "months", [], D(2026, 11, 3)) == D(2026, 11, 30)

    def test_due_inside_the_season_stays(self) -> None:
        assert due_date(D(2026, 4, 1), 2, "weeks", [4, 5], D(2026, 4, 5)) == D(2026, 4, 15)

    def test_due_after_the_season_waits_for_the_next_one(self) -> None:
        got = due_date(D(2026, 9, 25), 7, "days", [4, 5, 6, 7, 8, 9], D(2026, 9, 26))
        assert got == D(2027, 4, 1)

    def test_never_done_outside_the_season_is_not_due_yet(self) -> None:
        today = D(2026, 11, 3)
        assert due_date(None, 7, "days", [4, 5, 6], today) == D(2027, 4, 1)

    def test_never_done_inside_the_season_is_due_today(self) -> None:
        today = D(2026, 5, 3)
        assert due_date(None, 7, "days", [4, 5, 6], today) == today

    def test_a_missed_window_is_skipped(self) -> None:
        """Due at the end of the season but not done: no overdue after it closed."""
        got = due_date(D(2026, 9, 22), 7, "days", [4, 5, 6, 7, 8, 9], D(2026, 10, 2))
        assert got == D(2027, 4, 1)

    def test_overdue_inside_the_season_is_overdue(self) -> None:
        got = due_date(D(2026, 4, 1), 1, "weeks", [4, 5], D(2026, 4, 20))
        assert got == D(2026, 4, 8)

    def test_due_while_the_window_was_closed_is_due_since_it_opened(self) -> None:
        """Due on 1 October, but the season starts 1 April."""
        got = due_date(D(2026, 9, 1), 1, "months", [4, 5, 6], D(2027, 4, 15))
        assert got == D(2027, 4, 1)

    def test_a_postponement_pushes_back(self) -> None:
        got = due_date(D(2026, 10, 30), 7, "days", [], D(2026, 11, 3), D(2026, 11, 20))
        assert got == D(2026, 11, 20)

    def test_a_postponement_into_the_off_season_moves_to_the_next_season(self) -> None:
        got = due_date(
            D(2026, 4, 1), 1, "weeks", [4, 5], D(2026, 4, 5), postponed_until=D(2026, 7, 1)
        )
        assert got == D(2027, 4, 1)

    def test_an_earlier_postponement_changes_nothing(self) -> None:
        got = due_date(D(2026, 10, 30), 7, "days", [], D(2026, 11, 3), D(2026, 11, 4))
        assert got == D(2026, 11, 6)


def test_rrule() -> None:
    """Recurrence rules for the calendar."""
    assert rrule(7, "days", []) == "FREQ=DAILY;INTERVAL=7"
    assert rrule(2, "weeks", []) == "FREQ=WEEKLY;INTERVAL=2"
    assert rrule(3, "months", []) == "FREQ=MONTHLY;INTERVAL=3"
    assert rrule(1, "weeks", [5, 3, 4]) == "FREQ=WEEKLY;INTERVAL=1;BYMONTH=3,4,5"


class TestOccurrences:
    """The dates shown in the calendar."""

    def test_every_week(self) -> None:
        got = occurrences(D(2026, 11, 10), 7, "days", [], D(2026, 11, 1), D(2026, 12, 1))
        assert got == [D(2026, 11, 3), D(2026, 11, 10), D(2026, 11, 17), D(2026, 11, 24)]

    def test_every_month_looks_back_and_forward(self) -> None:
        got = occurrences(D(2026, 11, 10), 1, "months", [], D(2026, 9, 1), D(2027, 1, 1))
        assert got == [D(2026, 9, 10), D(2026, 10, 10), D(2026, 11, 10), D(2026, 12, 10)]

    def test_nothing_in_the_off_season(self) -> None:
        got = occurrences(D(2027, 4, 1), 1, "weeks", [4, 5], D(2026, 11, 1), D(2026, 12, 1))
        assert got == []

    def test_only_active_months_in_a_longer_range(self) -> None:
        got = occurrences(D(2027, 4, 1), 2, "weeks", [4, 5], D(2027, 3, 1), D(2027, 7, 1))
        assert got
        assert {d.month for d in got} <= {4, 5}
        assert D(2027, 4, 1) in got

    def test_the_next_season_starts_on_its_first_day(self) -> None:
        got = occurrences(D(2026, 9, 28), 1, "weeks", [4, 5, 6, 7, 8, 9], D(2027, 3, 1), D(2027, 5, 1))
        assert got[0] == D(2027, 4, 1)

    def test_an_invalid_interval_gives_nothing(self) -> None:
        assert occurrences(D(2026, 11, 10), 0, "days", [], D(2026, 11, 1), D(2026, 12, 1)) == []
