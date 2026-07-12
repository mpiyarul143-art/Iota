"""
Iota — safe callback_data codec (Telegram 64-byte guard).

Callback button payloads are hard-capped at 64 bytes by Telegram. Several
handlers build `callback_data` from ids/usernames and will silently BREAK
(the button does nothing) the moment a payload gets long. This module
encodes structured data as a compact, URL-safe base64 token under a short
prefix, and refuses to build anything over 64 bytes.

Usage:
    from utils.callback_codec import encode_callback, decode_callback

    data = encode_callback("wsp", {"w": wid})   # -> "wsp:<base64>"
    # pattern in bot.py:  r"^wsp:"
    payload = decode_callback(query.data, "wsp") # -> {"w": wid} or None
"""
import json
import base64

MAX_CALLBACK_BYTES = 64


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def encode_callback(prefix: str, data: dict) -> str:
    """Encode `data` into `prefix:<b64>` and assert it fits in 64 bytes."""
    if not prefix or ":" in prefix:
        raise ValueError("callback prefix must be non-empty and colon-free")
    token = prefix + ":" + _b64encode(
        json.dumps(data, separators=(",", ":")).encode("utf-8")
    )
    if len(token) > MAX_CALLBACK_BYTES:
        raise ValueError(
            f"callback_data too long ({len(token)} > {MAX_CALLBACK_BYTES} bytes)"
        )
    return token


def decode_callback(data, prefix: str):
    """Decode a callback token, or return None if it doesn't match `prefix`."""
    if not data or not isinstance(data, str) or not data.startswith(prefix + ":"):
        return None
    raw = data[len(prefix) + 1:]
    try:
        return json.loads(_b64decode(raw))
    except Exception:
        return None
