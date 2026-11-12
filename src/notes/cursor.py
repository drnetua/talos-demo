"""Signed Page cursor: opaque position + tag filter, verified with HMAC-SHA256."""

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: bytes) -> str:
    return _b64(hmac.new(secret, payload.encode(), hashlib.sha256).digest())


def get_secret() -> bytes:
    """Signing key from NOTES_CURSOR_SECRET, else a random per-process key."""
    env = os.environ.get("NOTES_CURSOR_SECRET")
    return env.encode() if env else secrets.token_bytes(32)


def encode_cursor(position: int, tag: str | None, secret: bytes) -> str:
    payload = _b64(json.dumps({"a": position, "t": tag}, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload, secret)}"


def decode_cursor(cursor: str, secret: bytes) -> tuple[int, str | None]:
    """Return (position, tag); raise ValueError on malformed or tampered input."""
    payload, sep, signature = cursor.partition(".")
    if not sep or not hmac.compare_digest(signature, _sign(payload, secret)):
        raise ValueError("invalid page cursor")
    try:
        data = json.loads(_unb64(payload))
        position, tag = data["a"], data["t"]
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ValueError("invalid page cursor") from exc
    if type(position) is not int or not (tag is None or isinstance(tag, str)):
        raise ValueError("invalid page cursor")
    return position, tag
