"""Async Redis client lifecycle and health probe.

C06 contract: ``/ready`` checks Redis. The client is created from the
environment-provided URL at application startup and reused by every probe
(one ``PING`` per check, no per-request connection cost).
"""

from redis.asyncio import Redis

_client: Redis | None = None


def init_redis(url: str) -> None:
    """Initialise the module-level Redis client.

    Args:
        url: Redis DSN, e.g. ``redis://host:6379/0``.
    """
    global _client
    _client = Redis.from_url(url, decode_responses=True)


async def dispose_redis() -> None:
    """Close the client connection pool and reset the module-level state."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def check_redis() -> None:
    """Probe Redis with ``PING``.

    Raises:
        RuntimeError: If ``init_redis()`` was not called first.
        Exception: Whatever the ``PING`` raises (refused connection, timeout,
            protocol error) — callers map any failure to "not ready".
    """
    if _client is None:
        raise RuntimeError("redis not initialised — call init_redis() first")
    await _client.ping()
