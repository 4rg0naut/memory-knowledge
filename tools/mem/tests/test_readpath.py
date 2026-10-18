import datetime
import unittest

from mem import distill, hygiene, readpath
from mem.store import Store
import shutil
import tempfile

RAW = """# Session log 2026-10-17

## Prune gate migration

turn 3 — incident: the prune-gate harness on mini failed because
events.jsonl quota exceeded; retry loop rewrote partial JSON lines
until raw/2026-10-17_session.md capture aborted with SIGKILL.
fix: split capture into chunked writes with fsync checkpointing so a
restart resumes from the last complete line instead of truncating the
whole journal. The same quota bug had already eaten one evening of
capture logs on the studio host, and operators kept blaming tailscale
share flapping until the events.jsonl size audit proved otherwise.
The checkpoint design also stops the retry loop from amplifying a
transient mount hiccup into a corrupted journal, which is what turned
this from a nuisance into a data-integrity incident last month.

## Embedding notes

turn 9 — decision: keep the featurehash-512 offline embedder because
mini has no GPU; the XERJ default embedder class fits the stdlib rule
and keeps recall deterministic for the audit trail. A neural provider
can be swapped behind the same embed callable later without touching
stored vectors, since every document is re-embedded from raw at query
time anyway and the corpus stays the single source of truth for the
read path across the whole fleet and every future migration on mini.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-r-")
        self.store = Store(self.root)
        self.rel = self.store.write_raw("mem://session/log", RAW,
                                        "2026-10-17")[0]
        self.store.ensure_page("wiki/entities/prune-gate.md")
        hygiene.ingest(self.store, "wiki/entities/prune-gate.md", {
            "text": "prune-gate harness owner: keep featurehash embedder",
            "pred": "decision", "status": "unverified", "confidence": 0.6,
            "date": "2026-10-17",
            "edges": [{"type": "derived_from", "target": self.rel}]})
        distill.distill_raw(self.store, self.rel, "2026-10-17")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)


class TestCorpus(Base):
    def test_kinds_and_tags(self):
        docs = readpath.corpus(self.store)
        kinds = {d["kind"] for d in docs}
        self.assertLessEqual({"claim", "verbatim", "distilled"}, kinds)
        for d in docs:
            self.assertTrue(d["tags"].startswith("["), d["tags"])
        claim = next(d for d in docs if d["kind"] == "claim")
        self.assertIn("[claim:%s|unverified]" % claim["id"], claim["tags"])

    def test_asof_drops_later_and_invalidated(self):
        docs = readpath.corpus(self.store, asof="2020-01-01")
        self.assertEqual(docs, [])
        docs = readpath.corpus(self.store, asof="2026-10-17")
        self.assertTrue(docs)


class TestRanking(Base):
    def docs(self):
        return readpath.corpus(self.store)

    def test_fts5_and_python_top_hit_parity(self):
        docs = self.docs()
        fts = readpath.build_fts5(docs)
        py = readpath.PythonBM25(docs)
        query = "featurehash embedder mini GPU"
        a = readpath.fts5_search(fts, query, 5)
        b = py.search(query, 5)
        self.assertTrue(a and b)
        self.assertEqual(docs[a[0]]["id"], docs[b[0]]["id"])
        for tok in ("featurehash", "embedder"):
            self.assertIn(tok, docs[a[0]]["text"].casefold())

    def test_fts5_absent_fallback(self):
        saved = readpath._HAS_FTS5
        readpath._HAS_FTS5 = False
        try:
            hits = readpath.search(self.store, "featurehash embedder",
                                   mode="baseline")
        finally:
            readpath._HAS_FTS5 = saved
        self.assertTrue(hits)

    def test_rrf_fuses_by_rank(self):
        fused = readpath.rrf([[0, 1], [0]])
        self.assertEqual(fused[0][1], 0)  # (score, idx) pair, doc 0 first
        self.assertGreater(fused[0][0], fused[1][0])

    def test_recency_and_importance(self):
        today = datetime.date(2026, 10, 18)
        self.assertGreater(readpath.recency("2026-10-17", today),
                           readpath.recency("2025-01-01", today))
        self.assertEqual(readpath.recency("garbage", today), 0.0)
        claim = {"kind": "claim", "status": "verified"}
        self.assertGreater(readpath.importance(claim),
                           readpath.importance({"kind": "verbatim"}))


class TestSearchPack(Base):
    def test_search_tags_and_scores(self):
        hits = readpath.search(self.store, "prune gate events.jsonl")
        self.assertTrue(hits)
        for h in hits:
            self.assertTrue(h["tags"].startswith("["))
            self.assertGreaterEqual(h["score"], 0.0)

    def test_all_modes_return(self):
        for mode in ("baseline", "distilled", "fused", "graph"):
            hits = readpath.search(self.store,
                                   "featurehash embedder offline",
                                   mode=mode)
            self.assertIsInstance(hits, list, mode)

    def test_pack_budget_and_tags(self):
        hits = readpath.search(self.store, "featurehash embedder mini")
        items, used = readpath.pack(hits, 80)
        self.assertLessEqual(used, 80)
        for it in items:
            self.assertTrue(it["tag"].startswith("["))
            if it.get("truncated"):
                self.assertGreaterEqual(len(it["text"]), 40)

    def test_recall_end_to_end(self):
        got = readpath.recall(self.store, "prune gate capture failure",
                              budget=300)
        self.assertLessEqual(got["tokens_used"], 300)
        self.assertTrue(got["items"])
        self.assertTrue(all(i["tag"].startswith("[")
                            for i in got["items"]))


if __name__ == "__main__":
    unittest.main()
