"""Hygiene: ingest pipeline, contradiction/corroboration, lint, decay."""

import datetime
import os
import re

from . import codec, rules, schema


def _today():
    return datetime.date.today()


GUARDRAIL_TTL_ENV = "MEM_GUARDRAIL_TTL_DAYS"
GUARDRAIL_TTL_DEFAULT = 90


def _guardrail_ttl_days():
    try:
        return int(os.environ.get(GUARDRAIL_TTL_ENV, GUARDRAIL_TTL_DEFAULT))
    except ValueError:
        return GUARDRAIL_TTL_DEFAULT


def build_guardrail(store, page, old, by):
    """G-G1: a contradiction spawns a guardrail — an explicit
    prohibition ('do not assert X'), NOT a re-assertion of Y. It
    carries BOTH lineages (the contradicted claim and the refuting
    evidence/raw) and a revalidate_at expiry so stale prohibitions
    get re-checked instead of accumulating as retrieval noise."""
    ttl = _guardrail_ttl_days()
    today = datetime.date.fromisoformat(by["date"])
    raws = [t for t in schema.claim_edges(by, "derived_from")
            if t.startswith("raw/")]
    edges = [{"type": "contradicts", "target": "%s#%s" % (page, old["id"])},
             {"type": "derived_from", "target": "%s#%s" % (page, by["id"])}]
    for r in raws:
        edges.append({"type": "derived_from", "target": r})
    return {
        "id": schema.new_id("guardrail|" + old["id"] + "|" + by["id"]),
        "text": "guardrail: do not assert \"%s\" (stale since %s; "
                "refuted by %s; re-validate after %s)"
                % (old["text"], by["date"], by["id"],
                   (today + datetime.timedelta(days=ttl)).isoformat()),
        "pred": "gotcha",
        "status": "guardrail",
        "confidence": 0.9,
        "date": by["date"],
        "valid_at": by["date"],
        "revalidate_at": (today + datetime.timedelta(days=ttl)).isoformat(),
        "edges": edges,
    }


def retire_guardrails(store, today=None, checker=None):
    """Guardrail retirement path: after revalidate_at expires, the
    audit re-checks whether the failure condition still holds. The
    condition holds while the refuting claim is active; when the
    refuter is retracted or contradicted (the failure was fixed /
    the ban was wrong), the guardrail is SUPERSEDED — status flip +
    invalid_at, history kept (append-only, AGENTS.md rule 4).
    Expired-but-still-true guardrails are reported, never deleted."""
    today = today or datetime.date.today().isoformat()
    checker = checker or _refutation_holds
    retired, expired = [], []
    with store:
        for page in store.all_pages():
            _, _, claims = store.parse_page(page)
            for c in claims:
                if c["status"] != "guardrail":
                    continue
                rv = c.get("revalidate_at")
                if not rv or rv > today:
                    continue
                expired.append(c["id"])
                if checker(store, page, c):
                    continue
                store.mutate_claim(page, c["id"], add_status="superseded",
                                   set_attrs={"invalid_at": today})
                store.append_event({"event": "guardrail_retire",
                                    "page": page, "claim": c["id"],
                                    "from": "guardrail", "to": "superseded",
                                    "invalid_at": today})
                retired.append(c["id"])
    return {"expired": expired, "retired": retired}


def _refutation_holds(store, page, guardrail):
    """Failure condition still holds = the refuting claim is still
    active (not retracted, not itself contradicted/superseded)."""
    ref_id = next((e.split("#")[-1]
                   for e in schema.claim_edges(guardrail, "derived_from")
                   if e.split("#")[-1].startswith("clm_")), None)
    if not ref_id:
        return False
    _, _, claims = store.parse_page(page)
    ref = next((c for c in claims if c["id"] == ref_id), None)
    return bool(ref) and ref["status"] not in ("retracted", "contradicted",
                                               "superseded")


def validate_claim(claim, at_ingest=True, ctx=None, rules_dir=None):
    """Writer-side gate, evaluated from declarative rules (ADR-0008).
    Returns list of rejection reasons ([] = ok)."""
    return rules.enforce(claim, ctx=ctx, directory=rules_dir,
                         at_ingest=at_ingest)


