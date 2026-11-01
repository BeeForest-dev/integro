"""Application settings loaded from the environment.

C01 contract: load and validate application settings from environment.
Reads process environment variables and an optional ``.env`` file only.
"""

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Immutable application settings, validated at construction time.

    Values are read from process environment variables first; variables not
    present there are read from a ``.env`` file in the working directory.

    Raises:
        pydantic.ValidationError: If a required variable is missing or a value
            has an invalid type. The error names the offending field, so the
            app refuses to start with a named error.

    Attributes:
        DATABASE_URL: PostgreSQL DSN for the async SQLAlchemy engine (required).
        REDIS_URL: Redis DSN used by Celery and the cache (required).
        SECRET_KEY: Secret key for signing tokens and encrypting connection
            secrets (required).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    DATABASE_URL: PostgresDsn
    REDIS_URL: str
    SECRET_KEY: str
