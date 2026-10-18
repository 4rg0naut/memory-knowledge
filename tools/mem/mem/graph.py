"""E2: entity graph with typed bitemporal edges (ADR-0011).

Graphiti/HippoRAG pattern for project knowledge: entities extracted
from claims, distilled exchanges, and daily cards become nodes; edges
carry a type (co_mentioned / derived_from / contradicts / superseded)
plus valid_at / invalid_at taken from the underlying claim's validity
window, so "who believed what after which event" is a filter, not a
reconstruction. The graph is derived state: metadata/graph.jsonl is
rebuildable from files and never hand-edited (Memory as File).

Recall NEVER runs graph-only (Mem0 evidence: graphs hurt single-hop):
expand() results join the readpath fusion as a third consensus list
(CombMNZ; keep/drop verdict measured per run by scorecard() and
recorded in docs/experiments/).
"""

import json
import re
from collections import defaultdict

from . import chunking, codec, distill, schema

EDGE_TYPES = ["co_mentioned", "derived_from", "contradicts", "superseded"]
GRAPH_REL = "metadata/graph.jsonl"
MAX_HOPS = 2


def norm_entity(e):
    return e.strip(" .-`'\"").casefold()


def entities_of_claim(claim):
    return set(norm_entity(e) for e in distill.extract_entities(claim["text"]))


def build(store):
    """Rebuild metadata/graph.jsonl from current files. Returns edge
    count. Every edge carries type + validity window + provenance."""
    edges = []

    def add(src, dst, etype, valid_at=None, invalid_at=None, via=None):
        if src == dst or not src or not dst:
            return
        edges.append({"src": src, "dst": dst, "type": etype,
                      "valid_at": valid_at, "invalid_at": invalid_at,
                      "via": via})

    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        for c in claims:
            ents = sorted(entities_of_claim(c))
            for i, a in enumerate(ents):
                for b in ents[i + 1:]:
                    add(a, b, "co_mentioned", c.get("valid_at") or c["date"],
                        c.get("invalid_at"), "%s#%s" % (page, c["id"]))
            for e in c["edges"]:
                if e["type"] == "derived_from":
                    add(ents[0] if ents else page,
                        e["target"].split("#")[0], "derived_from",
                        c.get("valid_at") or c["date"], c.get("invalid_at"),
                        c["id"])
                elif e["type"] in ("contradicts", "superseded_by"):
                    other = e["target"].split("#")[-1]
                    add(ents[0] if ents else page, other,
                        "contradicts" if e["type"] == "contradicts"
                        else "superseded", c["date"], None, c["id"])

    for obj in distill.load_distilled(store):
        ents = sorted(set(distill.extract_entities(
            obj["exchange_core"] + " " + obj["specific_context"])
            + [r["key"] for r in obj["room_assignments"]]))
        ents = [norm_entity(e) for e in ents]
        for i, a in enumerate(ents[:6]):
            for b in ents[i + 1:6]:
                add(a, b, "co_mentioned", obj["date"], None, obj["id"])

    for page in _daily_pages(store):
        text = store.read(page)
        for parsed in _iter_links(text):
            rel, start, end = parsed
            ents = [norm_entity(e) for e in
                    distill.extract_entities(text)][:6]
            for e in ents:
                add(e, rel.split("/")[-1], "derived_from", None, None,
                    chunking.anchor(rel, start, end) if start else rel)

    store.write(GRAPH_REL, "".join(json.dumps(e, sort_keys=True) + "\n"
                                   for e in edges))
    store.append_event({"event": "graph_build", "edges": len(edges)})
    return len(edges)


def load_graph(store):
    """Derived view: torn lines (crash mid-append, hand-edit damage)
    are dropped, not fatal — `mem graph --build` regenerates from
    files, which are the source of truth. Dropped count is appended
    to events so the degradation is recorded, never silent."""
    if not store.exists(GRAPH_REL):
        return []
    edges, torn = codec.read_jsonl(store.read(GRAPH_REL))
    if torn:
        store.append_event({"event": "graph_view_torn_lines",
                            "dropped": len(torn),
                            "lines": [t["line"] for t in torn]})
    return edges


def adjacency(edges):
    adj = defaultdict(list)
    for e in edges:
        adj[e["src"]].append(e)
        adj[e["dst"]].append({"src": e["dst"], "dst": e["src"],
                              "type": e["type"], "valid_at": e["valid_at"],
                              "invalid_at": e["invalid_at"], "via": e["via"]})
    return adj