def ingest(store, page, claim, *, source_quote=None, raw_rel=None):
    """Append a validated claim with contradiction/corroboration checks.

    Returns dict with action + affected ids. Raises ValueError if invalid.
    """
    ctx = {"source_quote": source_quote}
    if raw_rel and store.exists(raw_rel):
        ctx["raw_text"] = store.read(raw_rel)
    reasons = validate_claim(claim, ctx=ctx)
    if reasons:
        raise ValueError("; ".join(reasons))
    from . import temporal
    temporal.stamp_claim(claim)
    if "id" not in claim:
        claim["id"] = schema.new_id(page + "|" + claim["text"])
    with store:
        _, _, claims = store.parse_page(page)
        existing = [c for c in claims
                    if c["status"] not in ("retracted", "guardrail",
                                           "superseded")]
        result = {"action": "appended", "id": claim["id"],
                  "contradicted": [], "corroborated": None,
                  "guardrails": []}
        pending_guards = []
        for old in existing:
            if old.get("pred") != claim.get("pred"):
                continue
            if schema.norm(old["text"]) == schema.norm(claim["text"]):
                new_srcs = [s for s in schema.claim_edges(claim, "derived_from")
                            if s not in schema.claim_edges(old, "derived_from")]
                if not new_srcs:
                    result["action"] = "duplicate_ignored"
                    return result
                if new_srcs:
                    store.mutate_claim(page, old["id"],
                                       add_edge={"type": "corroborated_by",
                                                 "target": new_srcs[0]})
                    if old["status"] == "unverified":
                        store.mutate_claim(page, old["id"],
                                           add_status="corroborated")
                    result["corroborated"] = old["id"]
                    result["action"] = "corroborated_existing"
                    store.append_event({"event": "corroborate",
                                        "page": page, "claim": old["id"],
                                        "from": old["status"],
                                        "to": "corroborated",
                                        "source": new_srcs[0]})
                    return result
            else:
                if old["status"] not in ("contradicted", "retracted"):
                    store.mutate_claim(page, old["id"],
                                       add_status="contradicted",
                                       set_attrs={"invalid_at":
                                                  claim["date"]})
                    store.append_event({"event": "contradict", "page": page,
                                        "claim": old["id"],
                                        "from": old["status"],
                                        "to": "contradicted",
                                        "by": claim["id"],
                                        "invalid_at": claim["date"]})
                    guard = build_guardrail(store, page, old, claim)
                    reasons = validate_claim(guard)
                    if reasons:
                        store.append_event(
                            {"event": "guardrail_rejected", "page": page,
                             "claim": guard["id"], "on": old["id"],
                             "reasons": reasons})
                    else:
                        pending_guards.append(guard)
                result["contradicted"].append(old["id"])
        store.append_claim(page, claim)
        store.append_event({"event": "emit", "page": page,
                            "claim": claim["id"], "to": claim["status"],
                            "pred": claim.get("pred"),
                            "sources": schema.claim_edges(claim,
                                                          "derived_from"),
                            "raw": raw_rel,
                            "quote_ok": (source_quote in
                                         store.read(raw_rel))
                            if source_quote and raw_rel and store.exists(raw_rel)
                            else None})
        if result["contradicted"]:
            store.mutate_claim(page, claim["id"], add_edge={
                "type": "contradicts",
                "target": "%s#%s" % (page, result["contradicted"][0])})
        for guard in pending_guards:
            store.append_claim(page, guard)
            store.append_event(
                {"event": "guardrail_emit", "page": page,
                 "claim": guard["id"], "on": guard["edges"][0]["target"],
                 "by": claim["id"],
                 "revalidate_at": guard["revalidate_at"]})
            result["guardrails"].append(guard["id"])
    return result


def verify(store, page, claim_id, source, actor="human"):
    if actor != "human":
        raise PermissionError("only human action can verify (got %r)" % actor)
    with store:
        _, _, claims = store.parse_page(page)
        target = next((c for c in claims if c["id"] == claim_id), None)
        if not target:
            raise KeyError("claim not found: %s" % claim_id)
        old = target["status"]
        store.mutate_claim(page, claim_id, add_status="verified")
        store.mutate_claim(page, claim_id,
                           add_edge={"type": "corroborated_by",
                                     "target": source})
        store.append_event({"event": "verify", "page": page, "claim": claim_id,
                            "from": old, "to": "verified", "source": source,
                            "actor": actor})


