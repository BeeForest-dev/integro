"""Tests for C13 services.auth.password — one test per contract error case.

The PG-backed test proves the C11 standing requirement: the password_hash
column (migration 0005) exists and round-trips a real argon2id hash.
"""

import asyncio
import os
from pathlib import Path

import pytest
from sqlalchemy import delete, inspect, select

from app.db.engine import create_engine, create_session_factory
from app.models import User
from app.services.auth.password import hash_password, verify_password

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set - these tests require a real PostgreSQL")
    return url


def test_hash_produces_argon2id_and_verifies():
    """hash_password yields an argon2id string; verify_password confirms it."""
    password_hash = hash_password("correct horse battery staple")

    assert password_hash.startswith("$argon2id$")
    assert verify_password(password_hash, "correct horse battery staple") is True


def test_hash_uses_a_random_salt():
    """Two hashes of the same password differ."""
    assert hash_password("same-password") != hash_password("same-password")


def test_wrong_password_returns_false():
    """A mismatched password verifies as False, no exception."""
    password_hash = hash_password("right")

    assert verify_password(password_hash, "wrong") is False


@pytest.mark.parametrize("malformed", ["not-a-hash", "", "$argon2id$broken"])
def test_invalid_hash_returns_false(malformed):
    """A malformed stored hash yields False, never an exception."""
    assert verify_password(malformed, "any-password") is False


def test_empty_password_hash_is_a_validation_error():
    """hash_password("") raises ValueError (contract: empty password -> validation error)."""
    with pytest.raises(ValueError, match="password must not be empty"):
        hash_password("")


def test_empty_password_verify_is_a_validation_error():
    """verify_password with an empty password raises ValueError too."""
    password_hash = hash_password("real-password")

    with pytest.raises(ValueError, match="password must not be empty"):
        verify_password(password_hash, "")


def test_password_hash_column_roundtrips_on_real_postgres():
    """users.password_hash persists and verifies end to end (C11 standing requirement)."""
    async def _scenario():
        engine = create_engine(_database_url())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                await session.execute(delete(User))
                await session.commit()

            password_hash = hash_password("s3cret passphrase")

            async with factory() as session:
                user = User(email="carol@example.com", password_hash=password_hash)
                session.add(user)
                await session.commit()
                user_id = user.id

            async with factory() as session:
                stored = await session.scalar(select(User).where(User.id == user_id))
                assert stored is not None
                assert stored.password_hash == password_hash
                assert verify_password(stored.password_hash, "s3cret passphrase") is True

            async with engine.connect() as connection:
                columns = await connection.run_sync(
                    lambda conn: {c["name"] for c in inspect(conn).get_columns("users")}
                )
                assert "password_hash" in columns
        finally:
            await engine.dispose()

    asyncio.run(_scenario())
