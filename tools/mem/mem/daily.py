"""E1: daily/ workbench layer (ADR-0011).

ReMe lifecycle applied to the mem store:
  raw (source of truth, untouched) -> daily cards (lightly processed,
  line-anchored routing index) -> digest claims (deep-processed via
  the existing hygiene pipeline) and distilled exchanges.

Daily cards are ordinary Markdown with frontmatter + [[raw/…#Lx-Ly]]
anchor links: human-editable, git-diffable, rebuildable. Consolidation
is auto_dream-style: bounded window, at most max_units promoted per
run, and promotion goes through hygiene.ingest so the quote gate and
contradiction machinery apply — never a bulk rewrite of the store.
"""

import datetime
import json
import os
import re

from . import codec, distill, hygiene, schema
from .chunking import anchor, chunk_markdown


def _first_scalar(v):
    while isinstance(v, list):
        v = v[0] if v else ""
    return str(v)


def _covered_raws(store):
    """Raw rels already having a daily card (from card frontmatter).
    mini-YAML parses [[raw/x.md]] as a nested list; flatten and pull
    the .md path out of whatever shape the scalar survived as."""
    covered = set()
    for rel in store.list_rel("daily"):
        front, _ = codec.split_frontmatter(store.read(rel))
        src = _first_scalar((front or {}).get("source", ""))
        m = re.search(r"([^\[\]#|',\s]+\.md)", src)
        if m:
            covered.add(m.group(1).strip())
    return covered


def raw_rel_list(store):
    return store.list_rel("raw")


def build_daily(store, today=None):
    """One card per uncarded raw file -> daily/<date>/<slug>.md with
    anchor-linked section index + Sources section. Raw untouched."""
    today = today or datetime.date.today().isoformat()
    created = []
    for rel in raw_rel_list(store):
        if rel in _covered_raws(store):
            continue
        text = store.read(rel)
        front, body = codec.split_frontmatter(text)
        front = front or {}
        title = front.get("origin") or os.path.basename(rel)
        chunks = chunk_markdown(body, max_lines=40, ref=rel)
        if not chunks:
            continue
        slug = schema.slugify(os.path.basename(rel).rsplit(".", 1)[0])[:60]
        card_rel = "daily/%s/%s.md" % (today, slug)
        lines = ["# %s" % title, ""]
        for ch in chunks[:20]:
            first = next((l.strip() for l in ch["text"].split("\n")
                          if l.strip() and not l.startswith("#")), "")
            lines.append("- [[%s]] %s" % (ch["ref"],
                                          (ch["heading_path"][-1] + ": "
                                           if ch["heading_path"] else "")
                                          + first[:90]))
        lines += ["", "## Sources",
                  "", "Captured from [[%s]] (verbatim source of truth; "
                  "this card is routing index only)." % rel, ""]
        fm = codec.build_frontmatter({
            "title": title, "format": codec.FMT, "type": "daily",
            "source": "[[%s]]" % rel, "date": today,
            "created": today, "updated": today})
        store.write(card_rel, fm + "\n" + "\n".join(lines))
        store.append_event({"event": "daily_card", "rel": card_rel,
                            "source": rel, "chunks": len(chunks)})
        created.append({"rel": card_rel, "source": rel,
                        "chunks": len(chunks)})
    return created


def consolidate(store, today=None, window_days=2, max_units=5):
    """auto_dream-lite: promote up to max_units distilled exchanges
    from the recent window into digest claims via hygiene.ingest
    (quote-gated; the specific_context verbatim is the source_quote).
    Already-promoted objects are never re-promoted (event check)."""
    today = today or datetime.date.today().isoformat()
    from . import hygiene as _h
    events = _h._events(store)
    promoted = {e.get("dst") for e in events if e.get("event") == "promote"}
    units = []
    for obj in distill.load_distilled(store):
        if len(units) >= max_units:
            break
        if obj["id"] in promoted:
            continue
        if _days_between(obj["date"], today) > window_days:
            continue
        pred = _pick_pred(obj)
        subject = (obj["files_touched"][0] if obj["files_touched"]
                   else (obj["room_assignments"][0]["key"]
                         if obj["room_assignments"] else "session"))
        page = store.page_for_subject(subject)
        claim = {
            "text": "%s %s: %s" % (subject, pred, obj["exchange_core"]),
            "pred": pred, "status": "unverified",
            "confidence": 0.6, "date": obj["date"],
            "edges": [{"type": "derived_from",
                       "target": "%s#L%d-L%d" % (obj["source"]["file"],
                                                 obj["source"]["start_line"],
                                                 obj["source"]["end_line"])}],
        }
        try:
            r = hygiene.ingest(
                store, page, claim,
                source_quote=obj["specific_context"],
                raw_rel=obj["source"]["file"])
            store.append_event({"event": "promote", "dst": obj["id"],
                                "claim": r["id"], "page": page})
            units.append({"dst": obj["id"], "claim": r["id"],
                          "page": page, "pred": pred})
        except ValueError as e:
            store.remove_if_empty(page)
            units.append({"dst": obj["id"], "rejected": str(e)})
    return units


def _pick_pred(obj):
    low = (obj["exchange_core"] + " " + obj["specific_context"]).casefold()
    if re.search(r"\bfail|crash|error|bug\b", low):
        return "incident"
    if re.search(r"\bdecision|decided|choose|chose|keep\b", low):
        return "decision"
    if re.search(r"\bgotcha|trap|quirk|caveat|breaks?\b", low):
        return "gotcha"
    return "other"


def _days_between(iso_a, iso_b):
    a = datetime.date.fromisoformat(iso_a[:10])
    b = datetime.date.fromisoformat(iso_b[:10])
    return abs((b - a).days)
