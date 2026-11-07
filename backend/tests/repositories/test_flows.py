"""Tests for C20 models.flow + repositories.flows.

Real PostgreSQL via DATABASE_URL (compose postgres locally, CI service
container). No skips: without a reachable database these tests fail loudly.
"""

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, inspect

from app.core.errors import AppError
from app.db.engine import create_engine, create_session_factory
from app.models import SUPPORTED_TYPES, Flow, FlowVersion, Organization
from app.repositories.flows import (
    create_flow,
    get_current_definition,
    get_flow,
    list_flows,
    set_enabled,
    update_flow_definition,
    version_history,
)
from app.repositories.org_scope import OrgScope

BACKEND_DIR = Path(__file__).resolve().parents[2]
VALID_DEFINITION = {
    "trigger": {"type": "webhook_in", "config": {"path": "/hook"}},
    "actions": [{"type": "http_api", "config": {"url": "https://example.com"}}],
}


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


@pytest.fixture
def run():
    """Run a coroutine against a fresh engine bound to a single event loop.

    Tables are cleaned before AND after (FK hygiene for other suites).
    """

    def _run(scenario) -> None:
        async def _wrapped():
            engine = create_engine(_database_url())
            factory = create_session_factory(engine)
            try:
                command.upgrade(_alembic_cfg(), "head")
                for model in (FlowVersion, Flow, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
                await scenario(factory)
                for model in (FlowVersion, Flow, Organization):
                    async with factory() as session:
                        await session.execute(delete(model))
                        await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(_wrapped())

    return _run


def _flow_tables_exist() -> bool:
    async def _check() -> bool:
        engine = create_engine(_database_url())
        try:
            async with engine.connect() as connection:
                tables = set(
                    await connection.run_sync(lambda conn: inspect(conn).get_table_names())
                )
                return {"flows", "flow_versions"}.issubset(tables)
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def test_migration_0009_cycle():
    """upgrade head creates flows + flow_versions, downgrade base drops them, re-up is clean."""
    command.downgrade(_alembic_cfg(), "base")
    assert not _flow_tables_exist()

    command.upgrade(_alembic_cfg(), "head")
    assert _flow_tables_exist()

    command.downgrade(_alembic_cfg(), "base")
    assert not _flow_tables_exist()

    command.upgrade(_alembic_cfg(), "head")
    assert _flow_tables_exist()


def test_create_flow_persists_version_one(run):
    """create_flow stores the flow and version 1 with the validated definition."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="flow-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            flow = await create_flow(
                session, scope, name="Lead routing", definition=VALID_DEFINITION
            )
            await session.commit()

            assert flow.enabled is True
            assert flow.organization_id == organization.id
            history = await version_history(session, scope, flow.id)
            assert [v.version for v in history] == [1]
            assert history[0].definition == VALID_DEFINITION
            current = await get_current_definition(session, scope, flow.id)
            assert current is not None and current.version == 1

    run(_scenario)


def test_update_bumps_version_monotonically_and_uniquely(run):
    """Each update appends max+1; duplicate (flow_id, version) is rejected."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="versions-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            flow = await create_flow(session, scope, name="F", definition=VALID_DEFINITION)
            v2 = await update_flow_definition(
                session, scope, flow.id, {**VALID_DEFINITION, "actions": []}
            )
            v3 = await update_flow_definition(session, scope, flow.id, VALID_DEFINITION)
            await session.commit()

            assert [v.version for v in (v2, v3)] == [2, 3]
            assert [v.version for v in await version_history(session, scope, flow.id)] == [1, 2, 3]

            session.add(FlowVersion(flow_id=flow.id, version=3, definition={}))
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                await session.flush()

    run(_scenario)


def test_missing_trigger_is_a_422_with_the_path(run):
    """A definition without trigger -> 422 naming the 'trigger' path."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="no-trigger-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            with pytest.raises(AppError) as exc_info:
                await create_flow(session, scope, name="Bad", definition={"actions": []})
            error = exc_info.value
            assert error.status_code == 422
            assert error.detail.startswith("trigger:")

    run(_scenario)


def test_unknown_trigger_type_is_a_422_listing_supported(run):
    """An unsupported trigger type -> 422 with the full supported list."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="bad-trigger-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            bad = {"trigger": {"type": "carrier_pigeon"}, "actions": []}
            with pytest.raises(AppError) as exc_info:
                await create_flow(session, scope, name="Bad", definition=bad)

            assert exc_info.value.status_code == 422
            assert "trigger.type:" in exc_info.value.detail
            assert "carrier_pigeon" in exc_info.value.detail
            for supported in SUPPORTED_TYPES:
                assert supported in exc_info.value.detail

    run(_scenario)


def test_unknown_action_type_is_a_422_with_the_path(run):
    """An unsupported action type -> 422 naming the actions path."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="bad-action-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            bad = {
                "trigger": {"type": "webhook_in"},
                "actions": [{"type": "smoke_signal"}],
            }
            with pytest.raises(AppError) as exc_info:
                await create_flow(session, scope, name="Bad", definition=bad)

            assert exc_info.value.status_code == 422
            assert "actions.0.type:" in exc_info.value.detail
            assert "smoke_signal" in exc_info.value.detail

    run(_scenario)


def test_set_enabled_toggles(run):
    """The enabled flag flips and persists."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="toggle-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            flow = await create_flow(session, scope, name="F", definition=VALID_DEFINITION)
            assert flow.enabled is True

            disabled = await set_enabled(session, scope, flow.id, False)
            await session.commit()
            assert disabled.enabled is False

            reloaded = await get_flow(session, scope, flow.id)
            assert reloaded.enabled is False

    run(_scenario)


def test_flows_are_scoped_between_organizations(run):
    """Org B cannot see or update org A's flow."""
    async def _scenario(factory):
        async with factory() as session:
            org_a = Organization(name="A", slug="flow-scope-a")
            org_b = Organization(name="B", slug="flow-scope-b")
            session.add_all([org_a, org_b])
            await session.commit()
            scope_a = OrgScope(session, org_a.id)
            scope_b = OrgScope(session, org_b.id)

            flow = await create_flow(session, scope_a, name="A flow", definition=VALID_DEFINITION)
            await session.commit()

            assert [f.id for f in await list_flows(session, scope_a)] == [flow.id]
            assert await list_flows(session, scope_b) == []
            assert await get_flow(session, scope_b, flow.id) is None
            assert await get_current_definition(session, scope_b, flow.id) is None
            assert await update_flow_definition(session, scope_b, flow.id, VALID_DEFINITION) is None

    run(_scenario)


def test_version_history_order_is_ascending(run):
    """History is ordered by version ascending across several updates."""
    async def _scenario(factory):
        async with factory() as session:
            organization = Organization(name="Org", slug="history-org")
            session.add(organization)
            await session.commit()
            scope = OrgScope(session, organization.id)

            flow = await create_flow(session, scope, name="F", definition=VALID_DEFINITION)
            for _ in range(3):
                await update_flow_definition(session, scope, flow.id, VALID_DEFINITION)
            await session.commit()

            history = await version_history(session, scope, flow.id)
            assert [v.version for v in history] == [1, 2, 3, 4]
            current = await get_current_definition(session, scope, flow.id)
            assert current.version == 4

    run(_scenario)
