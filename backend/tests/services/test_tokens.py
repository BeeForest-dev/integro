"""Tests for C14 services.auth.tokens — one test per contract error case.

No database needed: the secret is an explicit parameter everywhere.
"""

import base64
import json
import uuid

import pytest

from app.services.auth.tokens import (
    ACCESS_TOKEN_TTL_SECONDS,
    REFRESH_TOKEN_TTL_SECONDS,
    TokenExpired,
    TokenInvalid,
    _encode_token,
    _signature,
    issue_token_pair,
    verify_access_token,
    verify_refresh_token,
)

SECRET = "test-secret-key-for-c14"
OTHER_SECRET = "another-secret-entirely"
NOW = 1_800_000_000


def _claims(**overrides):
    base = {
        "iss": "integro",
        "aud": "integro-api",
        "sub": str(uuid.uuid4()),
        "org": str(uuid.uuid4()),
        "typ": "access",
        "iat": NOW,
        "exp": NOW + ACCESS_TOKEN_TTL_SECONDS,
    }
    base.update(overrides)
    return base


def test_issue_and_verify_roundtrip():
    """Issued tokens verify and carry the expected claims."""
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()

    pair = issue_token_pair(user_id, organization_id, SECRET, now=NOW)

    access_claims = verify_access_token(pair.access_token, SECRET, now=NOW + 10)
    assert access_claims["sub"] == str(user_id)
    assert access_claims["org"] == str(organization_id)
    assert access_claims["typ"] == "access"
    assert access_claims["iat"] == NOW
    assert access_claims["exp"] == NOW + ACCESS_TOKEN_TTL_SECONDS

    refresh_claims = verify_refresh_token(pair.refresh_token, SECRET, now=NOW + 10)
    assert refresh_claims["typ"] == "refresh"
    assert refresh_claims["exp"] == NOW + REFRESH_TOKEN_TTL_SECONDS


def test_access_refresh_cross_rejection():
    """An access token is not a refresh token and vice versa."""
    pair = issue_token_pair(uuid.uuid4(), uuid.uuid4(), SECRET, now=NOW)

    with pytest.raises(TokenInvalid):
        verify_refresh_token(pair.access_token, SECRET, now=NOW + 10)
    with pytest.raises(TokenInvalid):
        verify_access_token(pair.refresh_token, SECRET, now=NOW + 10)


def test_tampered_payload_is_rejected():
    """Flipping one payload character breaks the signature."""
    pair = issue_token_pair(uuid.uuid4(), uuid.uuid4(), SECRET, now=NOW)
    header, payload, signature = pair.access_token.split(".")
    flipped = ("A" if payload[0] != "A" else "B") + payload[1:]
    tampered = ".".join([header, flipped, signature])

    with pytest.raises(TokenInvalid):
        verify_access_token(tampered, SECRET, now=NOW + 10)


def test_tampered_signature_is_rejected():
    """A forged signature fails the constant-time comparison."""
    pair = issue_token_pair(uuid.uuid4(), uuid.uuid4(), SECRET, now=NOW)
    header, payload, signature = pair.access_token.split(".")
    forged = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = ".".join([header, payload, forged])

    with pytest.raises(TokenInvalid):
        verify_access_token(tampered, SECRET, now=NOW + 10)


def test_wrong_secret_is_rejected():
    """A token signed by another secret verifies as invalid."""
    pair = issue_token_pair(uuid.uuid4(), uuid.uuid4(), SECRET, now=NOW)

    with pytest.raises(TokenInvalid):
        verify_access_token(pair.access_token, OTHER_SECRET, now=NOW + 10)


def test_expired_token_raises_token_expired():
    """exp <= now raises TokenExpired (token built with a past exp)."""
    claims = _claims(exp=NOW - 1)
    expired = _encode_token(claims, SECRET)

    with pytest.raises(TokenExpired):
        verify_access_token(expired, SECRET, now=NOW)


def test_missing_exp_is_rejected():
    """A token without exp is invalid even if everything else is right."""
    claims = _claims()
    del claims["exp"]
    token = _encode_token(claims, SECRET)

    with pytest.raises(TokenInvalid):
        verify_access_token(token, SECRET, now=NOW + 10)


def test_wrong_audience_or_issuer_is_rejected():
    """Exact iss/aud matching: one wrong claim -> TokenInvalid."""
    wrong_audience = _encode_token(_claims(aud="other-api"), SECRET)
    with pytest.raises(TokenInvalid):
        verify_access_token(wrong_audience, SECRET, now=NOW + 10)
    wrong_issuer = _encode_token(_claims(iss="other-issuer"), SECRET)
    with pytest.raises(TokenInvalid):
        verify_access_token(wrong_issuer, SECRET, now=NOW + 10)


def test_alg_none_token_is_rejected():
    """A foreign header is rejected even with a signature valid FOR that header."""
    none_header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(
        json.dumps(_claims()).encode("utf-8")
    ).rstrip(b"=")
    signing_input = none_header + b"." + payload
    valid_for_that_header = base64.urlsafe_b64encode(
        _signature(signing_input, SECRET)
    ).rstrip(b"=")
    token = signing_input.decode() + "." + valid_for_that_header.decode()

    with pytest.raises(TokenInvalid):
        verify_access_token(token, SECRET, now=NOW + 10)


def test_garbage_string_is_rejected():
    """A non-token string raises TokenInvalid, not something else."""
    with pytest.raises(TokenInvalid):
        verify_access_token("not.a.jwt.at.all", SECRET, now=NOW)
    with pytest.raises(TokenInvalid):
        verify_access_token("total garbage", SECRET, now=NOW)