def retract(store, page, claim_id, reason=""):
    with store:
        _, _, claims = store.parse_page(page)
        target = next((c for c in claims if c["id"] == claim_id), None)
        if not target:
            raise KeyError("claim not found: %s" % claim_id)
        old = target["status"]
        store.mutate_claim(page, claim_id, add_status="retracted")
        store.append_event({"event": "retract", "page": page,
                            "claim": claim_id, "from": old,
                            "to": "retracted", "reason": reason})


def lint(store):
    """All hygiene violations across pages. Returns list of dicts."""
    issues = []
    for page in store.all_pages():
        try:
            _, _, claims = store.parse_page(page)
        except ValueError as e:
            issues.append({"page": page, "check": "parse", "detail": str(e)})
            continue
        for c in claims:
            for reason in validate_claim(c, at_ingest=False):
                issues.append({"page": page, "check": "validate",
                               "claim": c["id"], "detail": reason})
            if c["status"] == "verified":
                if not _has_verify_event(store, page, c["id"]):
                    issues.append({"page": page, "check": "self_verified",
                                   "claim": c["id"],
                                   "detail": "verified without verify event"})
            eff = schema.effective_confidence(c, _today())
            if eff < schema.FLAG_THRESHOLD and c["status"] != "retracted":
                issues.append({"page": page, "check": "stale",
                               "claim": c["id"],
                               "detail": "effective %.3f < %.2f (flagged, "
                                         "not removed)" % (eff,
                                                           schema.FLAG_THRESHOLD)})
    return issues


_EVENT_CACHE_TTL = {}


def _events(store):
    path = store.path("events.jsonl")
    try:
        import os
        st = os.stat(path)
        sig = (st.st_mtime, st.st_size)
    except OSError:
        return []
    key = path
    cached = _EVENT_CACHE_TTL.get(key)
    # (mtime, size) signature: mtime alone can survive an append within
    # coarse-filesystem timestamp granularity, serving a stale event
    # list to the very process that just wrote the line.
    if cached and cached[0] == sig:
        return cached[1]
    out = []
    with open(path, encoding="utf-8") as f:
        out, _torn = codec.read_jsonl(f.read())
    _EVENT_CACHE_TTL[key] = (sig, out)
    return out


def _has_verify_event(store, page, claim_id):
    return any(e["event"] == "verify" and e.get("claim") == claim_id
               and e.get("page") == page for e in _events(store))


def stale_report(store):
    rows = []
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        for c in claims:
            if c["status"] == "retracted":
                continue
            eff = schema.effective_confidence(c, _today())
            if eff < schema.STALE_THRESHOLD:
                rows.append({"page": page, "claim": c["id"],
                             "date": c["date"], "status": c["status"],
                             "effective": round(eff, 3),
                             "text": c["text"][:80]})
    rows.sort(key=lambda r: r["date"])
    return rows


def contradictions(store):
    """Contradicting-claim pairs. Guardrail claims are records of a
    contradiction, not independent contradictors — their lineage
    contradicts edges are skipped here (they surface via their `on`
    event and through the graph)."""
    out = []
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        by_id = {c["id"]: c for c in claims}
        for c in claims:
            if c["status"] in ("guardrail", "superseded"):
                continue
            for t in schema.claim_edges(c, "contradicts"):
                cid = t.split("#")[-1]
                other = by_id.get(cid)
                if other and other["status"] == "contradicted":
                    out.append({"page": page, "new": c["id"],
                                "old": cid, "old_text": other["text"],
                                "new_text": c["text"],
                                "old_date": other["date"],
                                "new_date": c["date"]})
    return out


def orphans(store):
    pages = store.all_pages()
    targets = set()
    for page in pages:
        text = store.read(page)
        for m in re.finditer(r"\[\[([^\]#|]+)", text):
            targets.add(m.group(1).strip().split("/")[-1])
    return [p for p in pages
            if (p.split("/")[-1] not in targets
                and p.split("/")[-1][:-3] not in targets)]


