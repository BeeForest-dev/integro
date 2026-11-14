"""Tests for C24 services.cron — pure stdlib parser, no database."""

from datetime import UTC, datetime

import pytest

from app.services.cron import CronError, next_slot, parse_cron

T = datetime(2026, 11, 14, 12, 30, 45, tzinfo=UTC)  # Saturday


@pytest.mark.parametrize(
    ("expression", "field", "expected"),
    [
        ("* * * * *", "minute", set(range(60))),
        ("*/15 * * * *", "minute", set(range(0, 60, 15))),
        ("5 * * * *", "minute", {5}),
        ("10-20 * * * *", "minute", set(range(10, 21))),
        ("10-20/5 * * * *", "minute", {10, 15, 20}),
        ("1,7,42 * * * *", "minute", {1, 7, 42}),
        ("0 9-18 * * 1-5", "hour", set(range(9, 19))),
        ("0 0 1 * *", "dom", {1}),
        ("0 0 * 6 *", "month", {6}),
        ("0 0 * * 7", "dow", {0}),  # 7 normalizes to Sunday
        ("0 0 * * 0,6", "dow", {0, 6}),
    ],
)
def test_parser_field_forms(expression, field, expected):
    """Every documented field form parses to the expected value set."""
    schedule = parse_cron(expression)
    assert getattr(schedule, field) == frozenset(expected)


@pytest.mark.parametrize(
    ("expression", "name"),
    [
        ("61 * * * *", "minute"),
        ("* 24 * * *", "hour"),
        ("* * 0 * *", "dom"),
        ("* * * 13 *", "month"),
        ("* * * * 8", "dow"),
        ("*/0 * * * *", "minute"),
        ("5-2 * * * *", "minute"),
        ("a * * * *", "minute"),
        ("* * * *", "cron"),
        ("* * * * * *", "cron"),
        ("1,,2 * * * *", "minute"),
    ],
)
def test_parser_invalid_syntax_names_the_field(expression, name):
    """Bad syntax raises CronError naming the offending field."""
    with pytest.raises(CronError) as exc_info:
        parse_cron(expression)
    assert f"{name}:" in str(exc_info.value)


def test_next_slot_minute_boundary():
    """*/15 from 12:30:45 finds 12:45 (search starts at the next minute)."""
    slot = next_slot(parse_cron("*/15 * * * *"), T)
    assert slot == datetime(2026, 11, 14, 12, 45, tzinfo=UTC)


def test_next_slot_hour_boundary():
    """Daily 09:00 after 08:59 finds the same day; after 09:00 the next day."""
    daily = parse_cron("0 9 * * *")
    assert next_slot(daily, datetime(2026, 11, 14, 8, 59, tzinfo=UTC)) == datetime(
        2026, 11, 14, 9, 0, tzinfo=UTC
    )
    assert next_slot(daily, datetime(2026, 11, 14, 9, 0, tzinfo=UTC)) == datetime(
        2026, 11, 15, 9, 0, tzinfo=UTC
    )


def test_next_slot_day_boundary():
    """Weekday 9:00 from Saturday finds Monday (dow 1-5, AND semantics)."""
    weekday = parse_cron("0 9 * * 1-5")
    slot = next_slot(weekday, T)
    assert slot == datetime(2026, 11, 16, 9, 0, tzinfo=UTC)  # Monday
    assert slot.weekday() == 0


def test_next_slot_month_boundary():
    """Jan 1st after Dec 31st lands on the next Jan 1st."""
    yearly = parse_cron("0 0 1 1 *")
    slot = next_slot(yearly, datetime(2026, 12, 31, 23, 59, tzinfo=UTC))
    assert slot == datetime(2027, 1, 1, 0, 0, tzinfo=UTC)


def test_next_slot_strictly_after():
    """A slot equal to 'after' is never returned."""
    every_minute = parse_cron("* * * * *")
    on_the_minute = datetime(2026, 11, 14, 12, 30, tzinfo=UTC)
    assert next_slot(every_minute, on_the_minute) == datetime(
        2026, 11, 14, 12, 31, tzinfo=UTC
    )


def test_next_slot_rejects_naive_input():
    """Naive datetimes raise CronError instead of guessing a timezone."""
    with pytest.raises(CronError):
        next_slot(parse_cron("* * * * *"), datetime(2026, 11, 14, 12, 30))
