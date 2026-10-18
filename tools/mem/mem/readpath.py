"""S3: hybrid read path (ADR-0011).

SQLite FTS5 BM25 over verbatim sections, feature-hash vectors over
distilled objects, CombMNZ consensus fusion with a tiered
full-lexical-match backbone, then score += power-law recency +
importance (claim status weight), finally a token-budget packer for
small-model context injection.

Every packed item carries its citation tag: `[claim:clm_x|status]`
for ledger claims, `[ref|evidence]` for raw/daily anchors — cite or
it didn't happen (AGENTS.md rule 1). Unverified claims pack as
assertions, never as fact (rule 2).

Modes (A/B-tested by evalkit):
  baseline  — BM25 over verbatim + claims (no distillation)
  distilled — vector recall over distilled objects only
  fused     — CombMNZ(FTS5 verbatim, vector distilled) + strong-match
              protection (full-lexical-match docs keep their slots)
  graph     — fused with 2-hop entity expansion as third consensus list

The vector stand-in is a deterministic lexical feature-hash embedder
(same class as XERJ's default offline embedder): 512-d signed term
hashes, L2-normalized, stdlib-only. Swap by passing an `embed`
callable once a neural provider is wired.
"""

import datetime
import hashlib
import math
import re
import sqlite3

from . import distill, graph, schema
from .chunking import chunk_markdown
from .distill import estimate_tokens

DIM = 512
RRF_K = 60
_RECENCY_ALPHA = 0.35

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_HAS_FTS5 = True
try:
    sqlite3.connect(":memory:").execute(
        "CREATE VIRTUAL TABLE t USING fts5(x)")
except sqlite3.OperationalError:
    _HAS_FTS5 = False


def embed(text, dim=DIM):
    """Offline lexical feature-hash embedding (deterministic)."""
    v = [0.0] * dim
    for tok in _TOKEN_RE.findall(text.casefold()):
        h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "big")
        idx = h % dim
        v[idx] += 1.0 if (h >> 63) & 1 == 0 else -1.0
    nrm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / nrm for x in v]


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def corpus(store, asof=None):
    """Docs: kind in {claim, verbatim, daily, distilled}. asof drops
    documents dated later or invalidated earlier (S2 filter).

    Claim ids are deduped (first occurrence wins): the append-only
    history may legitimately contain the same id twice (a pre-lint
    duplicate capture), but the derived FTS index has a UNIQUE id —
    derived views must absorb history mess, not crash on it."""
    docs = []
    seen_ids = set()
    today = datetime.date.today().isoformat()
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        for c in claims:
            if c["status"] == "retracted" or c["id"] in seen_ids:
                continue
            seen_ids.add(c["id"])
            docs.append({"id": c["id"], "kind": "claim",
                         "text": c["text"], "date": c["date"],
                         "status": c["status"],
                         "contradicts": [t.split("#")[-1] for t in
                                         schema.claim_edges(
                                             c, "contradicts")],
                         "invalid_at": c.get("invalid_at"),
                         "ref": "%s#%s" % (page, c["id"]),
                         "tags": "[claim:%s|%s]" % (c["id"], c["status"])})
    for rel in _list_raw(store):
        front, body = _read_body(store, rel)
        for ch in chunk_markdown(body, max_lines=40, ref=rel):
            docs.append({"id": "raw:%s" % ch["ref"], "kind": "verbatim",
                         "text": ch["text"], "date": _date_of(front, rel),
                         "status": "source", "invalid_at": None,
                         "ref": ch["ref"],
                         "tags": "[raw %s|verbatim]" % ch["ref"]})
    for rel in _list_daily(store):
        front, body = _read_body(store, rel)
        for ch in chunk_markdown(body, max_lines=40, ref=rel):
            docs.append({"id": "daily:%s" % ch["ref"], "kind": "daily",
                         "text": ch["text"],
                         "date": front.get("date") or today,
                         "status": "source", "invalid_at": None,
                         "ref": ch["ref"],
                         "tags": "[daily %s|routing]" % ch["ref"]})
    for obj in distill.load_distilled(store):
        docs.append({"id": obj["id"], "kind": "distilled",
                     "text": obj["exchange_core"] + "\n"
                     + obj["specific_context"],
                     "date": obj["date"], "status": "distilled",
                     "invalid_at": None,
                     "ref": "%s#L%d-L%d" % (obj["source"]["file"],
                                            obj["source"]["start_line"],
                                            obj["source"]["end_line"]),
                     "tags": "[dst %s|distilled]" % obj["id"]})
    if asof:
        docs = [d for d in docs if d["date"] <= asof
                and not (d.get("invalid_at") and d["invalid_at"] <= asof)]
    return docs


def _bm25_docs(docs):
    """Returns (fts, py): sqlite FTS5 index (or None) + python BM25.
    Both are rebuilt per query — fine at corpus scale today (~hundreds
    of docs, full rebuild in ms); if the corpus grows, cache by corpus
    sha (readpath already gets a stable hash from evalkit.stamp) and
    build PythonBM25 lazily only for the test parity oracle."""
    return (build_fts5(docs) if _HAS_FTS5 else None), PythonBM25(docs)


