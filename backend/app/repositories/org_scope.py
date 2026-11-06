"""Organization scoping choke point (C12) — the anti-leak mechanism.

Every read query in the application must pass through :class:`OrgScope`.
The scope carries the organization id established by the authentication
layer; callers of repository methods never supply an org id themselves.

Enforced invariant: a statement executed through the scope must be a plain
SELECT that selects from exactly one entity, contains no ``OR`` conditions,
and pins that entity's ``organization_id`` to exactly this scope. Anything
else — no filter, a different org id, an ``OR`` branch, a ``UNION``, a raw
``text()`` clause, a second selected entity — is rejected with
:class:`ScopeError` before the statement reaches the database.

These restrictions are deliberate: false rejections of exotic-but-honest
queries are visible (ScopeError) and fixable by splitting the query, while
a false acceptance in an anti-leak mechanism is silent and fatal. An
``OR`` of two org pins in particular would launder a cross-tenant read
through the scope's own filter, so it is banned outright.
"""

import uuid
from typing import Any, TypeVar

from sqlalchemy import Column, Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList

from app.core.errors import AppError

_Model = TypeVar("_Model", bound=DeclarativeBase)


class ScopeError(AppError):
    """A query attempted to run without (or with a foreign) organization scope.

    This is a programming error, not a client error: it surfaces as a
    generic 500 through the C03 problem-details handlers.
    """

    title = "Scope Error"


def _pinned_org_column(statement: Select, organization_id: uuid.UUID) -> Column | None:
    """Return the organization_id column pinned to this scope, or None.

    Only plain equality is accepted, in either operand order; IN lists and
    OR-ed branches never reach this function (rejected earlier).
    """
    whereclause = statement.whereclause
    if whereclause is None:
        return None
    for element in visitors.iterate(whereclause):
        if not isinstance(element, BinaryExpression) or element.operator is not operators.eq:
            continue
        for column, value in ((element.left, element.right), (element.right, element.left)):
            if (
                isinstance(column, Column)
                and column.name == "organization_id"
                and isinstance(value, BindParameter)
                and value.value == organization_id
            ):
                return column
    return None


def _contains_or(whereclause: Any) -> bool:
    """True when the WHERE clause contains an OR branch anywhere."""
    if whereclause is None:
        return False
    for element in visitors.iterate(whereclause):
        if (
            isinstance(element, BooleanClauseList)
            and element.operator is operators.or_
        ):
            return True
    return False


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

        This is the choke point. The enforced invariant (see the module
        docstring) is checked before the statement reaches the database;
        any violation raises ScopeError instead of executing.

        Raises:
            ScopeError: If the statement is not a single-entity SELECT
                without OR branches, pinned to this organization.
        """
        self._assert_scoped(statement)
        return await self._session.execute(statement)

    def _assert_scoped(self, statement: Any) -> None:
        """Enforce the module invariant, raising ScopeError on any violation."""
        if not isinstance(statement, Select):
            raise ScopeError("only plain SELECT statements pass through the organization scope")
        if _contains_or(statement.whereclause):
            raise ScopeError("OR conditions are not allowed in a scoped query")
        froms = statement.get_final_froms()
        if len(froms) != 1:
            raise ScopeError("a scoped query must select from exactly one entity")
        pinned = _pinned_org_column(statement, self.organization_id)
        if pinned is None:
            raise ScopeError("query attempted without organization scope")
        if pinned.table is not froms[0]:
            raise ScopeError("organization scope must pin the selected entity")

    @staticmethod
    def _org_column(model: type[_Model]) -> Column:
        """Return the model's organization_id column or raise ScopeError."""
        table = model.metadata.tables[model.__tablename__]
        column = table.columns.get("organization_id")
        if column is None:
            raise ScopeError(f"{table.name} has no organization_id column")
        return column
