"""Encryption of connection secrets at rest (C17).

Fernet (AES-128-CBC + HMAC) with a key derived from ``Settings.SECRET_KEY``
via HKDF-SHA256 — the same env var that signs tokens, separated by key
derivation (info ``b"integro-connection-secrets-v1"``), so a second secret
variable is not needed. Derivation runs per call: it is cheap and keeps the
module stateless. There is no key versioning — a single derived key; key
rotation is a future operational concern.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_KEY_INFO = b"integro-connection-secrets-v1"
_DECRYPTION_FAILED = "decryption failed"


class CryptoError(Exception):
    """The single failure type for decryption.

    Raised for a wrong key, a tampered ciphertext or any malformed input.
    Callers must treat it as "no plaintext" — the module never returns
    partial plaintext and never reveals which key was tried.
    """


def _derive_key(secret: str) -> bytes:
    """Derive the urlsafe-b64 Fernet key from the application secret."""
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_KEY_INFO)
    return base64.urlsafe_b64encode(hkdf.derive(secret.encode("utf-8")))


def encrypt(plaintext: str, secret: str) -> str:
    """Encrypt a connection secret for storage.

    Args:
        plaintext: The secret to protect.
        secret: The application secret (``Settings.SECRET_KEY`` at the edge).

    Returns:
        The urlsafe Fernet token, or the empty string for empty input.
    """
    if not plaintext:
        return ""
    return Fernet(_derive_key(secret)).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str, secret: str) -> str:
    """Decrypt a stored connection secret.

    Args:
        ciphertext: A token produced by :func:`encrypt`.
        secret: The application secret the token was encrypted with.

    Returns:
        The original plaintext, or the empty string for empty input.

    Raises:
        CryptoError: For a wrong key, tampered ciphertext or malformed input
            — never any other exception type, never partial plaintext.
    """
    if not ciphertext:
        return ""
    try:
        plaintext = Fernet(_derive_key(secret)).decrypt(ciphertext.encode("ascii"))
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise CryptoError(_DECRYPTION_FAILED) from exc
    return plaintext.decode("utf-8")
