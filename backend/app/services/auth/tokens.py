"""Access/refresh token issuing and verification (C14).

Compact JWTs signed with HS256. The header is fixed byte-for-byte, so no
algorithm negotiation exists and ``alg=none`` is impossible by construction.
Signing uses cryptography's hazmat HMAC-SHA256; comparison uses
``hmac.compare_digest`` (constant time). The secret is an explicit
parameter — wiring ``Settings.SECRET_KEY`` in is C15's job, which keeps this
module pure and side-effect free.

No role claim is ever put into a token: roles come from the database
membership, never from something the client can present.
"""

import base64
import binascii
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.hmac import HMAC

ISSUER = "integro"
AUDIENCE = "integro-api"
ACCESS_TOKEN_TTL_SECONDS = 900
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60

# Fixed header: {"alg":"HS256","typ":"JWT"} — serialized once, byte-for-byte.
_HEADER_JSON = b'{"alg":"HS256","typ":"JWT"}'


class TokenError(Exception):
    """Base class for token verification failures."""


class TokenExpired(TokenError):
    """The token's ``exp`` is at or before the verification time."""


class TokenInvalid(TokenError):
    """The token is malformed, mis-signed, or carries wrong claims."""


@dataclass(frozen=True)
class TokenPair:
    """A freshly issued access + refresh token pair."""

    access_token: str
    refresh_token: str


def _b64url_encode(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _signature(signing_input: bytes, secret: str) -> bytes:
    signer = HMAC(secret.encode("utf-8"), hashes.SHA256())
    signer.update(signing_input)
    return signer.finalize()


def _encode_token(claims: dict[str, Any], secret: str) -> str:
    """Build a signed compact JWT from raw claims (used by tests too)."""
    payload_b64 = _b64url_encode(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )
    signing_input = _b64url_encode(_HEADER_JSON) + b"." + payload_b64
    signature_b64 = _b64url_encode(_signature(signing_input, secret))
    return signing_input.decode("ascii") + "." + signature_b64.decode("ascii")


def issue_token_pair(
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    secret: str,
    now: float | None = None,
) -> TokenPair:
    """Issue a signed access + refresh token pair for one user in one org.

    Args:
        user_id: The user the tokens identify (``sub`` claim).
        organization_id: The organization context (``org`` claim).
        secret: The HMAC secret (explicit; C15 wires ``Settings.SECRET_KEY``).
        now: Issuance time as a Unix timestamp (defaults to ``time.time()``;
            injectable for deterministic tests).

    Returns:
        A :class:`TokenPair` with both tokens carrying ``iat``/``exp``.
    """
    issued_at = int(time.time() if now is None else now)
    base_claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(user_id),
        "org": str(organization_id),
        "iat": issued_at,
    }
    access = _encode_token(
        {
            **base_claims,
            "typ": "access",
            "exp": issued_at + ACCESS_TOKEN_TTL_SECONDS,
        },
        secret,
    )
    refresh = _encode_token(
        {
            **base_claims,
            "typ": "refresh",
            "exp": issued_at + REFRESH_TOKEN_TTL_SECONDS,
        },
        secret,
    )
    return TokenPair(access_token=access, refresh_token=refresh)


def _verify(
    token: str, secret: str, expected_type: str, now: float | None = None
) -> dict[str, Any]:
    """Shared verification core; see verify_access_token for the contract."""
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenInvalid("a token must have exactly three parts")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header_raw = header_b64.encode("ascii", "strict")
        payload_raw = payload_b64.encode("ascii", "strict")
        signature_raw = signature_b64.encode("ascii", "strict")
    except UnicodeEncodeError as exc:
        raise TokenInvalid("token segments must be ASCII") from exc
    if header_raw != _b64url_encode(_HEADER_JSON):
        raise TokenInvalid("unexpected token header")
    expected = _b64url_encode(_signature(header_raw + b"." + payload_raw, secret))
    if not hmac.compare_digest(expected, signature_raw):
        raise TokenInvalid("signature mismatch")
    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise TokenInvalid("undecodable payload") from exc
    if not isinstance(claims, dict):
        raise TokenInvalid("payload is not an object")
    if claims.get("iss") != ISSUER or claims.get("aud") != AUDIENCE:
        raise TokenInvalid("wrong issuer or audience")
    if claims.get("typ") != expected_type:
        raise TokenInvalid("wrong token type")
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        raise TokenInvalid("missing or malformed exp")
    if exp <= (time.time() if now is None else now):
        raise TokenExpired("token has expired")
    if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("org"), str):
        raise TokenInvalid("missing subject or organization")
    return claims


def verify_access_token(token: str, secret: str, now: float | None = None) -> dict[str, Any]:
    """Verify an access token and return its claims.

    Raises:
        TokenExpired: If ``exp`` is at or before the verification time.
        TokenInvalid: For anything else malformed or wrong (bad structure,
            header, signature, issuer, audience, type, missing ``exp``).
    """
    return _verify(token, secret, "access", now)


def verify_refresh_token(token: str, secret: str, now: float | None = None) -> dict[str, Any]:
    """Verify a refresh token and return its claims (same rules as access)."""
    return _verify(token, secret, "refresh", now)
