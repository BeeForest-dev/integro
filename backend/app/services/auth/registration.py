"""Registration orchestration (C15): organization + user + owner membership.

One transaction: a failure anywhere (e.g. a duplicate email after the
organization was inserted) rolls the whole registration back.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MembershipRole, Organization, User
from app.repositories.memberships import create_membership
from app.repositories.organizations import create_organization
from app.repositories.users import create_user
from app.services.audit import record_audit
from app.services.auth.password import hash_password
from app.services.auth.tokens import TokenPair, issue_token_pair


@dataclass(frozen=True)
class AuthResult:
    """Tokens plus the user/organization they belong to."""

    access_token: str
    refresh_token: str
    user: User
    organization: Organization


async def register(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    organization_name: str,
    organization_slug: str,
    secret: str,
) -> AuthResult:
    """Register a new organization with its owner user.

    Steps in one transaction: create the organization, create the user
    (a duplicate email rolls back the organization insert too), attach the
    owner membership, record the audit row, commit, then issue the token
    pair.

    Args:
        session: The session to work in.
        email: The new user's email.
        password: Plaintext password (hashed here).
        organization_name: The new organization's display name.
        organization_slug: The new organization's unique slug.
        secret: Token signing secret (explicit; wired from Settings by the router).

    Returns:
        An :class:`AuthResult` with both tokens and both rows.

    Raises:
        app.core.errors.AppError: 409 on duplicate slug or duplicate email.
        ValueError: If the password is empty.
    """
    organization = await create_organization(
        session, name=organization_name, slug=organization_slug
    )
    user = await create_user(session, email=email, password_hash=hash_password(password))
    await create_membership(
        session,
        user_id=user.id,
        organization_id=organization.id,
        role=MembershipRole.OWNER,
    )
    await record_audit(
        session,
        organization_id=organization.id,
        actor_user_id=user.id,
        action="user.registered",
    )
    await session.commit()
    pair: TokenPair = issue_token_pair(user.id, organization.id, secret)
    return AuthResult(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        user=user,
        organization=organization,
    )


def body_of(result: AuthResult) -> dict:
    """The API response body shared by register and login."""
    return {
        "access_token": result.access_token,
        "user": {"id": str(result.user.id), "email": result.user.email},
        "organization": {
            "id": str(result.organization.id),
            "name": result.organization.name,
            "slug": result.organization.slug,
        },
    }