def build_fts5(docs):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE docs (id TEXT PRIMARY KEY)")
    con.execute("CREATE VIRTUAL TABLE ft USING fts5(body, content='')")
    for i, d in enumerate(docs):
        con.execute("INSERT INTO docs(rowid, id) VALUES (?,?)", (i, d["id"]))
        con.execute("INSERT INTO ft(rowid, body) VALUES (?,?)",
                    (i, d["text"]))
    return con


def fts5_search(con, query, k):
    q = " ".join('"%s"' % t for t in _TOKEN_RE.findall(query.casefold()))
    if not q:
        return []
    rows = con.execute(
        "SELECT rowid, bm25(ft) FROM ft WHERE ft MATCH ? ORDER BY "
        "bm25(ft) LIMIT ?", (q, k)).fetchall()
    return [r[0] for r in rows]


class PythonBM25:
    """Okapi BM25 fallback (k1=1.5, b=0.75) — also the parity oracle
    in tests."""

    def __init__(self, docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.toks = [list(_TOKEN_RE.findall(d["text"].casefold()))
                     for d in docs]
        self.tf = []
        self.df = {}
        for toks in self.toks:
            tf = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
                self.df[t] = self.df.get(t, 0) + 1
            self.tf.append(tf)
        self.lens = [max(1, len(x)) for x in self.toks]
        self.avg = sum(self.lens) / max(1, len(self.lens))
        self.n = len(self.toks)

    def search(self, query, k):
        q = set(_TOKEN_RE.findall(query.casefold()))
        scored = []
        for i in range(self.n):
            s = 0.0
            for t in q:
                f = self.tf[i].get(t, 0)
                if not f:
                    continue
                idf = math.log(1 + (self.n - self.df[t] + 0.5)
                               / (self.df[t] + 0.5))
                s += idf * (f * (self.k1 + 1)) / (
                    f + self.k1 * (1 - self.b + self.b
                                   * self.lens[i] / self.avg))
            if s > 0:
                scored.append((s, i))
        scored.sort(key=lambda t: -t[0])
        return [i for _, i in scored[:k]]


def rrf(rank_lists, k=RRF_K):
    """Reciprocal rank fusion — kept as the documented alternative;
    search() production path is combmnz() (see FAILURES F-08). Used
    in tests as the parity contrast and available for A/B runs."""
    scores = {}
    for lst in rank_lists:
        for rank, idx in enumerate(lst):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(((s, i) for i, s in scores.items()),
                key=lambda t: -t[0])


STRONG_MATCH_BONUS = 10.0  # > 3-list combmnz ceiling (9.0); see search()
GUARDRAIL_BOOST = 0.5  # G-G1: a live prohibition outranks the claim it
                       # retires — a guardrail that never surfaces is
                       # a guardrail that never happened


def combmnz(rank_lists):
    """CombMNZ fusion (criterion S3 alternative to RRF, chosen after
    A/B): score = consensus_count * sum(1/(rank+1)). Sharper rank gaps
    than RRF k=60, and the consensus multiplier rewards docs two
    independent retrievers agree on — the fusion signal we actually
    want. Returns (score, idx) pairs."""
    agg = {}
    for lst in rank_lists:
        for rank, idx in enumerate(lst):
            cur = agg.get(idx, [0.0, 0])
            cur[0] += 1.0 / (rank + 1)
            cur[1] += 1
            agg[idx] = cur
    return sorted(((c * s, i) for i, (s, c) in agg.items()),
                  key=lambda t: -t[0])


def recency(date_iso, today=None):
    today = today or datetime.date.today()
    try:
        d = datetime.date.fromisoformat(date_iso[:10])
    except ValueError:
        return 0.0
    age = max(0, (today - d).days)
    return 1.0 / ((age + 1) ** _RECENCY_ALPHA)


def importance(doc):
    if doc["kind"] == "claim":
        return schema.STATUS_WEIGHT.get(doc["status"], 0.3)
    return 0.4 if doc["kind"] == "distilled" else 0.35


def search(store, query, mode="fused", k=8, asof=None, today=None):
    docs = corpus(store, asof=asof)
    if not docs:
        return []
    idxs = list(range(len(docs)))
    fts, pybm = _bm25_docs(docs)
    qvec = embed(query)

    def fts_rank(pool):
        if fts is not None:
            got = fts5_search(fts, query, max(k * 5, 25))
            return [i for i in got if i in pool]
        order = pybm.search(query, max(k * 5, 25))
        return [i for i in order if i in pool]

    def vec_rank(pool):
        scored = sorted((( _cos(qvec, embed(docs[i]["text"])), i)
                         for i in pool), reverse=True)
        return [i for s, i in scored if s > 0][: max(k * 5, 25)]

    verbatim_pool = [i for i in idxs
                     if docs[i]["kind"] in ("verbatim", "daily", "claim")]
    distilled_pool = [i for i in idxs if docs[i]["kind"] == "distilled"]

    qtok = set(_TOKEN_RE.findall(query.casefold()))
    dtoks = {i: set(_TOKEN_RE.findall(d["text"].casefold()))
             for i, d in enumerate(docs)}

    if mode == "baseline":
        lists = [fts_rank(set(verbatim_pool))]
    elif mode == "distilled":
        lists = [vec_rank(distilled_pool)]
    elif mode == "graph":
        lists = [fts_rank(set(verbatim_pool)), vec_rank(set(idxs))]
        hits = graph.expand(query, edges=graph.load_graph(store),
                            asof=asof)
        hop_docs = graph.link_docs(docs, hits) if hits else []
        hop_ids = {doc_id for doc_id, _ in hop_docs[: k * 2]}
        hop_list = [i for i, d in idxs_with(docs) if d["id"] in hop_ids]
        if hop_list:
            lists.append(hop_list)
    else:  # fused
        lists = [fts_rank(set(verbatim_pool)), vec_rank(set(idxs))]

    combined = dict((i, s) for s, i in combmnz(lists))

    # Tiered fusion (fixes the fused-mrr-regression gotcha): docs
    # containing EVERY query token form a protected lexical backbone —
    # no partial-match consensus can push a full-lexical hit below a
    # partial one. STRONG_MATCH_BONUS (10.0) exceeds the theoretical
    # 3-list combmnz ceiling (3 x (1+1+1) = 9.0), so the hierarchy is
    # strict: guardrail > full-lexical > consensus > recency >
    # importance (GUARDRAIL_BOOST 0.5 tips a prohibition above the
    # retired claim sharing its text; retirement bounds the staleness
    # of the boost, G-G1). MRR
    # for lexically-anchored queries can therefore never fall below
    # the baseline's, while paraphrase and multi-hop recall still get
    # the dense/graph signal.
    out = []
    for i in set(combined):
        d = docs[i]
        backbone = STRONG_MATCH_BONUS if tier_ok(qtok, dtoks, i) else 0.0
        guard = GUARDRAIL_BOOST if d["status"] == "guardrail" else 0.0
        final = combined[i] + backbone + guard + 0.2 * recency(d["date"], today) \
            + 0.15 * importance(d)
        out.append({"id": d["id"], "kind": d["kind"], "ref": d["ref"],
                    "date": d["date"], "status": d["status"],
                    "contradicts": d.get("contradicts", []),
                    "tags": d["tags"], "text": d["text"],
                    "score": round(final, 5)})
    out.sort(key=lambda r: -r["score"])
    out = honor_guardrail_order(out)
    for pos, r in enumerate(out):
        r["rank"] = pos
    return out[:k]


def honor_guardrail_order(out):
    """G-G1: a guardrail is guaranteed to rank above every claim it
    contradicts — lineage beats weight consensus. A prohibition that
    fails to outrank the claim it retired is worse than no
    prohibition at all (the agent keeps acting on the stale claim).
    Stable pull-up: each guardrail moves to just above the highest
    contradicted doc in the list; everything else keeps its order."""
    moved = True
    while moved:
        moved = False
        pos = {r["id"]: i for i, r in enumerate(out)}
        for i, r in enumerate(out):
            if r["status"] != "guardrail":
                continue
            above = [pos[t] for t in r.get("contradicts", [])
                     if t in pos and pos[t] < i]
            if above:
                out.insert(min(above), out.pop(i))
                moved = True
                break
    return out


def tier_ok(qtok, dtoks, i):
    return not qtok or qtok <= dtoks[i]


def idxs_with(docs):
    return list(enumerate(docs))


def pack(results, budget_tokens):
    """Token-budgeted injection packer: keep top-scored items whose
    citation-tagged payload fits; stop, don't truncate mid-item
    (except the last item's text tail). Returns (items, tokens_used)."""
    items, used = [], 0
    for r in results:
        head = r["tags"] + " "
        cost = estimate_tokens(head + r["text"])
        if used + cost <= budget_tokens:
            items.append({"id": r["id"], "ref": r["ref"], "tag": r["tags"],
                          "score": r["score"], "text": r["text"]})
            used += cost
        else:
            remain = budget_tokens - used
            room = max(0, remain - estimate_tokens(head))
            keep = r["text"][: room * 4]
            if keep.strip() and len(keep) >= 40:
                items.append({"id": r["id"], "ref": r["ref"],
                              "tag": r["tags"],
                              "score": r["score"], "text": keep,
                              "truncated": True})
                used += estimate_tokens(head + keep)
            break
    return items, used


def recall(store, query, mode="fused", k=8, budget=600, asof=None):
    results = search(store, query, mode=mode, k=k, asof=asof)
    items, used = pack(results, budget)
    return {"query": query, "mode": mode, "budget": budget,
            "tokens_used": used, "items": items,
            "candidates": len(results)}


def _list_raw(store):
    return store.list_rel("raw")


def _list_daily(store):
    return store.list_rel("daily")


def _read_body(store, rel):
    from . import codec
    front, body = codec.split_frontmatter(store.read(rel))
    return front or {}, body


def _date_of(front, rel):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", front.get("retrieved_at", "")
                  + rel)
    return m.group(1) if m else datetime.date.today().isoformat()
