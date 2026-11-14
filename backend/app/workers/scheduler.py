"""Schedule trigger tick (C24) — one beat-driven pass over due schedule flows.

Celery beat runs ``tick_schedules`` every 60 s. The tick fires each enabled
flow whose latest definition has a ``schedule`` trigger and whose
``next_run_at`` is due (or never initialized). Events are stored through
the C22 idempotent path with ``schedule:{flow_id}:{slot}`` keys, so a
double tick (or a crashed previous tick) can never create a second event
for the same slot. Catch-up fires ONCE for the latest missed slot and
moves on — never a loop over missed slots.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from celery import shared_task  # type: ignore[import-untyped]
from sqlalchemy import desc, select

from app.db.engine import create_engine, create_session_factory
from app.models import Flow, FlowVersion
from app.services.cron import next_slot, parse_cron
from app.services.events import store_event

logger = structlog.get_logger(__name__)


def _enqueue_process_event(event_id: str) -> None:
    """Dispatch the event to the worker pipeline (lazy Celery import)."""
    from app.workers.celery_app import app as celery_app

    celery_app.send_task(
        "app.workers.tasks.process_event",
        args=[event_id],
    )


def _next_run_for(config: dict[str, Any], now: datetime) -> datetime:
    """Compute the next run: interval -> now + every_seconds; cron -> next slot."""
    if "every_seconds" in config:
        return now + timedelta(seconds=int(config["every_seconds"]))
    return next_slot(parse_cron(config["cron"]), now)


async def _tick_schedules() -> int:
    """Fire every due schedule flow; returns the number of events created."""
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    factory = create_session_factory(engine)
    try:
        fired = 0
        now = datetime.now(UTC)
        async with factory() as session:
            due = (
                select(Flow)
                .where(Flow.enabled.is_(True))
                .where(Flow.next_run_at.is_(None) | (Flow.next_run_at <= now))
            )
            flows = (await session.scalars(due)).all()

            for flow in flows:
                latest = await session.scalar(
                    select(FlowVersion)
                    .where(FlowVersion.flow_id == flow.id)
                    .order_by(desc(FlowVersion.version))
                    .limit(1)
                )
                if latest is None:
                    continue
                trigger = latest.definition.get("trigger") or {}
                if trigger.get("type") != "schedule":
                    continue
                config = trigger.get("config") or {}

                slot = flow.next_run_at or flow.created_at
                previous_run_at = slot.isoformat() if flow.next_run_at else None
                slot_iso = slot.isoformat()

                # Advance first so a crash after the event cannot re-fire the slot.
                flow.next_run_at = _next_run_for(config, now)
                await session.commit()

                event, created = await store_event(
                    session,
                    organization_id=flow.organization_id,
                    connection_id=None,
                    event_type="schedule",
                    payload={
                        "schedule": config,
                        "previous_run_at": previous_run_at,
                        "scheduled_at": slot_iso,
                    },
                    idempotency_key=f"schedule:{flow.id}:{slot_iso}",
                )
                await session.commit()
                if created:
                    _enqueue_process_event(str(event.id))
                    fired += 1
                    logger.info(
                        "schedule_fired", flow_id=str(flow.id), slot=slot_iso
                    )
        return fired
    finally:
        await engine.dispose()


@shared_task(name="app.workers.scheduler.tick_schedules")
def tick_schedules() -> int:
    """Beat entry point: fire due schedule flows (called every 60 s)."""
    return asyncio.run(_tick_schedules())