# --- S5: silicon-ledger hygiene port (ADR-0011) --------------------------
#
# Three rules from dev_m5max_re/silicon-ledger (CROSS-REPO-CONTRACT.md,
# bench/verify_extraction.py): evidence honesty is a computed state, not
# an assertion; machines may stamp model_check only; a standing audit
# re-checks every ledger row against its source.


PASSAGE_TOKEN_COVERAGE = 0.6


def quote_era(store, claim):
    """Capture era from the claim's own emit event (G-G2): 'quote'
    when the emit recorded quote_ok=True (quote gate checked this
    claim's source verbatim at write time); 'pre-gate' otherwise —
    emitted before the quote gate, or without a recorded check.
    This is a policy lookup against recorded history, not a guess."""
    for e in _events(store):
        if e.get("event") == "emit" and e.get("claim") == claim["id"]:
            if e.get("quote_ok") is True:
                return "quote"
    return "pre-gate"


def evidence_status(store, claim):
    """Write/audit-time non-LLM recheck of a claim's evidence, checked
    in order of severity (digest, then location):
      stale       — raw source no longer hashes to its pinned
                    content_hash (source drifted after emission)
      unlocatable — source or cited passage missing
      ok          — source intact and passage present
    Passage check is era-aware (G-G2): the claim's emit event records
    quote_ok, so the era is looked up, not guessed. Quote-era claims
    must locate verbatim — no coverage fallback. Pre-gate claims are
    paraphrases by design and get a deterministic token-coverage
    check whose result is explicitly attributed to that tier.
    Coverage requires >= PASSAGE_TOKEN_COVERAGE of the passage's
    long tokens (len>=6) in the source — invented claims still fail.
    Returns (status, detail)."""
    import hashlib
    if claim.get("status") == "guardrail":
        old = schema.claim_edges(claim, "contradicts")
        ref = schema.claim_edges(claim, "derived_from")
        if not old or not ref:
            return "unlocatable", "guardrail missing lineage edges"
        page = ref[0].split("#")[0]
        if not store.exists(page):
            return "unlocatable", "guardrail lineage page missing: %s" % page
        return "ok", "ledger-internal pair (%s, %s)" % (old[0], ref[0])
    sources = schema.claim_edges(claim, "derived_from")
    if not sources:
        return "unlocatable", "no derived_from source"
    target = sources[0].split("#")[0].strip()
    if not store.exists(target):
        return "unlocatable", "source missing: %s" % target
    text = store.read(target)
    front, body = codec.split_frontmatter(text)
    # write_raw appends exactly one newline after the payload; strip
    # that one byte only — rstrip-all would rehash payloads that
    # legitimately end with newlines and wrongly report "stale".
    if body.endswith("\n"):
        body = body[:-1]
    pinned = (front or {}).get("content_hash") or \
        (re.search(r"content_hash: (\w+)", text[:2000]) or [None, None])[1]
    if pinned:
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual != pinned:
            return "stale", "content_hash mismatch (pinned %s…)" % pinned[:12]
    passage = claim["text"].split(": ", 1)[-1]
    if not passage:
        return "ok", target
    if passage[:60] in body:
        return "ok", target
    era = quote_era(store, claim)
    long_toks = set(t.casefold() for t in
                    re.findall(r"[A-Za-z][A-Za-z0-9_-]{5,}", passage))
    if not long_toks:
        return "unlocatable", "passage not found in source"
    src_toks = set(t.casefold() for t in
                   re.findall(r"[A-Za-z][A-Za-z0-9_-]{5,}", body))
    cov = len(long_toks & src_toks) / len(long_toks)
    if era == "quote":
        # Quote-era policy today: full two-tier check unchanged (the
        # emit recorded a verbatim source quote; the claim value may
        # still paraphrase it). Explicitly attributed, never silent.
        if cov >= PASSAGE_TOKEN_COVERAGE:
            return "ok", ("%s (quote-era: paraphrase coverage %.2f)"
                          % (target, cov))
        return "unlocatable", ("quote-era: verbatim required, coverage "
                               "%.2f below %.2f" % (cov,
                                                   PASSAGE_TOKEN_COVERAGE))
    if cov >= PASSAGE_TOKEN_COVERAGE:
        return "ok", ("%s (pre-gate capture: verbatim not required; "
                      "paraphrase coverage %.2f)" % (target, cov))
    return "unlocatable", ("pre-gate capture: passage not located "
                           "(paraphrase coverage %.2f below %.2f)"
                           % (cov, PASSAGE_TOKEN_COVERAGE))


