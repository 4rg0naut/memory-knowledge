"""S4: own-traffic eval harness (ADR-0011).

LongMemEval-style protocol on your own corpus: recall queries in three
types (exact / phrase / conceptual), consensus grading, and metrics
reported WITH token cost (MRR, P@1, mean grade, tokens/query) — the
field-guide rule that a score without tokens is noise.

Grading runs offline by consensus of three deterministic graders
(token-idf coverage, verbatim phrase hit, rare-token overlap) —
mechanical, reproducible, no model at runtime; an LLM grader can be
injected via grade_fn. Bootstrap builds a queryset from the live
corpus with guaranteed non-empty gold sets.

Every run writes metadata/eval_stamp.json (S5: protocol stamp —
python/platform/git commit/corpus hashes) so rows stay comparable,
and --emit pushes the headline into the OpenClaims ledger (AGENTS.md
rule 6: benchmark results are claims) via ocl, falling back to an
events.jsonl note when ocl is unavailable.
"""

import base64
import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys

from . import codec, distill, graph, readpath, schema
from .distill import estimate_tokens

QUERY_TYPES = ("exact", "phrase", "conceptual", "multihop")
MODES = ("baseline", "distilled", "fused", "graph")
_qs_token_re = readpath._TOKEN_RE
_ID_RX = distill._ID_RE


# --- queryset bootstrap ---------------------------------------------------

