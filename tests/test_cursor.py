import base64
import hashlib
import hmac

import pytest

from notes.cursor import decode_cursor, encode_cursor, get_secret

SECRET = b"k" * 32


def test_round_trip() -> None:
    assert decode_cursor(encode_cursor(7, "work", SECRET), SECRET) == (7, "work")
    assert decode_cursor(encode_cursor(3, None, SECRET), SECRET) == (3, None)


def test_altered_or_garbage_raises() -> None:
    cur = encode_cursor(7, "work", SECRET)
    for bad in ("", "garbage", cur + "x", "x" + cur, cur.replace(".", ":")):
        with pytest.raises(ValueError):
            decode_cursor(bad, SECRET)
    with pytest.raises(ValueError):
        decode_cursor(cur, b"other" * 8)


def _signed(raw: bytes) -> str:
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def test_signed_but_malformed_payload_raises() -> None:
    for raw in (b"not json", b'{"a":"x","t":null}', b'{"a":true,"t":null}', b'{"a":1}', b"[1]"):
        with pytest.raises(ValueError):
            decode_cursor(_signed(raw), SECRET)


def test_get_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTES_CURSOR_SECRET", "abc")
    assert get_secret() == b"abc"
    monkeypatch.delenv("NOTES_CURSOR_SECRET")
    assert len(get_secret()) == 32 and get_secret() != get_secret()
