import json
import unittest

from mem import distill, evalkit, graph, hygiene, readpath
from mem.store import Store
import shutil
import tempfile

RAW = """# Session 2026-10-17 harness design

## Queryset bootstrap protocol

turn 4 — decision: bootstrap the queryset from checkpointing and
bitemporal transcripts; longmemeval style grading with consensus
graders replaces single-LLM judging on this corpus. The deploy
scripts deploy_memory.sh and backup_memory.sh are cited as the
worked example of the audit trail we want to reproduce, because
the mini rollout kept a full retry history that made the eventual
quota incident traceable to the launchd restart loops running on
the tailnet share mount during the capture window. The bootstrap
also records which host captured each exchange so provenance
survives every later migration step and every operator audit on
the fleet without needing to reopen the original journal files.

## Token accounting

turn 9 — incident: the harness reported recall without
tokens_per_query; fieldguide says a score without tokens is noise;
budget enforcement got added to the packing path after the overrun
observed on mini, and every packed item now carries its citation
tag so an agent can never inject a claim without its lineage
attached. This is the same discipline launchd_plist applies when
stamping machine evidence: the audit row is only trustworthy when
the source anchor travels with it through every later read path.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-e-")
        self.store = Store(self.root)
        self.rel = self.store.write_raw("mem://s/harness", RAW,
                                        "2026-10-17")[0]
        self.store.ensure_page("wiki/entities/harness.md")
        hygiene.ingest(self.store, "wiki/entities/harness.md", {
            "text": "harness rule: bitemporal transcripts need "
                    "checkpointing for the queryset bootstrap",
            "pred": "decision", "status": "unverified", "confidence": 0.6,
            "date": "2026-10-17",
            "edges": [{"type": "derived_from", "target": self.rel}]})
        distill.distill_raw(self.store, self.rel, "2026-10-17")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestQueryset(Base):
    def test_three_types_with_golds(self):
        qs = evalkit.build_queryset(self.store, n=9, seed=1)
        self.assertTrue(qs)
        types = {q["type"] for q in qs}
        self.assertLessEqual({"exact", "phrase", "conceptual"}, types)
        for q in qs:
            self.assertTrue(q["gold"], q)
            self.assertTrue(q["id"].startswith("q_"))

    def test_deterministic_seed(self):
        a = evalkit.build_queryset(self.store, n=6, seed=7)
        b = evalkit.build_queryset(self.store, n=6, seed=7)
        self.assertEqual([q["id"] for q in a], [q["id"] for q in b])

    def test_save_load_sha(self):
        qs = evalkit.build_queryset(self.store, n=6, seed=3)
        evalkit.save_queryset(self.store, qs)
        back = evalkit.load_queryset(self.store)
        self.assertEqual(back, qs)
        self.assertEqual(evalkit.sha_queryset(back),
                         evalkit.sha_queryset(qs))


class TestGraders(Base):
    def test_phrase_and_consensus(self):
        docs = readpath.corpus(self.store)
        g = dict(zip(("coverage", "phrase", "rare"),
                     evalkit.make_graders(docs)))
        doc = next(d for d in docs if "bitemporal" in d["text"])
        self.assertEqual(g["phrase"]("bitemporal transcripts need", doc), 3)
        self.assertEqual(g["phrase"]("quantum flux capacitor", doc), 0)
        grade = evalkit.consensus_grades(
            "bitemporal transcripts need checkpointing", doc,
            evalkit.make_graders(docs))
        self.assertIn(grade, (0, 1, 2, 3))


class TestRun(Base):
    def test_metrics_and_report(self):
        qs = evalkit.build_queryset(self.store, n=6, seed=2)
        rep = evalkit.run(self.store, modes=("baseline", "fused"),
                          budget=300, queryset=qs)
        self.assertNotIn("error", rep)
        for mode in ("baseline", "fused"):
            m = rep["modes"][mode]
            for key in ("mrr", "p_at_1", "mean_grade",
                        "tokens_per_query", "per_type", "n"):
                self.assertIn(key, m)
            self.assertLessEqual(m["tokens_per_query"], 300)
            self.assertGreaterEqual(m["n"], 1)
        self.assertEqual(rep["budget"], 300)
        got = json.loads(self.store.read("metadata/eval_report.json"))
        self.assertEqual(got["modes"], rep["modes"])

    def test_headline_mentions_scores(self):
        qs = evalkit.build_queryset(self.store, n=6, seed=2)
        rep = evalkit.run(self.store, modes=("fused",), budget=200,
                          queryset=qs)
        text = evalkit.headline(rep)
        self.assertIn("fused mrr=", text)
        self.assertIn("tok/q=", text)


class TestMultihopAndDecision(Base):
    def test_queryset_includes_multihop_with_invisible_golds(self):
        graph.build(self.store)
        qs = evalkit.build_queryset(self.store, n=40, seed=3)
        mh = [q for q in qs if q["type"] == "multihop"]
        self.assertTrue(mh)
        docs = {d["id"]: d for d in readpath.corpus(self.store)}
        for q in mh:
            gold = docs[q["gold"][0]]["text"].casefold()
            gold_toks = set(evalkit._qs_token_re.findall(gold))
            anchor = " ".join(q["query"].split()[:-1])
            anchor_toks = set(evalkit._qs_token_re.findall(anchor))
            self.assertFalse(anchor_toks & gold_toks,
                             "gold must be lexically invisible: %s"
                             % q["query"])

    def test_run_reports_graph_decision(self):
        graph.build(self.store)
        qs = evalkit.build_queryset(self.store, n=30, seed=5)
        rep = evalkit.run(self.store,
                          modes=("baseline", "fused", "graph"),
                          budget=300, queryset=qs)
        self.assertIn(rep.get("graph_decision"),
                      ("keep-graph", "drop-to-routed", "insufficient-data",
                       "inconclusive"))
        got = json.loads(self.store.read("metadata/eval_report.json"))
        self.assertEqual(got["graph_decision"], rep["graph_decision"])

    def test_fused_not_below_baseline(self):
        graph.build(self.store)
        qs = evalkit.build_queryset(self.store, n=40, seed=11)
        rep = evalkit.run(self.store, modes=("baseline", "fused"),
                          budget=600, queryset=qs)
        self.assertGreaterEqual(rep["modes"]["fused"]["mrr"],
                                rep["modes"]["baseline"]["mrr"])


class TestStampEmit(Base):
    def test_stamp_fields(self):
        st = evalkit.stamp(self.store)
        for key in ("python", "platform", "fts5", "embedder",
                    "raw_files", "corpus_sha256", "git_commit", "ts"):
            self.assertIn(key, st)
        self.assertEqual(st["embedder"], "featurehash-%d" % readpath.DIM)
        self.assertEqual(st["raw_files"], 1)
        self.assertTrue(self.store.exists("metadata/eval_stamp.json"))

    def test_emit_via_ledger(self):
        seen = {}

        def runner(cmd, **kw):
            seen["cmd"] = cmd

            class R:
                returncode = 0
                stdout = "emitted clm_test"
            return R()

        rep = {"ts": "t", "budget": 1, "modes": {"fused": {"n": 2,
               "mrr": 0.5, "p_at_1": 0.5, "tokens_per_query": 10}}}
        out = evalkit.emit_claim(self.store, rep,
                                ledger="claims/claims.jsonl",
                                runner=runner)
        self.assertEqual(out["emitted"], "ledger")
        self.assertIn("emit", seen["cmd"])
        self.assertIn("--type", seen["cmd"])
        self.assertIn("calculation", seen["cmd"])

    def test_emit_fallback_pending(self):
        def runner(cmd, **kw):
            class R:
                returncode = 1
                stdout = ""
            return R()

        rep = {"ts": "t", "budget": 1, "modes": {"fused": {"n": 1,
               "mrr": 0.0, "p_at_1": 0.0, "tokens_per_query": 5}}}
        out = evalkit.emit_claim(self.store, rep, runner=runner)
        self.assertEqual(out["emitted"], "pending")
        events = [json.loads(l) for l in
                  self.store.read("events.jsonl").splitlines() if l.strip()]
        pending = [e for e in events
                   if e["event"] == "benchmark_claim_pending"]
        self.assertEqual(len(pending), 1)
        self.assertIn("fused mrr=", pending[0]["text"])


if __name__ == "__main__":
    unittest.main()
