"""Password hashing and verification (C13).

Argon2id via argon2-cffi with its default parameters. Verification of a
malformed stored hash returns ``False`` instead of raising — an unparseable
hash simply never matches, so a corrupted row degrades to "login fails",
never to a 500.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerificationError

_hasher = PasswordHasher()


def _require_password(password: str) -> None:
    """Reject an empty password with a validation error."""
    if not password:
        raise ValueError("password must not be empty")


def hash_password(password: str) -> str:
    """Hash a password with argon2id (random salt per call).

    Args:
        password: The plaintext password to hash.

    Returns:
        The encoded argon2id hash string (safe to store in ``users.password_hash``).

    Raises:
        ValueError: If the password is empty.
    """
    _require_password(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a plaintext password against a stored argon2id hash.

    Args:
        password_hash: The encoded hash string, as returned by
            :func:`hash_password`. A malformed hash yields ``False``.
        password: The plaintext password to check.

    Returns:
        ``True`` only when the password matches the hash.

    Raises:
        ValueError: If the password is empty.
    """
    _require_password(password)
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHash):
        return False
