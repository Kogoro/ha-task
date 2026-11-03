"""Statistics over a task's completion history."""

import datetime
from dataclasses import dataclass

from .store import CompletionEntry


@dataclass
class CycleStats:
    """How the actual time between completions compares with the interval."""

    average_cycle_days: float | None
    last_cycle_days: float | None
    on_time_percent: int | None


def cycle_days(completions: list[CompletionEntry]) -> list[float | None]:
    """Return the days since the previous completion for each completion.

    The first completion has no predecessor, so its value is None.
    """
    result: list[float | None] = []
    previous: datetime.datetime | None = None
    for entry in completions:
        if previous is None:
            result.append(None)
        else:
            result.append(
                round((entry.completed_at - previous).total_seconds() / 86400, 1)
            )
        previous = entry.completed_at
    return result


def cycle_stats(completions: list[CompletionEntry], interval_days: int) -> CycleStats:
    """Return average and last cycle length and the share done within the interval.

    A cycle is "on time" if the next completion came within the planned interval
    after the previous one. With fewer than two completions nothing can be said.
    """
    cycles = [c for c in cycle_days(completions) if c is not None]
    if not cycles:
        return CycleStats(None, None, None)
    on_time = sum(1 for c in cycles if c <= interval_days)
    return CycleStats(
        average_cycle_days=round(sum(cycles) / len(cycles), 1),
        last_cycle_days=cycles[-1],
        on_time_percent=round(100 * on_time / len(cycles)),
    )
