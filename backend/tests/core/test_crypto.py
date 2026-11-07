"""Tests for C17 core.crypto — one test per contract error case."""

import pytest
from cryptography.fernet import Fernet

from app.core.crypto import CryptoError, _derive_key, decrypt, encrypt

SECRET = "c17-test-secret"
OTHER_SECRET = "a-different-secret-entirely"
PLAINTEXTS = ["simple ascii", "日本語の秘密 ✓", "🔑 emoji key\twith\ttabs"]


@pytest.mark.parametrize("plaintext", PLAINTEXTS)
def test_roundtrip_ascii_and_unicode(plaintext):
    """encrypt -> decrypt returns the original text for ascii and unicode."""
    assert decrypt(encrypt(plaintext, SECRET), SECRET) == plaintext


def test_empty_input_yields_empty_output_both_ways():
    """Empty plaintext encrypts to empty; empty ciphertext decrypts to empty."""
    assert encrypt("", SECRET) == ""
    assert decrypt("", SECRET) == ""


def test_wrong_secret_raises_crypto_error_not_invalid_token():
    """A foreign key surfaces as CryptoError, never cryptography's InvalidToken."""
    ciphertext = encrypt("top secret", SECRET)

    with pytest.raises(CryptoError, match="decryption failed"):
        decrypt(ciphertext, OTHER_SECRET)


def test_tampered_ciphertext_raises_crypto_error():
    """Flipping characters in the token makes decryption fail closed."""
    ciphertext = encrypt("top secret", SECRET)
    tampered = ciphertext[:-8] + "AAAAAAAA"

    with pytest.raises(CryptoError):
        decrypt(tampered, SECRET)


def test_garbage_ciphertext_raises_crypto_error():
    """Non-Fernet input fails closed as CryptoError."""
    with pytest.raises(CryptoError):
        decrypt("not-a-fernet-token", SECRET)
    with pytest.raises(CryptoError):
        decrypt("héllo-ünïcode", SECRET)


def test_encryption_is_randomized():
    """Two encryptions of the same plaintext differ (randomized IV)."""
    assert encrypt("same", SECRET) != encrypt("same", SECRET)


def test_derived_key_differs_from_raw_secret_and_is_deterministic():
    """HKDF output is stable per secret and is not the secret itself."""
    first = _derive_key(SECRET)
    second = _derive_key(SECRET)

    assert first == second
    assert first != SECRET.encode("utf-8")
    assert first != _derive_key(OTHER_SECRET)
    Fernet(first)  # the derived key is a valid Fernet key


def test_never_returns_partial_plaintext():
    """A truncated token raises CryptoError instead of returning a prefix."""
    ciphertext = encrypt("a much longer secret value", SECRET)

    with pytest.raises(CryptoError):
        decrypt(ciphertext[: len(ciphertext) // 2], SECRET)
