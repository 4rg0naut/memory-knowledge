import json
import unittest

from mem import daily, distill, graph, hygiene
from mem.store import Store
import os
import shutil
import tempfile

RAW1 = """# Session 2026-10-17 mini rollout

## Deploy failure

turn 2 — incident: deploy_memory.sh failed on mini because the
tailnet share quota was exceeded; backup_memory.sh aborted mid-copy
and left a partial tarball that the nightly verifier kept flagging
for two days until someone correlated the timestamp with the quota
event. Agent noted deploy_memory.sh must checkpoint before retry,
and the retry loop must abort on quota errors instead of pretending
the mount is just slow, because that is how the whole evening was
lost. The postmortem line in the journal names both scripts and the
launchd job so future greps land on this exact incident quickly.

## Rollout decision

turn 8 — decision: keep deploy_memory.sh as the single bootstrap
entry for mini; backup_memory.sh runs only from launchd so a human
shell can never accidentally overwrite the last known good snapshot
while the fleet is mid-migration. The rationale is that a second
manual entry point doubles the blast radius of a typo on the share,
and the audit trail is easier to reason about when scheduled jobs
own the write path entirely and interactive sessions stay read-only
against the mount for the duration of the rollout window.
"""
RAW2 = """# Session 2026-10-18 inbox triage

turn 1 — knowledge inbox capture for entity_index: the graph build
walks entity_index nodes and links them to the source spans behind
each claim, while prune-gate metrics post as claims of their own so
harness numbers carry lineage like any other fact. The triage also
renamed the stale launchd plist entries, cross-checked the backup
rotation schedule against the new share quota, and left a note for
the next operator about which journal files are safe to compress.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-dg-")
        self.store = Store(self.root)
        self.rel1 = self.store.write_raw("mem://s/17", RAW1,
                                         "2026-10-17")[0]
        self.rel2 = self.store.write_raw("mem://s/18", RAW2,
                                         "2026-10-18")[0]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestDaily(Base):
    def test_cards_created_with_anchors(self):
        created = daily.build_daily(self.store, today="2026-10-17")
        self.assertEqual(len(created), 2)
        card = self.store.read(created[0]["rel"])
        self.assertIn("[[%s#L" % self.rel1, card)
        self.assertIn("## Sources", card)
        self.assertIn("source: [[%s]]" % self.rel1, card)

    def test_idempotent(self):
        daily.build_daily(self.store, today="2026-10-17")
        before = os.listdir(os.path.join(self.store.root, "daily",
                                         "2026-10-17"))
        again = daily.build_daily(self.store, today="2026-10-17")
        self.assertEqual(again, [])
        after = os.listdir(os.path.join(self.store.root, "daily",
                                        "2026-10-17"))
        self.assertEqual(before, after)

    def test_raw_untouched(self):
        before = self.store.read(self.rel1)
        daily.build_daily(self.store, today="2026-10-17")
        self.assertEqual(self.store.read(self.rel1), before)


class TestConsolidate(Base):
    def test_cap_and_quote_gate(self):
        daily.build_daily(self.store, today="2026-10-18")
        distill.distill_raw(self.store, self.rel1, "2026-10-17")
        distill.distill_raw(self.store, self.rel2, "2026-10-18")
        units = daily.consolidate(self.store, today="2026-10-18",
                                 max_units=1)
        self.assertEqual(len(units), 1)
        self.assertIn("dst", units[0])
        self.assertTrue("claim" in units[0] or "rejected" in units[0])
        for u in units:
            if "rejected" in u:
                self.assertIn("quote", u["rejected"].lower())

    def test_no_repromote(self):
        distill.distill_raw(self.store, self.rel1, "2026-10-17")
        first = daily.consolidate(self.store, today="2026-10-18")
        second = daily.consolidate(self.store, today="2026-10-18")
        self.assertTrue(first)
        self.assertTrue(all("dst" in u for u in first))
        self.assertEqual(second, [])

    def test_window_filter(self):
        distill.distill_raw(self.store, self.rel1, "2026-10-17")
        units = daily.consolidate(self.store, today="2026-10-31",
                                 window_days=2)
        self.assertEqual(units, [])

    def test_promoted_claim_carries_source_edge(self):
        distill.distill_raw(self.store, self.rel1, "2026-10-17")
        units = [u for u in daily.consolidate(self.store,
                                              today="2026-10-18")
                 if "claim" in u]
        self.assertTrue(units)
        _, _, claims = self.store.parse_page(units[0]["page"])
        claim = next(c for c in claims if c["id"] == units[0]["claim"])
        targets = hygiene.schema.claim_edges(claim, "derived_from")
        self.assertTrue(any(self.rel1 in t for t in targets))


class TestScorecard(unittest.TestCase):
    def modes(self, multi_g=0.5, multi_b=0.1, conc_g=0.6, conc_b=0.5,
              exact_g=1.0, exact_b=1.0, tok_g=400, tok_b=400):
        return {"baseline": {
                    "per_type": {"multihop": {"n": 10, "mrr": multi_b},
                                 "conceptual": {"n": 10, "mrr": conc_b},
                                 "exact": {"n": 10, "mrr": exact_b}},
                    "tokens_per_query": tok_b},
                "graph": {
                    "per_type": {"multihop": {"n": 10, "mrr": multi_g},
                                 "conceptual": {"n": 10, "mrr": conc_g},
                                 "exact": {"n": 10, "mrr": exact_g}},
                    "tokens_per_query": tok_g}}

    def test_keep_when_multihop_wins_single_hop_holds(self):
        self.assertEqual(graph.scorecard(self.modes()), "keep-graph")

    def test_drop_when_multihop_loses(self):
        self.assertEqual(graph.scorecard(self.modes(multi_g=0.0)),
                         "drop-to-routed")

    def test_drop_on_single_hop_degradation(self):
        self.assertEqual(
            graph.scorecard(self.modes(exact_g=1.0 - 2 *
                                       graph.EXACT_TOLERANCE)),
            "drop-to-routed")

    def test_drop_on_token_blowout(self):
        self.assertEqual(
            graph.scorecard(self.modes(tok_g=self.modes()["graph"]
                                       ["tokens_per_query"] * 2)),
            "drop-to-routed")

    def test_insufficient_without_graph(self):
        self.assertEqual(graph.scorecard({"baseline": {}}),
                         "insufficient-data")
        m = self.modes()
        m["graph"]["per_type"]["multihop"]["n"] = 0
        self.assertEqual(graph.scorecard(m), "insufficient-data")


class TestGraph(Base):
    def test_build_edges_typed_bitemporal(self):
        self.store.ensure_page("wiki/entities/mini.md")
        hygiene.ingest(self.store, "wiki/entities/mini.md", {
            "text": "deploy_memory.sh and backup_memory.sh run on mini",
            "pred": "other", "status": "unverified", "confidence": 0.6,
            "date": "2026-10-17", "valid_at": "2026-10-01",
            "invalid_at": "2026-10-15",
            "edges": [{"type": "derived_from", "target": self.rel1}]})
        n = graph.build(self.store)
        self.assertGreater(n, 0)
        edges = graph.load_graph(self.store)
        self.assertEqual(len(edges), n)
        co = [e for e in edges if e["type"] == "co_mentioned"]
        self.assertTrue(co)
        for e in edges:
            self.assertIn(e["type"], graph.EDGE_TYPES)
            self.assertTrue(e["via"])
        df = next(e for e in edges if e["type"] == "derived_from")
        self.assertEqual(df["valid_at"], "2026-10-01")
        self.assertEqual(df["invalid_at"], "2026-10-15")

    def test_expand_two_hops_and_asof(self):
        edges = [
            {"src": "alpha", "dst": "beta", "type": "co_mentioned",
             "valid_at": "2026-01-01", "invalid_at": None, "via": "p#1"},
            {"src": "beta", "dst": "gamma", "type": "co_mentioned",
             "valid_at": "2026-01-01", "invalid_at": "2026-06-01",
             "via": "p#2"},
        ]
        hits = graph.expand("Alpha", edges=edges)
        self.assertEqual(hits["alpha"]["distance"], 0)
        self.assertEqual(hits["beta"]["distance"], 1)
        self.assertEqual(hits["gamma"]["distance"], 2)
        self.assertEqual(hits["gamma"]["hops"], ["co_mentioned",
                                                 "co_mentioned"])
        stale = graph.expand("Alpha", edges=edges, asof="2026-07-01")
        self.assertNotIn("gamma", stale)
        in_win = graph.expand("Alpha", edges=edges, asof="2026-03-01")
        self.assertEqual(in_win["gamma"]["distance"], 2)

    def test_hop_cap(self):
        edges = [{"src": "node%d" % i, "dst": "node%d" % (i + 1),
                  "type": "co_mentioned", "valid_at": None,
                  "invalid_at": None, "via": "v"} for i in range(4)]
        hits = graph.expand("Node0", edges=edges)
        self.assertNotIn("node3", hits)

    def test_link_docs_maps_entities(self):
        docs = [{"id": "d1", "text": "notes about backup_memory.sh run"}]
        got = graph.link_docs(docs, {"backup_memory.sh":
                                     {"distance": 1, "hops": []}})
        self.assertEqual(got, [("d1", 1)])

    def test_graph_via_readpath_carries_tags(self):
        daily.build_daily(self.store, today="2026-10-18")
        distill.distill_raw(self.store, self.rel1, "2026-10-17")
        graph.build(self.store)
        from mem import readpath
        hits = readpath.search(self.store, "deploy_memory.sh quota",
                               mode="graph")
        for h in hits:
            self.assertTrue(h["tags"].startswith("["))


if __name__ == "__main__":
    unittest.main()