def build_queryset(store, n=200, seed=42):
    """Deterministic bootstrap: derive recall queries from the corpus
    with gold sets by construction. multihop queries are anchored in
    one doc's entity and gold-matched to a graph-adjacent doc that
    shares no query tokens — exactly what BM25 cannot see and the
    graph must surface."""
    docs = readpath.corpus(store)
    if not docs:
        return []
    rng = random.Random(seed)
    n = max(n, len(QUERY_TYPES))
    df = {}
    for d in docs:
        for t in set(_qs_token_re.findall(d["text"].casefold())):
            df[t] = df.get(t, 0) + 1
    cand = {t: [] for t in QUERY_TYPES}

    for d in docs:
        ids = [t for t in _qs_token_re.findall(d["text"])
               if ("_" in t or "." in t or len(t) > 9) and t.lower() != t
               or (re.fullmatch(r"[A-Za-z0-9_.-]{8,}", t)
                   and df.get(t.lower(), 99) <= 3)]
        for t in ids[:4]:
            gold = [x["id"] for x in docs if t.lower() in x["text"].casefold()]
            if gold:
                cand["exact"].append({"type": "exact", "query": t.lower(),
                                      "gold": gold})
        words = _qs_token_re.findall(d["text"].casefold())
        for glen in (6, 5, 4):
            for i in range(0, max(1, len(words) - glen + 1), 3):
                grams = words[i:i + glen]
                if len(grams) == glen and max(df.get(t, 0) for t in grams) \
                        <= 4 and min(df.get(t, 0) for t in grams) >= 1:
                    phrase = " ".join(grams)
                    gold = [x["id"] for x in docs
                            if phrase in x["text"].casefold()]
                    if gold:
                        cand["phrase"].append({"type": "phrase",
                                               "query": phrase, "gold": gold})
        rare = sorted((t for t in set(words) if df.get(t, 0) >= 1
                       and len(t) > 5),
                      key=lambda t: df.get(t, 9))[:3]
        if len(rare) >= 2:
            gold = [x["id"] for x in docs
                    if sum(1 for t in rare if t in x["text"].casefold())
                    >= max(1, len(rare) - 1)]
            if gold:
                cand["conceptual"].append({"type": "conceptual",
                                           "query": " ".join(rare),
                                           "gold": gold})

    cand["multihop"] = _multihop_candidates(store, docs, df, rng)

    per = max(1, n // len(QUERY_TYPES))
    qs, seen = [], set()
    for t in QUERY_TYPES:
        rng.shuffle(cand[t])
        picked = 0
        for q in cand[t]:
            key = q["query"]
            if key in seen or not q["gold"]:
                continue
            q["id"] = "q_" + hashlib.sha256(
                (t + key).encode()).hexdigest()[:10]
            seen.add(key)
            qs.append(q)
            picked += 1
            if picked >= per:
                break
    rng.shuffle(qs)
    return qs


def _multihop_candidates(store, docs, df, rng, limit=400):
    """Queries gold-matched across one graph edge: anchored in d1's
    entity, answer doc d2 shares no query tokens (so FTS cannot find
    it). Requires a built graph; returns [] without one."""
    edges = graph.load_graph(store)
    if not edges:
        return []
    toks = {d["id"]: set(_qs_token_re.findall(d["text"].casefold()))
            for d in docs}
    out = []
    pool = [e for e in edges if e["type"] in ("co_mentioned",
                                              "derived_from")
            and len(e["src"]) >= 5 and len(e["dst"]) >= 5
            and re.search(_ID_RX, e["dst"])]
    rng.shuffle(pool)
    for e in pool[:limit]:
        a, b = e["src"].lower(), e["dst"].lower()
        if a in b or b in a:
            continue
        d1s = [d for d in docs if a in d["text"].casefold()
               and b not in d["text"].casefold()]
        d2s = [d for d in docs if b in d["text"].casefold()
               and a not in d["text"].casefold()]
        if not d1s or not d2s:
            continue
        d1 = rng.choice(d1s)
        bridge = set(_qs_token_re.findall(b))
        words = [t for t in sorted(toks[d1["id"]])
                 if len(t) > 5 and t not in bridge
                 and df.get(t, 0) <= 3 and t != a][:3]
        if len(words) < 2:
            continue
        bword = b.split(".")[0]
        d2 = rng.choice(d2s)
        if toks[d2["id"]] & set(words) or a in toks[d2["id"]]:
            continue
        query = " ".join(words + [bword])
        out.append({"type": "multihop", "query": query,
                    "gold": [d2["id"]], "via": e.get("via")})
        if len(out) >= limit:
            break
    return out


def save_queryset(store, qs):
    store.write("benchmarks/queryset.jsonl",
                "".join(json.dumps(q, sort_keys=True) + "\n" for q in qs))
    return len(qs)


def load_queryset(store):
    """Derived view: torn lines are dropped and counted, never fatal
    (`mem eval --bootstrap` regenerates)."""
    if not store.exists("benchmarks/queryset.jsonl"):
        return []
    qs, _torn = codec.read_jsonl(
        store.read("benchmarks/queryset.jsonl"))
    return qs


# --- grading ---------------------------------------------------------------

def _idf(df, n, t):
    import math
    return math.log(1 + (n - df.get(t, 0) + 0.5) / (df.get(t, 0) + 0.5))


def make_graders(docs):
    df = {}
    for d in docs:
        for t in set(_qs_token_re.findall(d["text"].casefold())):
            df[t] = df.get(t, 0) + 1
    n = max(1, len(docs))

    def g_coverage(query, doc):
        q = [t for t in _qs_token_re.findall(query.casefold())
             if len(t) > 3]
        if not q:
            return 0
        dt = doc["text"].casefold()
        cov = sum(1 for t in q if t in dt) / len(q)
        return 3 if cov >= 0.9 else 2 if cov >= 0.6 \
            else 1 if cov >= 0.3 else 0

    def g_phrase(query, doc):
        return 3 if query.casefold() in doc["text"].casefold() else 0

    def g_rare(query, doc):
        q = _qs_token_re.findall(query.casefold())
        if not q:
            return 0
        top = max(q, key=lambda t: _idf(df, n, t))
        dt = doc["text"].casefold()
        hit = sum(1 for t in q if t in dt)
        if top in dt and hit == len(q):
            return 3
        if top in dt:
            return 2
        return 1 if hit else 0

    return [g_coverage, g_phrase, g_rare]


def consensus_grades(query, doc, graders):
    grades = sorted(g(query, doc) for g in graders)
    return grades[len(grades) // 2]  # median


# --- bootstrap confidence intervals (G-G3) ---------------------------------

def bootstrap_ci(samples, n_resamples=2000, seed=42, alpha=0.05):
    """Percentile bootstrap CI for the mean, stdlib-only. Deterministic
    given the seed: same samples + seed -> byte-identical interval."""
    if not samples:
        return None
    rng = random.Random(seed)
    n = len(samples)
    means = []
    for _ in range(n_resamples):
        tot = 0.0
        for _ in range(n):
            tot += samples[rng.randrange(n)]
        means.append(tot / n)
    means.sort()
    lo = means[max(0, int((alpha / 2) * n_resamples) - 1)]
    hi = means[min(n_resamples - 1, int((1 - alpha / 2) * n_resamples))]
    return [round(lo, 4), round(hi, 4)]


ci_overlap = graph.ci_overlap  # single source lives in graph (review #14)


# --- guardrail adversarial eval (G-G1) -------------------------------------

def guardrail_eval(store, k=8):
    """Two regression directions, scored separately — the failure
    directions the external review named:
      guardrail        — the prohibition is active; a query about the
                         retired claim must surface the guardrail
                         ABOVE the contradicted claim (the agent
                         refuses / re-routes).
      guardrail_stale  — the guardrail has been retired (superseded,
                         failure condition fixed); the newer claim
                         must rank ABOVE the stale prohibition, else
                         the stale ban re-teaches "don't do X" when
                         X is fine again.
    Reports n / outrank_rate / gold_mrr per class; n=0 is honest
    absence, not a passing grade."""
    items = []
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        by_id = {c["id"]: c for c in claims}
        for c in claims:
            if not c["text"].startswith("guardrail:"):
                continue
            tgt = schema.claim_edges(c, "contradicts")
            old = by_id.get(tgt[0].split("#")[-1]) if tgt else None
            ref_id = next((e.split("#")[-1] for e in
                           schema.claim_edges(c, "derived_from")
                           if e.split("#")[-1].startswith("clm_")), None)
            if old is not None:
                items.append((c, old, ref_id))
    out = {}
    for cls, want in (("guardrail", "guardrail"),
                      ("guardrail_stale", "superseded")):
        n = wins = 0
        rr = 0.0
        for g, old, ref_id in items:
            if g["status"] != want:
                continue
            words, seen_t = [], set()
            for t in _qs_token_re.findall(old["text"].casefold()):
                if len(t) > 4 and t not in seen_t:
                    seen_t.add(t)
                    words.append(t)
            if not words or (want == "guardrail_stale" and not ref_id):
                continue
            res = readpath.search(store, " ".join(words[:4]),
                                  mode="fused", k=k)
            ranks = {}
            for pos, r in enumerate(res, 1):
                ranks.setdefault(r["id"], pos)
            gold = g["id"] if want == "guardrail" else ref_id
            against = old["id"] if want == "guardrail" else g["id"]
            gr, ar = ranks.get(gold), ranks.get(against)
            n += 1
            wins += 1 if gr is not None and (ar is None or gr < ar) else 0
            rr += 1.0 / gr if gr else 0.0
        out[cls] = {"n": n,
                    "outrank_rate": round(wins / n, 4) if n else None,
                    "gold_mrr": round(rr / n, 4) if n else None}
    return out


# --- run --------------------------------------------------------------------

def run(store, modes=("baseline", "distilled", "fused", "graph"),
        budget=600, k=8, queryset=None, grade_fn=None,
        keep_samples=False, seed=42):
    qs = queryset if queryset is not None else load_queryset(store)
    if not qs:
        return {"error": "no queryset; run eval --bootstrap first"}
    docs = readpath.corpus(store)
    graders = make_graders(docs)
    gf = grade_fn or (lambda q, d: consensus_grades(q, d, graders))
    out, _samples = {}, {}
    for mode in modes:
        per_type = {t: {"n": 0, "rr": 0.0, "p1": 0, "grade_sum": 0.0,
                        "tokens": 0.0, "rr_samples": []}
                    for t in QUERY_TYPES}
        solved = failed = 0
        for q in qs:
            res = readpath.recall(store, q["query"], mode=mode, k=k,
                                  budget=budget)
            grades = []
            for item in res["items"]:
                if q["type"] == "multihop":
                    # gold is by construction across a graph edge; the
                    # doc shares no query tokens, so a lexical grader
                    # could never confirm it. Gold-set membership is
                    # the honest grade here.
                    grades.append(3 if item.get("id") in q["gold"] else 0)
                    continue
                doc = next((d for d in docs if d["ref"] == item["ref"]
                            or d["id"] == item["ref"].split("#")[0]), None)
                grades.append(gf(q["query"],
                                 doc or {"text": item["text"]}))
            rr = 0.0
            for rank, g in enumerate(grades, 1):
                if g >= 3:
                    rr = 1.0 / rank
                    break
            p1 = 1 if grades and grades[0] >= 3 else 0
            t = per_type.setdefault(
                q["type"], {"n": 0, "rr": 0.0, "p1": 0, "grade_sum": 0.0,
                            "tokens": 0.0, "rr_samples": []})
            t["n"] += 1
            t["rr"] += rr
            t["rr_samples"].append(rr)
            t["p1"] += p1
            t["grade_sum"] += (sum(grades) / len(grades)) if grades else 0
            t["tokens"] += res["tokens_used"]
            solved += bool(grades and any(g >= 3 for g in grades))
            failed += 0 if (grades and any(g >= 3 for g in grades)) else 1
        total_n = sum(v["n"] for v in per_type.values()) or 1
        out[mode] = {
            "mrr": round(sum(v["rr"] for v in per_type.values()) / total_n, 4),
            "p_at_1": round(sum(v["p1"] for v in per_type.values())
                            / total_n, 4),
            "mean_grade": round(sum(v["grade_sum"] for v in per_type.values())
                                / total_n, 4),
            "tokens_per_query": round(sum(v["tokens"] for v in
                                          per_type.values()) / total_n, 1),
            "solved": solved, "unsolved": failed, "n": total_n,
            "per_type": {t: {"n": v["n"],
                             "mrr": round(v["rr"] / (v["n"] or 1), 4),
                             "ci95": bootstrap_ci(v["rr_samples"], seed=seed),
                             "p_at_1": round(v["p1"] / (v["n"] or 1), 4),
                             "tokens_per_query":
                                 round(v["tokens"] / (v["n"] or 1), 1)}
                         for t, v in per_type.items()},
        }
        out[mode]["mrr_ci95"] = bootstrap_ci(
            [x for v in per_type.values() for x in v["rr_samples"]],
            seed=seed)
        _samples[mode] = {t: list(v["rr_samples"])
                          for t, v in per_type.items()}
    report = {"ts": datetime.datetime.now(datetime.timezone.utc)
              .isoformat(timespec="seconds"),
              "budget": budget, "k": k, "ci_seed": seed,
              "queryset_sha": sha_queryset(qs), "modes": out,
              "adversarial": guardrail_eval(store)}
    if keep_samples:
        report["rr_samples"] = {m: {t: list(v) for t, v in ts.items()}
                                for m, ts in _samples.items()}
    if "graph" in out or "baseline" in out:
        report["graph_decision"] = graph.scorecard(out)
    store.write("metadata/eval_report.json",
                json.dumps({k: v for k, v in report.items()
                            if k != "rr_samples"},
                           indent=2, sort_keys=True) + "\n")
    return report


def sha_queryset(qs):
    h = hashlib.sha256()
    for q in sorted(qs, key=lambda x: x.get("id", x["query"])):
        h.update(json.dumps(q, sort_keys=True).encode())
    return h.hexdigest()[:16]


# --- seed rotation (G-G3): query-set growth + variance --------------------

def run_rotation(store, seeds, modes=None, budget=600, k=8):
    """Grow the measurement across deterministic seed rotations: each
    seed bootstraps its own queryset split (queries overlap only
    partially — candidate shuffling is seeded), the full harness runs
    per seed, and the report carries BOTH the pooled metrics (per-query
    samples pooled across seeds, bootstrap CI over the pool) and the
    per-seed variance, so n-noise is visible instead of assumed away.
    The graph decision is re-made on the pooled set with CI overlap
    enforced ('inconclusive' beats any winner)."""
    modes = tuple(modes or MODES)
    import statistics
    per_seed, pool_rr, pool_tok = [], {}, {}
    for seed in seeds:
        qs = build_queryset(store, seed=seed)
        rep = run(store, modes=modes, budget=budget, k=k, queryset=qs,
                  keep_samples=True, seed=seed)
        if "error" in rep:
            return rep
        per_seed.append({"seed": seed, "queryset_sha": rep["queryset_sha"],
                         "n": rep["modes"][modes[0]]["n"],
                         "mrr": {m: rep["modes"][m]["mrr"] for m in modes},
                         "graph_decision": rep.get("graph_decision")})
        for m, ts in rep["rr_samples"].items():
            for t, vals in ts.items():
                pool_rr.setdefault(m, {}).setdefault(t, []).extend(vals)
                pool_tok.setdefault(m, []).append(
                    rep["modes"][m]["tokens_per_query"])
    pooled = {}
    for m, ts in pool_rr.items():
        all_v = [v for vals in ts.values() for v in vals]
        n = len(all_v) or 1
        pooled[m] = {
            "n": n,
            "mrr": round(sum(all_v) / n, 4),
            "mrr_ci95": bootstrap_ci(all_v, seed=seeds[0]),
            "tokens_per_query": round(sum(pool_tok[m]) / len(pool_tok[m]),
                                      1),
            "per_type": {t: {"n": len(vals),
                             "mrr": (round(sum(vals) / len(vals), 4)
                                     if vals else None),
                             "ci95": bootstrap_ci(vals, seed=seeds[0])}
                         for t, vals in ts.items()},
        }
    variance = {}
    for m in pool_rr:
        vals = [p["mrr"][m] for p in per_seed if m in p["mrr"]]
        variance[m] = round(statistics.pstdev(vals), 4) if len(
            vals) > 1 else 0.0
    decision = graph.scorecard(pooled) if (
        "graph" in pooled and any(m != "graph" for m in pooled)) else None
    out = {"ts": datetime.datetime.now(datetime.timezone.utc)
           .isoformat(timespec="seconds"),
           "seeds": list(seeds), "budget": budget, "k": k,
           "protocol": "bootstrap-CI seed rotation (G-G3); intervals "
                       "overlap => inconclusive, never a winner",
           "per_seed": per_seed, "modes": pooled,
           "mrr_variance_across_seeds": variance,
           "graph_decision": decision}
    store.write("metadata/eval_rotation.json",
                json.dumps(out, indent=2, sort_keys=True) + "\n")
    return out


# --- S5: protocol stamp -----------------------------------------------------

def stamp(store):
    """Comparability stamp for this harness build: env + corpus digest.
    (silicon-ledger env.md rule: if the environment changed, results
    are not comparable.)"""
    import platform
    corpus_sha = hashlib.sha256()
    n_raw = 0
    for rel in store.list_rel("raw"):
        n_raw += 1
        corpus_sha.update(hashlib.sha256(store.read(rel).encode()).digest())
    git = ""
    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True,
                             cwd=store.root).stdout.strip()
    except OSError:
        pass
    st = {"python": sys.version.split()[0],
          "platform": "%s/%s" % (platform.system(), platform.machine()),
          "fts5": readpath._HAS_FTS5,
          "embedder": "featurehash-%d" % readpath.DIM,
          "raw_files": n_raw,
          "corpus_sha256": corpus_sha.hexdigest()[:16],
          "git_commit": git,
          "ts": datetime.datetime.now(datetime.timezone.utc)
          .isoformat(timespec="seconds")}
    store.write("metadata/eval_stamp.json",
                json.dumps(st, indent=2, sort_keys=True) + "\n")
    return st


# --- claim emission (rule 6) -------------------------------------------------

def headline(report):
    parts = []
    for mode, m in report["modes"].items():
        parts.append("%s mrr=%.4f p@1=%.2f tok/q=%.0f"
                     % (mode, m["mrr"], m.get("p_at_1", 0.0),
                        m["tokens_per_query"]))
    return ("Harness run %s (%d queries, budget %d): %s"
            % (report["ts"], report["modes"][list(report["modes"])[0]]["n"],
               report["budget"], " | ".join(parts)))


def emit_claim(store, report, ledger=None, runner=None):
    """Emit the harness headline as a ledger claim (AGENTS.md rule 6).
    Preferred path: ocl emit (hash-chained ledger). Fallback: event
    note in events.jsonl so nothing is lost, plus the pending file."""
    text = headline(report)
    ledger = ledger or _default_ledger()
    runner = runner or subprocess.run
    digest = base64.urlsafe_b64encode(hashlib.sha256(
        json.dumps(report, sort_keys=True).encode()).digest()
    ).decode().rstrip("=")
    cmd = [os.path.join(_repo_root(), "tools", "ocl", "ocl"),
           "emit", "--text", text, "--type", "calculation",
           "--source-uri", "mem://metadata/eval_report.json",
           "--source-digest", digest]
    try:
        r = runner(cmd, capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        r, ok = None, False
    if not ok:
        store.append_event({"event": "benchmark_claim_pending",
                            "text": text, "ledger": ledger})
        return {"emitted": "pending", "text": text}
    return {"emitted": "ledger", "text": text,
            "stdout": (r.stdout or "").strip()[:200]}


def _repo_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__),
                                        *[".."] * 3))


def _default_ledger():
    return os.path.join(_repo_root(), "claims", "claims.jsonl")
