"""S2: bitemporal stamping (ADR-0011).

Two clocks per claim (Graphiti/Zep model, arXiv:2501.13956): valid time
(valid_at/invalid_at — when the fact held in the world) and
transaction time (date — when the system recorded it; already on every
claim). Relative phrases ("last month", "3 days ago") are resolved at
EMIT time against the reference timestamp, because an unresolved
relative date is unrecoverable later.

Supersede-by-invalidation: when an ingest contradicts an older claim
(same predicate, different value), the old claim gets invalid_at = the
new claim's date — never deleted, never overwritten in place
(AGENTS.md rule 4). as_of() answers "what did we believe on day X".
"""

import calendar
import datetime
import re

_REL_PATTERNS = [
    (re.compile(r"\btoday\b", re.I), 0),
    (re.compile(r"\byesterday\b", re.I), -1),
    (re.compile(r"\blast night\b", re.I), -1),
    (re.compile(r"\b(\d+)\s+days?\s+ago\b", re.I), None),
    (re.compile(r"\b(\d+)\s+weeks?\s+ago\b", re.I), None),
    (re.compile(r"\b(\d+)\s+months?\s+ago\b", re.I), None),
    (re.compile(r"\bthis month\b", re.I), "month0"),
    (re.compile(r"\blast month\b", re.I), "month1"),
    (re.compile(r"\blast week\b", re.I), -7),
    (re.compile(r"\blast quarter\b", re.I), "quarter1"),
    (re.compile(r"\blast year\b", re.I), "year1"),
]


def resolve_relative(text, ref_date):
    """First relative-date phrase in text, resolved against ref_date
    (a date or ISO string) -> ISO date string, or None."""
    if isinstance(ref_date, str):
        ref_date = datetime.date.fromisoformat(ref_date[:10])
    for rx, delta in _REL_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        if isinstance(delta, int):
            return (ref_date + datetime.timedelta(days=delta)).isoformat()
        if delta is None:
            unit = m.group(0).split()[1].rstrip("s").lower()
            n = int(m.group(1))
            if unit == "day":
                return (ref_date - datetime.timedelta(days=n)).isoformat()
            if unit == "week":
                return (ref_date - datetime.timedelta(weeks=n)).isoformat()
            return _shift_months(ref_date, -n).isoformat()
        if delta == "month0":
            return ref_date.replace(day=1).isoformat()
        if delta == "month1":
            return _shift_months(ref_date, -1).replace(day=1).isoformat()
        if delta == "quarter1":
            return _shift_months(ref_date, -3).replace(day=1).isoformat()
        if delta == "year1":
            return _shift_months(ref_date, -12).isoformat()
    return None


def _shift_months(d, months):
    total = d.year * 12 + (d.month - 1) + months
    y, m = divmod(total, 12)
    m += 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return datetime.date(y, m, day)


def stamp_claim(claim, reference_date=None):
    """Resolve a relative phrase in the claim text at emit time; sets
    valid_at when found and no explicit valid_at exists. Returns the
    phrase resolved (or None); mutates the claim dict in place."""
    if claim.get("valid_at"):
        return None
    ref = reference_date or claim.get("date") or \
        datetime.date.today().isoformat()
    resolved = resolve_relative(claim["text"], ref)
    if resolved:
        claim["valid_at"] = resolved
    return resolved if resolved else None


def as_of(claim, day):
    """True if the claim's world-state was active on ISO date `day`:
    recorded on or before it, not yet invalidated before it."""
    if isinstance(day, str):
        day = day[:10]
    if claim.get("date") and claim["date"] > day:
        return False
    invalid = claim.get("invalid_at")
    if invalid and day >= invalid:
        return False
    return True


def active_claims(store, day):
    """(page, claim) for every claim believed active on `day`."""
    out = []
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        for c in claims:
            if c["status"] != "retracted" and as_of(c, day):
                out.append((page, c))
    return out


def timeline(store, claim_id):
    """Bitemporal view: transaction events from events.jsonl plus the
    claim's validity window."""
    from . import hygiene
    ev = [e for e in hygiene._events(store) if e.get("claim") == claim_id]
    window = {}
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        target = next((c for c in claims if c["id"] == claim_id), None)
        if target:
            window = {"page": page, "date": target.get("date"),
                      "valid_at": target.get("valid_at"),
                      "invalid_at": target.get("invalid_at"),
                      "status": target["status"]}
            break
    return {"claim": claim_id, "validity": window, "events": ev}
