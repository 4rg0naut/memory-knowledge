"""Canonical JSON (RFC 8785-style) and OpenClaims event digests.

Byte-compatible with the OpenClaims v0.1 reference implementation
(packages/typescript-sdk/src/canonicalize.js, commit pinned in
vendor/openclaims/PROVENANCE.md): objects sorted by key in UTF-16 code
unit order, JSON.stringify-compatible string escaping and number
formatting, SHA-256, base64url. Clean-room: re-implemented from spec and
observable behavior, not copied.
"""

import base64
import hashlib
import math
from decimal import Decimal

SPEC_VERSION = "0.1.0"
DEFAULT_SCHEMA_URL = (
    "https://openclaims.org/schemas/openclaims/0.1/ClaimEvent.schema.json"
)


def _code_units(s):
    units = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x10000:
            units.append(cp)
        else:
            v = cp - 0x10000
            units.append(0xD800 + (v >> 10))
            units.append(0xDC00 + (v & 0x3FF))
    return units


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _json_string(s):
    out = ['"']
    for ch in s:
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _json_number(n):
    if isinstance(n, bool):
        raise TypeError("bool is not a number")
    if not math.isfinite(n):
        raise TypeError("Cannot canonicalize non-finite number")
    if isinstance(n, int):
        return str(n)
    if n == int(n) and abs(n) < 1e21:
        return str(int(n))
    return _float_to_js(n)


def _float_to_js(n):
    sign, digits, exp = Decimal(repr(n)).normalize().as_tuple()
    digits = "".join(map(str, digits))
    k = len(digits) + exp
    prefix = "-" if sign else ""
    if -6 < k <= 0:
        return "%s0.%s%s" % (prefix, "0" * -k, digits)
    if 0 < k <= 21:
        if k >= len(digits):
            return "%s%s%s" % (prefix, digits, "0" * (k - len(digits)))
        return "%s%s.%s" % (prefix, digits[:k], digits[k:])
    mant = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
    return "%s%se%s%d" % (prefix, mant, "+" if k > 0 else "-", abs(k - 1))


def canonicalize(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _json_number(value)
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, (list, tuple)):
        return "[%s]" % ",".join(canonicalize(v) for v in value)
    if isinstance(value, dict):
        entries = [(k, v) for k, v in value.items() if v is not None]
        entries.sort(key=lambda kv: _code_units(kv[0]))
        return "{%s}" % ",".join(
            "%s:%s" % (_json_string(k), canonicalize(v)) for k, v in entries
        )
    raise TypeError("Cannot canonicalize %s" % type(value).__name__)


def sha256_base64url(text):
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def digest_value(value):
    return {
        "algorithm": "sha256",
        "encoding": "base64url",
        "value": sha256_base64url(canonicalize(value)),
    }


def event_digest(event):
    clone = {k: v for k, v in event.items() if k != "digest"}
    return digest_value(clone)


def with_event_digest(event):
    event = dict(event)
    event["digest"] = event_digest(event)
    return event


def verify_event_digest(event):
    if not event or not event.get("digest"):
        return False
    return event["digest"] == event_digest(event)
