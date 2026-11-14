"""IMAP mailbox access (C26) — stdlib-only synchronous client.

One read-only pass fetches every message with a UID greater than the
stored cursor. Connection breaks are retried ONCE inside the service
(reconnect-then-give-up); auth failures and timeouts propagate as typed
errors so the poller can react differently to each. Only reads: SELECT is
``readonly=True`` and nothing ever flags or deletes mail.
"""

import imaplib
import ssl
from contextlib import suppress
from email import policy
from email.message import Message
from email.parser import BytesParser
from typing import Any

BODY_TRUNCATE_CHARS = 20000
DEFAULT_IMAP_PORT = 993
# Tests shrink this; production uses one moderate ceiling for every step.
IMAP_TIMEOUT_SECONDS = 15.0


class ImapError(Exception):
    """Base class for IMAP failures (connection-level, post-auth)."""


class ImapAuthError(ImapError):
    """The server rejected the credentials."""


class ImapTimeoutError(ImapError):
    """An operation exceeded IMAP_TIMEOUT_SECONDS."""


class ImapConnectionError(ImapError):
    """The connection broke and the single in-service reconnect failed too."""


def _connect(host: str, port: int) -> imaplib.IMAP4:
    """Open (and implicitly TLS-wrap for the default port) the connection."""
    try:
        if port == DEFAULT_IMAP_PORT:
            return imaplib.IMAP4_SSL(host, port, timeout=IMAP_TIMEOUT_SECONDS)
        return imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT_SECONDS)
    except (OSError, ssl.SSLError, imaplib.IMAP4.abort) as exc:
        raise ImapConnectionError(f"could not connect to {host}:{port}") from exc


def _body_text(message: Message) -> str:
    """First text/plain part, decoded and truncated to BODY_TRUNCATE_CHARS."""
    if message.get_content_type() == "text/plain":
        body = message.get_content()  # type: ignore[attr-defined]
    else:
        body = ""
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()  # type: ignore[attr-defined]
                    break
    return body[:BODY_TRUNCATE_CHARS]


def _normalize(uid: int, raw: bytes) -> dict[str, Any]:
    """Reduce one RFC822 blob to the event payload shape."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    return {
        "uid": uid,
        "message_id": message.get("message-id"),
        "from": message.get("from"),
        "subject": message.get("subject"),
        "date": message.get("date"),
        "body_text": _body_text(message),
    }


def _search_uids(connection: imaplib.IMAP4, last_uid: int) -> list[int]:
    """UIDs strictly greater than last_uid (the n:* reply echoes the last UID)."""
    status, data = connection.uid("search", None, f"UID {last_uid + 1}:*")  # type: ignore[arg-type]
    if status != "OK":
        raise ImapError(f"UID SEARCH failed: {data!r}")
    uids = [int(token) for token in data[0].split()]
    return [uid for uid in uids if uid > last_uid]


def _fetch_raw(connection: imaplib.IMAP4, uid: int) -> bytes:
    """The full RFC822 bytes for one UID."""
    status, data = connection.uid("fetch", str(uid), "(RFC822)")
    if status != "OK":
        raise ImapError(f"UID FETCH {uid} failed: {data!r}")
    for item in data:
        if isinstance(item, tuple) and isinstance(item[1], bytes):
            return item[1]
    raise ImapError(f"UID FETCH {uid} returned no body")


def _fetch_once(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str,
    last_uid: int,
) -> tuple[int, list[dict[str, Any]]]:
    """One connection-lifetime pass over the mailbox."""
    connection = _connect(host, port)
    try:
        try:
            connection.login(username, password)
        except imaplib.IMAP4.error as exc:
            raise ImapAuthError("LOGIN rejected") from exc
        try:
            status, _ = connection.select(folder, readonly=True)
        except (imaplib.IMAP4.error, OSError, TimeoutError) as exc:
            raise ImapError(f"SELECT {folder!r} failed") from exc
        if status != "OK":
            raise ImapError(f"SELECT {folder!r} failed")

        uids = _search_uids(connection, last_uid)
        messages = [_normalize(uid, _fetch_raw(connection, uid)) for uid in uids]
        new_last_uid = max(uids, default=last_uid)
        return new_last_uid, messages
    except ImapError:
        raise
    except TimeoutError as exc:
        raise ImapTimeoutError("IMAP operation timed out") from exc
    except (imaplib.IMAP4.abort, OSError, EOFError, ssl.SSLError) as exc:
        raise ImapConnectionError("connection broke") from exc
    finally:
        with suppress(imaplib.IMAP4.error, OSError):
            connection.logout()


def fetch_new_messages(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str,
    last_uid: int,
) -> tuple[int, list[dict[str, Any]]]:
    """Fetch messages newer than the cursor, reconnecting exactly once.

    Args:
        host: Mail server host.
        port: Server port (993 implies implicit TLS, anything else plaintext).
        username: Mailbox account.
        password: Mailbox password (the connection secret at the poller).
        folder: Mailbox folder (e.g. ``"INBOX"``).
        last_uid: Cursor: only UIDs strictly above it are returned.

    Returns:
        ``(new_last_uid, messages)`` — messages are normalized dicts with
        uid, message_id, from, subject, date, body_text (truncated at 20000
        chars).

    Raises:
        ImapAuthError: Login rejected (no reconnect attempted).
        ImapTimeoutError: Operation timeout (no reconnect attempted).
        ImapConnectionError: Connection broke; the single in-service retry
            failed as well.
    """
    try:
        return _fetch_once(host, port, username, password, folder, last_uid)
    except ImapConnectionError:
        return _fetch_once(host, port, username, password, folder, last_uid)
