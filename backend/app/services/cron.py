"""Cron support for the schedule trigger (C24) — stdlib only.

Five-field cron expressions (minute hour day-of-month month day-of-week)
with the classic forms: ``*``, ``*/n``, ``a``, ``a-b``, ``a-b/n`` and
comma lists of those. Day-of-week accepts 0-7 (0 and 7 are Sunday).
Unsupported syntax raises :class:`CronError` naming the offending field.

Semantic note (documented): day-of-month and day-of-week are combined with
AND — both must match. That is a deliberate simplification over classic
cron's OR-when-both-restricted rule; the UI in M4 exposes one field at a
time, and the AND rule is the least surprising for scheduled flows.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_FIELD_SPECS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("dom", 1, 31),
    ("month", 1, 12),
    ("dow", 0, 7),
)


class CronError(ValueError):
    """A cron expression is malformed; the message names the offending field."""


@dataclass(frozen=True)
class CronSchedule:
    """A parsed cron expression as per-field value sets."""

    minute: frozenset[int]
    hour: frozenset[int]
    dom: frozenset[int]
    month: frozenset[int]
    dow: frozenset[int]


def _parse_part(part: str, name: str, low: int, high: int) -> set[int]:
    """Parse one comma-free field segment (``*``, ``a``, ``a-b``, ``/n`` forms)."""
    base, sep, step_text = part.partition("/")
    step: int | None = None
    if sep:
        try:
            step = int(step_text)
        except ValueError as exc:
            raise CronError(f"{name}: invalid step '{step_text}'") from exc
        if step <= 0:
            raise CronError(f"{name}: step must be a positive integer")

    if base == "*":
        start, end = low, high
    elif "-" in base:
        head, _, tail = base.partition("-")
        try:
            start, end = int(head), int(tail)
        except ValueError as exc:
            raise CronError(f"{name}: invalid range '{base}'") from exc
        if start > end:
            raise CronError(f"{name}: range start exceeds end '{base}'")
    else:
        try:
            start = end = int(base)
        except ValueError as exc:
            raise CronError(f"{name}: invalid value '{base}'") from exc

    if start < low or end > high:
        raise CronError(f"{name}: value out of range {low}-{high} in '{part}'")

    span = range(start, end + 1)
    if step is not None:
        return {value for value in span if (value - start) % step == 0}
    return set(span)


def _parse_field(text: str, name: str, low: int, high: int) -> frozenset[int]:
    """Parse one cron field (comma lists allowed), normalizing dow 7 -> 0."""
    values: set[int] = set()
    for part in text.split(","):
        if not part:
            raise CronError(f"{name}: empty list element")
        values |= _parse_part(part, name, low, high)
    if name == "dow":
        values = {0 if value == 7 else value for value in values}
    return frozenset(values)


def parse_cron(expression: str) -> CronSchedule:
    """Parse a five-field cron expression.

    Args:
        expression: e.g. ``"*/15 9-18 * * 1-5"``.

    Returns:
        The :class:`CronSchedule`.

    Raises:
        CronError: Naming the first offending field.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise CronError(f"cron: expected 5 fields, got {len(fields)}")
    parsed = {
        name: _parse_field(text, name, low, high)
        for (name, low, high), text in zip(_FIELD_SPECS, fields, strict=True)
    }
    return CronSchedule(
        minute=parsed["minute"],
        hour=parsed["hour"],
        dom=parsed["dom"],
        month=parsed["month"],
        dow=parsed["dow"],
    )


def _cron_dow(moment: datetime) -> int:
    """Python weekday (Mon=0..Sun=6) -> cron dow (Sun=0..Sat=6)."""
    return (moment.weekday() + 1) % 7


def next_slot(schedule: CronSchedule, after: datetime) -> datetime:
    """First matching minute strictly after ``after`` (UTC).

    Args:
        schedule: A parsed expression.
        after: An aware datetime; the search starts at the next minute.

    Returns:
        The next firing moment (second=0, microsecond=0).

    Raises:
        CronError: For naive input or when nothing matches within 4 years
            (e.g. a February 31st expression).
    """
    if after.tzinfo is None:
        raise CronError("next_slot: 'after' must be a timezone-aware datetime")
    candidate = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = candidate + timedelta(days=4 * 366)
    while candidate <= limit:
        if (
            candidate.minute in schedule.minute
            and candidate.hour in schedule.hour
            and candidate.day in schedule.dom
            and candidate.month in schedule.month
            and _cron_dow(candidate) in schedule.dow
        ):
            return candidate
        candidate += timedelta(minutes=1)
    raise CronError("next_slot: no occurrence within 4 years")


def validate_cron(expression: str) -> str:
    """Return the expression when parseable (helper for schema validators)."""
    parse_cron(expression)
    return expression
