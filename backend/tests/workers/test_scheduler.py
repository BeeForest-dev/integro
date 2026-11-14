"""Tests for C24 workers.scheduler — PG-backed, no real beat.

The tick coroutine is invoked directly inside one event loop; the enqueue
seam is spied like in the C22 webhook suite.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.db.engine import create_engine, create_session_factory
from app.models import Event, Flow, FlowVersion, Organization
from app.repositories.flows import create_flow
from app.repositories.org_scope import OrgScope
from app.schemas.flow_definition import FlowDefinition
from app.workers import scheduler

BACKEND_DIR = Path(__file__).resolve().parents[2]

INTERVAL_TRIGGER = {"type": "schedule", "config": {"every_seconds": 300}}
CRON_TRIGGER = {"type": "schedule", "config": {"cron": "0 9 * * *"}}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set - these tests require a real PostgreSQL")
    return url


def _alembic_cfg() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _database_url())
    return cfg


@pytest.fixture(autouse=True)
def database(monkeypatch):
    """Schema at head, empty tables, spied enqueue seam, per test."""
    monkeypatch.setenv("DATABASE_URL", _database_url())
    command.upgrade(_alembic_cfg(), "head")
    asyncio.run(_clean_all())
    sent: list[str] = []
    monkeypatch.setattr(scheduler, "_enqueue_process_event", sent.append)
    yield sent
    asyncio.run(_clean_all())


async def _clean_all():
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        for model in (Event, FlowVersion, Flow, Organization):
            async with factory() as session:
                await session.execute(delete(model))
                await session.commit()
    finally:
        await engine.dispose()


async def _seed_flow(trigger=None, enabled=True, next_run_at=None):
    """Create an organization with one flow; optionally tune next_run_at."""
    trigger = trigger or INTERVAL_TRIGGER
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            organization = Organization(name="Org", slug=f"sched-{os.urandom(4).hex()}")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)
            flow = await create_flow(
                session,
                scope,
                name="Scheduled",
                definition={"trigger": trigger, "actions": []},
            )
            if not enabled:
                flow.enabled = False
            if next_run_at is not None:
                flow.next_run_at = next_run_at
            await session.commit()
            return organization.id, flow.id
    finally:
        await engine.dispose()


async def _read_flow(flow_id):
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return await session.get(Flow, flow_id)
    finally:
        await engine.dispose()


async def _events():
    engine = create_engine(_database_url())
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            return (await session.scalars(select(Event))).all()
    finally:
        await engine.dispose()


def test_schema_rejects_bad_schedule_configs():
    """Save-time validation: bad cron, both keys, zero interval -> ValueError."""
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(
            {"trigger": {"type": "schedule", "config": {"cron": "not-a-cron"}}}
        )
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(
            {"trigger": {"type": "schedule", "config": {"cron": "* * * * *", "every_seconds": 60}}}
        )
    with pytest.raises(ValidationError):
        FlowDefinition.model_validate(
            {"trigger": {"type": "schedule", "config": {"every_seconds": 0}}}
        )
    valid = FlowDefinition.model_validate(
        {"trigger": {"type": "schedule", "config": {"cron": "*/5 9-18 * * 1-5"}}, "actions": []}
    )
    assert valid.trigger.type == "schedule"


def test_tick_fires_due_interval_flow(database):
    """A due interval flow fires exactly one event and advances next_run_at."""
    _, flow_id = asyncio.run(_seed_flow(next_run_at=datetime.now(UTC) - timedelta(minutes=10)))

    fired = asyncio.run(scheduler._tick_schedules())

    assert fired == 1
    assert database == [str(asyncio.run(_events())[0].id)]
    events = asyncio.run(_events())
    assert len(events) == 1
    assert events[0].type == "schedule"
    assert events[0].payload["schedule"] == {"every_seconds": 300}
    assert events[0].payload["previous_run_at"] is not None
    assert events[0].payload["scheduled_at"] == events[0].payload["previous_run_at"]
    flow = asyncio.run(_read_flow(flow_id))
    assert flow.next_run_at is not None
    assert flow.next_run_at > datetime.now(UTC)


def test_tick_skips_not_due_flow(database):
    """A flow whose next_run_at is in the future is untouched."""
    future = datetime.now(UTC) + timedelta(hours=1)
    _, flow_id = asyncio.run(_seed_flow(next_run_at=future))

    fired = asyncio.run(scheduler._tick_schedules())

    assert fired == 0
    assert asyncio.run(_events()) == []
    assert asyncio.run(_read_flow(flow_id)).next_run_at == future


def test_tick_skips_disabled_flow(database):
    """A disabled flow never fires, even when due."""
    asyncio.run(_seed_flow(enabled=False, next_run_at=datetime.now(UTC) - timedelta(minutes=1)))

    fired = asyncio.run(scheduler._tick_schedules())

    assert fired == 0
    assert asyncio.run(_events()) == []


def test_catch_up_fires_once_for_the_latest_missed_slot(database):
    """next_run_at 3h in the past -> ONE event, then the next run is future."""
    missed = datetime.now(UTC) - timedelta(hours=3)
    _, flow_id = asyncio.run(_seed_flow(next_run_at=missed))

    fired = asyncio.run(scheduler._tick_schedules())

    assert fired == 1
    events = asyncio.run(_events())
    assert len(events) == 1
    assert events[0].idempotency_key.endswith(missed.isoformat())
    flow = asyncio.run(_read_flow(flow_id))
    assert flow.next_run_at is not None
    assert flow.next_run_at > datetime.now(UTC)


def test_double_tick_creates_one_event(database):
    """Two ticks back to back: the slot idempotency key suppresses the second."""
    asyncio.run(_seed_flow(next_run_at=datetime.now(UTC) - timedelta(minutes=1)))

    first = asyncio.run(scheduler._tick_schedules())
    second = asyncio.run(scheduler._tick_schedules())

    assert first == 1
    assert second == 0
    assert len(asyncio.run(_events())) == 1
    assert len(database) == 1


def test_successive_slots_each_fire_once(database):
    """A flow firing on two different slots produces TWO events.

    The slot is part of the idempotency key: without it, the second slot
    would collide with the first event's key and be swallowed (the flow
    would fire exactly once, ever).
    """
    _, flow_id = asyncio.run(_seed_flow(next_run_at=datetime.now(UTC) - timedelta(minutes=5)))

    assert asyncio.run(scheduler._tick_schedules()) == 1

    async def _rearm():
        engine = create_engine(_database_url())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                target = await session.get(Flow, flow_id)
                target.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
                await session.commit()
        finally:
            await engine.dispose()

    asyncio.run(_rearm())

    assert asyncio.run(scheduler._tick_schedules()) == 1
    events = asyncio.run(_events())
    assert len(events) == 2
    assert len({e.idempotency_key for e in events}) == 2
    assert len(database) == 2


def test_tick_fires_cron_flow(database):
    """A due cron flow fires and lands on the next daily slot."""
    past_slot = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    past_slot = past_slot - timedelta(days=1)
    _, flow_id = asyncio.run(_seed_flow(trigger=CRON_TRIGGER, next_run_at=past_slot))

    fired = asyncio.run(scheduler._tick_schedules())

    assert fired == 1
    flow = asyncio.run(_read_flow(flow_id))
    assert flow.next_run_at is not None
    assert flow.next_run_at > datetime.now(UTC)
    assert flow.next_run_at.hour == 9
    assert flow.next_run_at.minute == 0


def test_tick_initializes_never_run_flow(database):
    """A schedule flow with NULL next_run_at fires once (slot = created_at)."""
    _, flow_id = asyncio.run(_seed_flow())

    fired = asyncio.run(scheduler._tick_schedules())

    assert fired == 1
    assert len(asyncio.run(_events())) == 1
    flow = asyncio.run(_read_flow(flow_id))
    assert flow.next_run_at is not None
    assert flow.next_run_at > datetime.now(UTC)


def test_beat_entry_registered(monkeypatch):
    """The beat schedule carries the 60-second tick entry (celery_app conf)."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    from app.workers.celery_app import app

    entry = app.conf.beat_schedule.get("tick-schedules")
    assert entry is not None
    assert entry["task"] == "app.workers.scheduler.tick_schedules"
    assert entry["schedule"] == 60.0
