"""Tests for C01 core.config — one test per contract error case."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REQUIRED_VARS = ("DATABASE_URL", "REDIS_URL", "SECRET_KEY")

VALID_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/integro",
    "REDIS_URL": "redis://localhost:6379/0",
    "SECRET_KEY": "test-secret-key",
}


@pytest.fixture
def valid_env(monkeypatch):
    """Provide valid values for all required settings vars."""
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


@pytest.fixture(autouse=True)
def clean_required_vars(monkeypatch):
    """Ensure required vars do not leak in from the real environment."""
    for name in REQUIRED_VARS:
        monkeypatch.delenv(name, raising=False)


def test_loads_settings_from_environment(valid_env):
    """Settings are built from environment variables."""
    settings = Settings()

    assert str(settings.DATABASE_URL) == VALID_ENV["DATABASE_URL"]
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.SECRET_KEY == "test-secret-key"


def test_loads_settings_from_env_file(tmp_path, monkeypatch):
    """Variables missing in the environment fall back to the .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/integro\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "SECRET_KEY=file-secret-key\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.SECRET_KEY == "file-secret-key"
    assert str(settings.DATABASE_URL) == VALID_ENV["DATABASE_URL"]


@pytest.mark.parametrize("missing_var", REQUIRED_VARS)
def test_missing_required_var_raises_named_error(valid_env, missing_var):
    """Missing required var -> ValidationError naming the field."""
    valid_env.delenv(missing_var)

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert missing_var in str(exc_info.value)


def test_invalid_database_url_raises_named_error(valid_env):
    """Invalid type (DATABASE_URL="foo") -> validation error naming the field."""
    valid_env.setenv("DATABASE_URL", "foo")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert "DATABASE_URL" in str(exc_info.value)


def test_settings_is_immutable(valid_env):
    """The Settings object is immutable: assignment raises ValidationError."""
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.SECRET_KEY = "other-secret"