def model_check(store, page, claim_id,
                validator="urn:agent:mem-model-checker"):
    """Machine verification: an agent reads the claim against its
    cited passage. Can raise status to corroborated, NEVER to
    verified — `verified` has no machine code path (producer
    discipline; hygiene.verify stays human-only). The passage must be
    locatable now: unverifiable evidence is declared, not asserted."""
    status, detail = None, None
    with store:
        _, _, claims = store.parse_page(page)
        target = next((c for c in claims if c["id"] == claim_id), None)
        if not target:
            raise KeyError("claim not found: %s" % claim_id)
        status, detail = evidence_status(store, target)
        if status != "ok":
            raise ValueError("model_check refused: evidence %s (%s)"
                             % (status, detail))
        old = target["status"]
        if old == "unverified":
            store.mutate_claim(page, claim_id, add_status="corroborated")
        store.append_event({"event": "model_check", "page": page,
                            "claim": claim_id, "from": old,
                            "to": ("corroborated" if old == "unverified"
                                   else old),
                            "method": "model_check", "validator": validator,
                            "evidence": detail})
    return {"claim": claim_id, "status": ("corroborated"
                                          if old == "unverified" else old),
            "method": "model_check"}


def reconcile(store):
    """Standing audit: every claim's evidence status, duplicate ids,
    verified-without-event rows, and index freshness. Writes the
    generated view metadata/audit_report.json (generated-only, never
    hand-edited)."""
    import json
    retirement = retire_guardrails(store)
    checked = 0
    rows, counts = [], {"ok": 0, "stale": 0, "unlocatable": 0,
                        "duplicate_id": 0,
                        "ok_quote_era": 0, "ok_pregate_era": 0,
                        "unlocatable_quote_era": 0,
                        "unlocatable_pregate_era": 0}
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        seen = set()
        for c in claims:
            checked += 1
            if c["id"] in seen:
                counts["duplicate_id"] += 1
                rows.append({"page": page, "claim": c["id"],
                             "status": c["status"],
                             "evidence": "duplicate_id",
                             "quote_era": quote_era(store, c),
                             "detail": "claim id repeated on page "
                                       "(derived views dedup; retire "
                                       "the stale copy via retract)"})
                continue
            seen.add(c["id"])
            status, detail = evidence_status(store, c)
            era = quote_era(store, c)
            counts[status] = counts.get(status, 0) + 1
            if status in ("ok", "unlocatable"):
                counts["%s_%s_era" % (status,
                                      "quote" if era == "quote"
                                      else "pregate")] += 1
            row = {"page": page, "claim": c["id"], "status": c["status"],
                   "evidence": status, "quote_era": era,
                   "detail": detail[:120]}
            if c["status"] == "verified" and not _has_verify_event(
                    store, page, c["id"]):
                row["evidence"] = status
                counts["self_verified"] = counts.get("self_verified", 0) + 1
                row["note"] = "verified without verify event"
            if status != "ok" or "note" in row:
                rows.append(row)
    indexed = {e["file"] for e in schema.load_index(store.read("index.yaml"))} \
        if store.exists("index.yaml") else set()
    missing_index = [p for p in store.all_pages() if p not in indexed]
    torn = []
    if store.exists("events.jsonl"):
        _evs, torn = codec.read_jsonl(store.read("events.jsonl"))
    if torn:
        counts["torn_event_lines"] = len(torn)
        for t in torn:
            rows.append({"page": "events.jsonl", "claim": "-",
                         "evidence": "torn_line",
                         "detail": "unparseable append at line %d: %r"
                                   % (t["line"], t["text"])})
    report = {"checked": checked,
              "counts": counts, "problems": rows,
              "torn_event_lines": len(torn),
              "unindexed_pages": missing_index,
              "guardrail_retirement": retirement}
    store.write("metadata/audit_report.json",
                json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
