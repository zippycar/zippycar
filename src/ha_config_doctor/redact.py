"""Keep passwords, tokens and personal details out of everything we write or print.

Two layers of protection:

1. Checks never copy a value whose setting name looks sensitive (``password``,
   ``token``, ``api_key``, ``latitude`` …) into a finding — they use
   :func:`shown_value`, which returns ``[hidden]`` for those.
2. Every piece of text that goes into a report, the change log or the screen
   passes through :func:`redact_text`, which blanks out anything that *looks*
   like an address, e-mail, phone number, login inside a web address, or a
   long token — even if it slipped through somewhere unexpected.
"""

from __future__ import annotations

import re
from typing import Any

HIDDEN = "[hidden]"

_SENSITIVE_EXACT = {
    "password", "passwd", "pass", "passphrase", "pin", "code", "token", "secret", "key",
    "api_key", "apikey", "api_token", "access_token", "refresh_token", "client_id",
    "client_secret", "auth", "authorization", "credentials", "cookie", "session",
    "webhook_id", "username", "user", "login", "email", "e_mail", "latitude", "longitude",
    "elevation", "lat", "lon", "lng", "long", "gps", "imei", "serial", "serial_number",
    "mac", "ssid", "bssid", "phone", "phone_number", "account", "account_id",
    "network_key", "encryption_key", "private_key", "pre_shared_key", "psk",
}
_SENSITIVE_PARTS = ("password", "passwd", "token", "secret", "api_key", "apikey", "private_key", "credential")


def is_sensitive_key(key: Any) -> bool:
    """True when a setting with this name usually holds a password, token or personal detail."""

    if not isinstance(key, str):
        return False
    name = key.strip().lower().replace("-", "_")
    if name in _SENSITIVE_EXACT:
        return True
    if name.endswith(("_key", "_token", "_secret", "_password", "_pin")):
        return True
    return any(part in name for part in _SENSITIVE_PARTS)


_URL_LOGIN = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_IPV4 = re.compile(r"(?<![\w.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\w.])")
_IPV6 = re.compile(
    r"(?<![\w:])(?:(?:[0-9A-Fa-f]{1,4}:){3,7}[0-9A-Fa-f]{1,4}|[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4})*::[0-9A-Fa-f:]{0,30}[0-9A-Fa-f])(?![\w:])"
)
_PHONE = re.compile(r"(?<!\w)\+\d[\d \-]{7,14}\d(?!\w)")
_KEY_VALUE = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|token|secret|access_token|client_secret|webhook_id)(\s*[:=]\s*)(\"[^\"]+\"|'[^']+'|[^\s,;}\"']+)"
)
_LONG_TOKEN = re.compile(r"(?<![\w\-+/=.])[A-Za-z0-9_\-+/=]{24,}(?![\w\-+/=])")
_HEX = set("0123456789abcdefABCDEF")


def _looks_like_token(word: str) -> bool:
    if word.isdigit():
        return False
    if len(word) >= 32 and all(ch in _HEX for ch in word):
        return True
    has_digit = any(ch.isdigit() for ch in word)
    has_upper = any(ch.isupper() for ch in word)
    has_lower = any(ch.islower() for ch in word)
    return has_digit and has_upper and has_lower


def redact_text(text: Any) -> str:
    """Blank out anything in ``text`` that looks private. Safe to call more than once."""

    if text is None:
        return ""
    out = str(text)
    out = _URL_LOGIN.sub(lambda m: m.group(1) + HIDDEN + "@", out)
    out = _JWT.sub("[hidden token]", out)
    out = _KEY_VALUE.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, out)
    out = _EMAIL.sub("[hidden e-mail]", out)
    out = _IPV4.sub("[hidden address]", out)
    out = _IPV6.sub("[hidden address]", out)
    out = _PHONE.sub("[hidden number]", out)
    out = _LONG_TOKEN.sub(lambda m: "[hidden code]" if _looks_like_token(m.group(0)) else m.group(0), out)
    return out


def shown_value(key: Any, value: Any, limit: int = 80) -> str:
    """A short, safe way to show a value in a report."""

    if is_sensitive_key(key):
        return HIDDEN
    if isinstance(value, (dict, list)):
        return "(a block of settings)"
    text = str(value)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return redact_text(text)
