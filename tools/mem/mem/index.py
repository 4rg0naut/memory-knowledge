"""index.yaml router: regeneration + keyword routing."""

import datetime
import math
import re

from . import schema


def rebuild(store):
    entries = []
    for page in store.all_pages():
        front, body, claims = store.parse_page(page)
        entry = {
            "file": page,
            "summary": (front.get("summary")
                        or _first_sentence(body)
                        or front.get("title", page)),
            "tags": front.get("tags") or [],
            "updated": front.get("updated", ""),
            "claim_count": len(claims),
            "unverified_count": sum(1 for c in claims
                                    if c["status"] == "unverified"),
        }
        entries.append(entry)
    store.write("index.yaml", schema.dump_index(entries))
    return entries


def _first_sentence(body):
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("- ") and "{id:" in line:
            return line[2:].split("{")[0].strip()[:120]
    return ""


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def route(store, query, top_k=5):
    """Score index entries by token overlap (tag x2, summary x1)."""
    entries = schema.load_index(store.read("index.yaml"))
    q = _tokens(query)
    scored = []
    for e in entries:
        s = len(q & _tokens(e["summary"])) + 2 * len(
            q & _tokens(" ".join(e["tags"])))
        if s:
            scored.append((s, e))
    scored.sort(key=lambda t: (-t[0], -t[1]["claim_count"]))
    return [e for _, e in scored[:top_k]]


def rank_claims(claims, query, today=None):
    """effective_confidence x crude bm25-ish term-frequency within page."""
    today = today or datetime.date.today()
    q = _tokens(query)
    n = max(1, len(claims))
    df = {}
    for c in claims:
        for t in _tokens(c["text"]):
            df[t] = df.get(t, 0) + 1
    out = []
    for c in claims:
        toks = _tokens(c["text"])
        tf = len(q & toks) / max(1, len(toks))
        idf = math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))
        score = (tf * sum(idf for t in q if t in toks)) * \
            schema.effective_confidence(c, today)
        out.append((round(score, 4), c))
    out.sort(key=lambda t: -t[0])
    return out