def expand(query, store=None, edges=None, max_hops=MAX_HOPS, asof=None):
    """BFS from query entities (hop cap 2). Returns
    {entity: {'distance': n, 'hops': [edge types]}} including distance
    0 for direct matches. asof: skip edges whose validity window ended
    before the date (bitemporal query)."""
    edges = edges if edges is not None else load_graph(store)
    adj = adjacency(edges)
    qents = set(norm_entity(e) for e in distill.extract_entities(query))
    direct = set()
    for node in adj:
        for q in qents:
            if q in node or node in q:
                direct.add(node)
    seen = {n: {"distance": 0, "hops": []} for n in direct}
    frontier = set(direct)
    for hop in range(1, max_hops + 1):
        nxt = set()
        for node in frontier:
            for e in adj.get(node, []):
                if asof and e.get("invalid_at") and e["invalid_at"] <= asof:
                    continue
                dst = e["dst"]
                if dst not in seen:
                    seen[dst] = {"distance": hop,
                                 "hops": seen[node]["hops"] + [e["type"]]}
                    nxt.add(dst)
        frontier = nxt
    return seen


def link_docs(docs, entity_hits):
    """Map expanded entity hits back to corpus docs: a doc matches an
    entity if the (lowercased) entity occurs in its text. Returns list
    of (doc_id, best_distance)."""
    scored = {}
    for ent, meta in entity_hits.items():
        for d in docs:
            if ent and ent in d["text"].casefold():
                cur = scored.get(d["id"])
                if cur is None or meta["distance"] < cur:
                    scored[d["id"]] = meta["distance"]
    return sorted(scored.items(), key=lambda t: (t[1], t[0]))


EXACT_TOLERANCE = 0.05   # allowed single-hop (exact) degradation vs baseline
TOKEN_TOLERANCE = 1.25   # allowed tok/q inflation for graph mode


def ci_overlap(ci_a, ci_b):
    """True when two 95% intervals share any ground — a winner may not
    be declared across overlapping intervals (G-G3)."""
    return bool(ci_a and ci_b and ci_a[0] <= ci_b[1] and ci_b[0] <= ci_a[1])


def scorecard(modes_report):
    """Decision rule (E2): keep the graph only if it wins on multi-hop
    /entity-chain query types (multihop, conceptual) against the best
    non-graph mode (usually fused — the real competitor, not the
    baseline), does not degrade single-hop exact beyond noise, and
    stays within a bounded token cost over that reference. Wired into
    evalkit.run; the verdict lands in eval_report.json as
    graph_decision — the decision is recorded, never vibes. When
    bootstrap CIs are present and the multihop intervals overlap, the
    verdict is "inconclusive" before any drop/keep is declared (G-G3:
    sampling noise may not decide architecture)."""
    g = modes_report.get("graph")
    refs = {k: v for k, v in modes_report.items()
            if k != "graph" and v.get("per_type")}
    if not g or not refs:
        return "insufficient-data"
    ref = max(refs.values(), key=lambda v: v.get("mrr", 0.0))
    gm, rm = g["per_type"], ref["per_type"]
    if not gm.get("multihop", {}).get("n") or not rm.get("multihop",
                                                          {}).get("n"):
        return "insufficient-data"
    if ci_overlap(gm["multihop"].get("ci95"), rm["multihop"].get("ci95")):
        return "inconclusive"

    def gain(t):
        return gm.get(t, {}).get("mrr", 0.0) - rm.get(t, {}).get("mrr", 0.0)

    multi_gain = (gain("multihop") + gain("conceptual")) / 2.0
    exact_drop = -gain("exact")
    if multi_gain <= 0:
        return "drop-to-routed"
    if exact_drop > EXACT_TOLERANCE:
        return "drop-to-routed"
    if g["tokens_per_query"] > ref["tokens_per_query"] * TOKEN_TOLERANCE:
        return "drop-to-routed"
    return "keep-graph"


def _daily_pages(store):
    return store.list_rel("daily")


def _iter_links(text):
    for m in chunking._ANCHOR_LINK_RE.finditer(text):
        yield m.group(1).strip(), \
            int(m.group(2)) if m.group(2) else None, \
            int(m.group(3)) if m.group(3) else None
