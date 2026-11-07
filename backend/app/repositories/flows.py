"""Flow persistence (C20) — OrgScope-first, definitions validated before write.

Every read goes through :class:`OrgScope` (C12); the scope stamps new rows
with its organization id. A flow's definition is validated against the
:class:`FlowDefinition` schema BEFORE any insert — a bad definition raises
a 422 problem-details error naming the exact JSON path, never a database
error or a half-written flow.
"""

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Flow, FlowVersion
from app.repositories.org_scope import OrgScope
from app.schemas.flow_definition import FlowDefinition


def _validated_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw definition dict, raising AppError 422 on the first failure.

    The detail carries the JSON path of the first failing field, e.g.
    ``"trigger.type: unsupported type 'carrier_pigeon' (supported: ...)"``.
    """
    try:
        return FlowDefinition.model_validate(definition).model_dump()
    except ValidationError as exc:
        first = exc.errors()[0]
        path = ".".join(str(part) for part in first["loc"])
        raise AppError(
            f"{path}: {first['msg']}",
            status_code=422,
            title="Validation Failed",
        ) from exc


async def create_flow(
    session: AsyncSession,
    scope: OrgScope,
    *,
    name: str,
    definition: dict[str, Any],
) -> Flow:
    """Create a flow with its first version in one transaction.

    Args:
        session: The session to insert through.
        scope: The organization scope (C12) — its org id stamps the row.
        name: Human-readable flow name.
        definition: The raw flow definition dict (validated before insert).

    Returns:
        The persisted ``Flow`` (version 1 lives in ``flow_versions``).

    Raises:
        app.core.errors.AppError: 422 with the failing JSON path when the
            definition is invalid.
    """
    validated = _validated_definition(definition)
    flow = Flow(organization_id=scope.organization_id, name=name)
    session.add(flow)
    await session.flush()
    session.add(FlowVersion(flow_id=flow.id, version=1, definition=validated))
    await session.flush()
    return flow


async def update_flow_definition(
    session: AsyncSession,
    scope: OrgScope,
    flow_id: uuid.UUID,
    definition: dict[str, Any],
) -> FlowVersion | None:
    """Append the next version of a flow's definition (max + 1).

    The flow must belong to the scope's organization; otherwise ``None``.

    Raises:
        app.core.errors.AppError: 422 on an invalid definition.
    """
    flow = await scope.get(Flow, flow_id)
    if flow is None:
        return None
    validated = _validated_definition(definition)
    latest = await get_current_definition(session, scope, flow_id)
    next_version = (latest.version + 1) if latest is not None else 1
    version = FlowVersion(flow_id=flow_id, version=next_version, definition=validated)
    session.add(version)
    await session.flush()
    await session.refresh(version)
    return version


async def set_enabled(
    session: AsyncSession, scope: OrgScope, flow_id: uuid.UUID, enabled: bool
) -> Flow | None:
    """Toggle whether a flow may be triggered; returns the row (or None)."""
    flow = await scope.get(Flow, flow_id)
    if flow is None:
        return None
    flow.enabled = enabled
    await session.flush()
    return flow


async def get_flow(
    session: AsyncSession, scope: OrgScope, flow_id: uuid.UUID
) -> Flow | None:
    """Fetch one flow by id, only inside the scope's organization."""
    return await scope.get(Flow, flow_id)


async def list_flows(session: AsyncSession, scope: OrgScope) -> list[Flow]:
    """Return all flows of the scope's organization."""
    return await scope.all(scope.query(Flow))


async def version_history(
    session: AsyncSession, scope: OrgScope, flow_id: uuid.UUID
) -> list[FlowVersion]:
    """Return all versions of a flow, ordered by version ascending.

    ``FlowVersion`` has no organization_id column, so it cannot be scoped
    directly; ownership is proven first by resolving the flow through the
    scope, and only then is the (implicitly scoped) per-flow query run on
    the raw session — the same trust-boundary pattern as the auth lookup.
    """
    flow = await scope.get(Flow, flow_id)
    if flow is None:
        return []
    statement = (
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.version.asc())
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def get_current_definition(
    session: AsyncSession, scope: OrgScope, flow_id: uuid.UUID
) -> FlowVersion | None:
    """Return the latest version row: the definition at max(version)."""
    history = await version_history(session, scope, flow_id)
    return history[-1] if history else None
