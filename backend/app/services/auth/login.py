"""Login orchestration (C15): authenticate, pick the org, issue the pair.

The credential lookup is the trust boundary that ESTABLISHES an
organization context: users and their memberships are global rows, so they
cannot be read through OrgScope (C12) — the scope is what login creates for
the rest of the request. Everything after this module is scoped.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Membership, Organization, User
from app.services.audit import try_record_audit
from app.services.auth.password import verify_password
from app.services.auth.registration import AuthResult
from app.services.auth.tokens import TokenPair, issue_token_pair

INVALID_CREDENTIALS = "Invalid credentials"


def _invalid_credentials() -> AppError:
    """The single generic 401 used for every credential failure.

    The message is byte-identical for an unknown email and a wrong password,
    so the response cannot be used to probe which accounts exist.
    """
    return AppError(INVALID_CREDENTIALS, status_code=401, title=INVALID_CREDENTIALS)


async def login(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    secret: str,
) -> AuthResult:
    """Authenticate a user and issue a token pair for their oldest membership.

    The organization is the user's oldest membership (``min(created_at)``,
    id as tiebreak) — documented limitation until M2 adds org selection.

    Args:
        session: The session to work in.
        email: The user's email.
        password: The plaintext password to check.
        secret: Token signing secret (explicit; wired from Settings by the router).

    Returns:
        An :class:`AuthResult` with both tokens and both rows.

    Raises:
        app.core.errors.AppError: 401 with the generic message for unknown
            email, wrong password, or a user without any membership.
    """
    user = await session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(user.password_hash or "", password):
        raise _invalid_credentials()
    membership = await session.scalar(
        select(Membership)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at.asc(), Membership.id.asc())
        .limit(1)
    )
    if membership is None:
        raise _invalid_credentials()
    organization = await session.get(Organization, membership.organization_id)
    if organization is None:
        raise _invalid_credentials()
    await try_record_audit(
        session,
        organization_id=organization.id,
        actor_user_id=user.id,
        action="user.logged_in",
    )
    await session.commit()
    pair: TokenPair = issue_token_pair(user.id, organization.id, secret)
    return AuthResult(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        user=user,
        organization=organization,
    )
