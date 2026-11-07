"""Authentication endpoints (C15): register, login, refresh, me.

The router is thin: it parses HTTP, delegates orchestration to the services
layer, and serializes responses. The refresh token travels only in the
httpOnly ``integro_refresh`` cookie; the access token only in response
bodies and the ``Authorization: Bearer`` header.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.engine import get_session
from app.models import Membership, Organization, User
from app.repositories.org_scope import OrgScope
from app.services.auth import login as login_service
from app.services.auth import registration as registration_service
from app.services.auth.login import INVALID_CREDENTIALS
from app.services.auth.tokens import (
    REFRESH_TOKEN_TTL_SECONDS,
    TokenError,
    issue_token_pair,
    verify_access_token,
    verify_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_REFRESH_COOKIE = "integro_refresh"


class RegisterPayload(BaseModel):
    """Body of POST /auth/register."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)
    organization_name: str = Field(min_length=1)
    organization_slug: str = Field(min_length=1)


class LoginPayload(BaseModel):
    """Body of POST /auth/login."""

    email: str = Field(min_length=1)
    password: str = Field(min_length=1)


def get_settings() -> Settings:
    """Per-request settings (env-backed); the router wires the secret down."""
    return Settings()  # type: ignore[call-arg]


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attach the rotated refresh token as the httpOnly cookie."""
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        max_age=REFRESH_TOKEN_TTL_SECONDS,
        path="/auth",
        secure=False,  # local demo over http; M5 may flip via settings
        httponly=True,
        samesite="lax",
    )


def _invalid_credentials() -> AppError:
    """Generic 401, byte-identical for every credential failure."""
    return AppError(INVALID_CREDENTIALS, status_code=401, title=INVALID_CREDENTIALS)


def _bearer_token(request: Request) -> str:
    """Extract the bearer token, rejecting anything else as generic 401."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not token:
        raise _invalid_credentials()
    return token


@router.post("/register")
async def register(
    payload: RegisterPayload,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Create an organization with its owner user and return a token pair."""
    result = await registration_service.register(
        session,
        email=payload.email,
        password=payload.password,
        organization_name=payload.organization_name,
        organization_slug=payload.organization_slug,
        secret=settings.SECRET_KEY,
    )
    _set_refresh_cookie(response, result.refresh_token)
    return registration_service.body_of(result)


@router.post("/login")
async def login(
    payload: LoginPayload,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Authenticate and return a token pair for the oldest membership."""
    result = await login_service.login(
        session,
        email=payload.email,
        password=payload.password,
        secret=settings.SECRET_KEY,
    )
    _set_refresh_cookie(response, result.refresh_token)
    return registration_service.body_of(result)


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Rotate the pair: the httpOnly cookie in, a fresh pair out.

    Only the cookie is read — a refresh token in the request body is never
    accepted (passing a body token without the cookie still yields 401).
    """
    presented = request.cookies.get(_REFRESH_COOKIE)
    if presented is None:
        raise _invalid_credentials()
    try:
        claims = verify_refresh_token(presented, settings.SECRET_KEY)
        user_id = uuid.UUID(claims["sub"])
        organization_id = uuid.UUID(claims["org"])
    except (TokenError, ValueError, KeyError):
        raise _invalid_credentials() from None

    organization = await session.get(Organization, organization_id)
    user = await session.get(User, user_id)
    if organization is None or user is None:
        raise _invalid_credentials()

    pair = issue_token_pair(user.id, organization.id, settings.SECRET_KEY)
    _set_refresh_cookie(response, pair.refresh_token)
    return {
        "access_token": pair.access_token,
        "user": {"id": str(user.id), "email": user.email},
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "slug": organization.slug,
        },
    }


@router.get("/me")
async def me(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Return the caller's user, organization and role for the token's org.

    The role is read from the membership THROUGH OrgScope (C12) with the
    organization from the verified access token — never from the token.
    """
    token = _bearer_token(request)
    try:
        claims = verify_access_token(token, settings.SECRET_KEY)
        user_id = uuid.UUID(claims["sub"])
        organization_id = uuid.UUID(claims["org"])
    except (TokenError, ValueError, KeyError):
        raise _invalid_credentials() from None

    scope = OrgScope(session, organization_id)
    membership = await scope.first(
        scope.query(Membership).where(Membership.user_id == user_id)
    )
    if membership is None:
        raise AppError(
            "no membership in this organization", status_code=403, title="Forbidden"
        )
    user = await session.get(User, user_id)
    organization = await session.get(Organization, organization_id)
    if user is None or organization is None:
        raise _invalid_credentials()
    return {
        "user": {"id": str(user.id), "email": user.email},
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "slug": organization.slug,
        },
        "role": membership.role.value,
    }
