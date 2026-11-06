"""Organization scoping choke point (C12) — the anti-leak mechanism.

Every read query in the application must pass through :class:`OrgScope`.
The scope carries the organization id established by the authentication
layer; callers of repository methods never supply an org id themselves.
A query that does not pin ``organization_id`` to exactly this scope is
rejected with :class:`ScopeError` instead of being executed — an unscoped
query can never return cross-tenant rows because it never runs.

Scope matching is deliberately strict and simple: a statement must contain
an equality ``organization_id = <this scope's org id>``. Anything else —
no filter, a different org id, an ``IN`` list, a model without the column —
is rejected. That is the trade-off: false rejections of exotic-but-honest
queries are visible (ScopeError) and fixable, while a false acceptance
would be silent and fatal.
"""

import uuid
from typing import Any, TypeVar

from sqlalchemy import Column, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter

from app.core.errors import AppError

_Model = TypeVar("_Model", bound=DeclarativeBase)


class ScopeError(AppError):
    """A query attempted to run without (or with a foreign) organization scope.

    This is a programming error, not a client error: it surfaces as a
    generic 500 through the C03 problem-details handlers.
    """

    title = "Scope Error"


def _pins_organization_id(statement: Select, organization_id: uuid.UUID) -> bool:
    """True when the WHERE clause pins organization_id to exactly organization_id.

    Only plain equality is accepted, in either operand order. Anything more
    exotic (IN lists, OR-ed branches) is rejected on purpose.
    """
    whereclause = statement.whereclause
    if whereclause is None:
        return False
    pinned = False
    for element in visitors.iterate(whereclause):
        if pinned or not isinstance(element, BinaryExpression):
            continue
        if element.operator is not operators.eq:
            continue
        left, right = element.left, element.right
        for column, value in ((left, right), (right, left)):
            if (
                isinstance(column, Column)
                and column.name == "organization_id"
                and isinstance(value, BindParameter)
                and value.value == organization_id
            ):
                pinned = True
                break
    return pinned


class OrgScope:
    """Binds every query executed through it to one organization.

    Construct this from the authenticated membership once per request; pass
    the scope — never a bare organization id — to repository methods.

    Args:
        session: The session queries run through.
        organization_id: The organization this scope is restricted to.

    Raises:
        ScopeError: If ``organization_id`` is missing.
    """

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID) -> None:
        if organization_id is None:
            raise ScopeError("organization scope is required")
        self._session = session
        self.organization_id = organization_id

    def query(self, model: type[_Model]) -> Select:
        """Build a SELECT pre-scoped to this organization.

        Raises:
            ScopeError: If the model has no ``organization_id`` column
                (e.g. ``User`` or ``Organization`` itself — those cannot be
                scoped and must not be queried through this choke point).
        """
        column = self._org_column(model)
        return select(model).where(column == self.organization_id)

    async def get(self, model: type[_Model], row_id: Any) -> _Model | None:
        """Fetch one row by primary key, but only inside this organization.

        Returns ``None`` when the row belongs to another organization — a
        cross-tenant id must be indistinguishable from a missing row here.
        """
        table = model.metadata.tables[model.__tablename__]
        statement = self.query(model).where(table.columns["id"] == row_id)
        return await self.first(statement)

    async def all(self, statement: Select) -> list[Any]:
        """Run a scoped statement and return all rows as a list."""
        result = await self.execute(statement)
        return list(result.scalars().all())

    async def first(self, statement: Select) -> Any:
        """Run a scoped statement and return the first row (or ``None``)."""
        result = await self.execute(statement)
        return result.scalars().first()

    async def execute(self, statement: Select) -> Any:
        """Run a SELECT after proving it is scoped to this organization.

        This is the choke point: any statement that does not pin
        ``organization_id`` to exactly this scope is rejected before it
        reaches the database.

        Raises:
            ScopeError: If the statement is not scoped to this organization.
        """
        if not _pins_organization_id(statement, self.organization_id):
            raise ScopeError("query attempted without organization scope")
        return await self._session.execute(statement)

    @staticmethod
    def _org_column(model: type[_Model]) -> Column:
        """Return the model's organization_id column or raise ScopeError."""
        table = model.metadata.tables[model.__tablename__]
        column = table.columns.get("organization_id")
        if column is None:
            raise ScopeError(f"{table.name} has no organization_id column")
        return column
