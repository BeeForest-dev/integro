"""Authentication and RBAC dependencies (C16).

Shared guards for protected routes: bearer-token verification, membership
resolution through the organization scope (C12), and explicit role checks.
The role always comes from the membership row in the database — never from
anything the client presents.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.engine import get_session
from app.models import Membership, MembershipRole
from app.repositories.org_scope import OrgScope
from app.services.auth.tokens import TokenError, verify_access_token

INVALID_CREDENTIALS = "Invalid credentials"


def get_settings() -> Settings:
    """Per-request settings (env-backed); the secret is wired from here."""
    return Settings()  # type: ignore[call-arg]


def _invalid_credentials() -> AppError:
    """The generic 401 used for every token problem (same wording as C15)."""
    return AppError(INVALID_CREDENTIALS, status_code=401, title=INVALID_CREDENTIALS)


def _bearer_token(request: Request) -> str:
    """Extract the bearer token, rejecting anything else as generic 401."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not token:
        raise _invalid_credentials()
    return token


def get_current_claims(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Verify the bearer access token and return its claims.

    Raises:
        app.core.errors.AppError: 401 with the generic message for a missing
            or malformed header, an invalid signature, a wrong token type
            (refresh presented as access) or an expired token.
    """
    token = _bearer_token(request)
    try:
        return verify_access_token(token, settings.SECRET_KEY)
    except TokenError:
        raise _invalid_credentials() from None


async def get_current_membership(
    request: Request,
    claims: Annotated[dict[str, Any], Depends(get_current_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Membership:
    """Resolve the caller's membership in the token's organization.

    The lookup runs through :class:`OrgScope` (C12); a missing membership is
    a 403 with a generic message, never a 404, so the response cannot be
    used to probe which organizations exist.

    Raises:
        app.core.errors.AppError: 401 for token problems; 403 when the user
            has no membership in the token's organization.
    """
    try:
        user_id = uuid.UUID(claims["sub"])
        organization_id = uuid.UUID(claims["org"])
    except (ValueError, KeyError):
        raise _invalid_credentials() from None
    scope = OrgScope(session, organization_id)
    membership = await scope.first(
        scope.query(Membership).where(Membership.user_id == user_id)
    )
    if membership is None:
        raise AppError(
            "no membership in this organization", status_code=403, title="Forbidden"
        )
    return membership


def require_roles(*allowed: MembershipRole) -> Callable[..., Any]:
    """Build a route dependency allowing exactly the given roles.

    No role hierarchy, no prebuilt role constants — the allowed set is the
    explicit argument, so every route states its own requirement.

    Args:
        allowed: The roles permitted through (e.g. ``require_roles(OWNER,
            ADMIN)``).

    Returns:
        A FastAPI dependency rejecting any caller whose membership role is
        outside ``allowed`` with 403 and the required roles in the detail.
    """

    allowed_set = frozenset(allowed)
    required = ", ".join(sorted(role.value for role in allowed_set))

    async def role_guard(
        membership: Annotated[Membership, Depends(get_current_membership)],
    ) -> Membership:
        if membership.role not in allowed_set:
            raise AppError(
                f"requires one of: {required}",
                status_code=403,
                title="Forbidden",
            )
        return membership

    return role_guard
