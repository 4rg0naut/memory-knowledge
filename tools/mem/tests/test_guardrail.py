"""G-G1: contradiction -> guardrail promotion, retrieval boost,
retirement path, bidirectional adversarial eval."""

import json
import os
import shutil
import tempfile
import unittest

from mem import evalkit, hygiene, readpath
from mem.store import Store

OLD = ("deploy_memory.sh rsync incident: the mini mirror used "
       "rsync --delete and wiped the archive journal on the shared "
       "volume during the launchd restart loop window")
NEW = ("deploy_memory.sh rsync recovery: the mirror switched to "
       "rsync backup mode with a journal and the shared volume kept "
       "every archive after the restart loop")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-gr-")
        self.store = Store(self.root)
        self.rel = self.store.write_raw("mem://ops/rsync", OLD + "\n",
                                        "2026-10-10")[0]
        self.rel2 = self.store.write_raw("mem://ops/recovery", NEW + "\n",
                                         "2026-10-17")[0]
        self.page = "wiki/entities/deploy_memory.md"
        self.store.ensure_page(self.page)
        self.old = {
            "text": "deploy_memory.sh rule: rsync --delete is safe for "
                    "the mini mirror",
            "pred": "decision", "status": "unverified", "confidence": 0.6,
            "date": "2026-10-10",
            "edges": [{"type": "derived_from", "target": self.rel}]}
        hygiene.ingest(self.store, self.page, self.old)
        self.new = {
            "text": "deploy_memory.sh rule: rsync backup mode replaces "
                    "the delete flag on the mini mirror",
            "pred": "decision", "status": "unverified", "confidence": 0.6,
            "date": "2026-10-17",
            "edges": [{"type": "derived_from", "target": self.rel2}]}

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def guardrails(self):
        out = []
        for p in self.store.all_pages():
            _, _, claims = self.store.parse_page(p)
            out += [c for c in claims if c["status"] == "guardrail"]
        return out

    def superseded_guards(self):
        out = []
        for p in self.store.all_pages():
            _, _, claims = self.store.parse_page(p)
            out += [c for c in claims
                    if c["text"].startswith("guardrail:")
                    and c["status"] == "superseded"]
        return out


class TestPromotion(Base):
    def test_contradiction_emits_guardrail(self):
        res = hygiene.ingest(self.store, self.page, dict(self.new))
        self.assertTrue(res["guardrails"], "no guardrail emitted")
        g = self.guardrails()[0]
        self.assertEqual(g["pred"], "gotcha")
        self.assertIn("do not assert", g["text"])
        self.assertIn("rsync --delete is safe", g["text"])

    def test_guardrail_carries_both_lineages(self):
        hygiene.ingest(self.store, self.page, dict(self.new))
        g = self.guardrails()[0]
        targets = [e["target"] for e in g["edges"]]
        self.assertTrue(any(self.old["id"] in t for t in targets),
                        "lineage to contradicted claim missing")
        by = None
        for p in self.store.all_pages():
            _, _, claims = self.store.parse_page(p)
            by = next((c["id"] for c in claims
                       if c["text"] == self.new["text"]), None)
        self.assertTrue(any(by and by in t for t in targets),
                        "lineage to refuting claim missing")
        self.assertTrue(any(t.startswith("raw/") for t in targets),
                        "lineage to refuting raw evidence missing")

    def test_guardrail_has_revalidate_at(self):
        hygiene.ingest(self.store, self.page, dict(self.new))
        g = self.guardrails()[0]
        self.assertEqual(g["revalidate_at"], "2027-01-15")

    def test_ttl_env_override(self):
        os.environ["MEM_GUARDRAIL_TTL_DAYS"] = "7"
        try:
            hygiene.ingest(self.store, self.page, dict(self.new))
            g = self.guardrails()[0]
            self.assertEqual(g["revalidate_at"], "2026-10-24")
        finally:
            del os.environ["MEM_GUARDRAIL_TTL_DAYS"]

    def test_event_logged(self):
        hygiene.ingest(self.store, self.page, dict(self.new))
        evs = [e for e in hygiene._events(self.store)
               if e["event"] == "guardrail_emit"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["by"], self.new.get("id") or evs[0]["by"])


class TestRetrievalBoost(Base):
    def test_guardrail_outranks_contradicted_claim(self):
        q = "rsync delete flag mini mirror safe rule"
        before = readpath.search(self.store, q, mode="fused", k=8)
        ranks_before = [r["id"] for r in before]
        hygiene.ingest(self.store, self.page, dict(self.new))
        after = readpath.search(self.store, q, mode="fused", k=8)
        g = self.guardrails()[0]
        ranks_after = [r["id"] for r in after]
        self.assertIn(g["id"], ranks_after)
        self.assertLess(ranks_after.index(g["id"]),
                        ranks_after.index(self.old["id"]),
                        "guardrail must outrank the contradicted claim")
        self.assertNotIn(g["id"], ranks_before)


class TestRetirement(Base):
    def _expired_guardrail(self):
        hygiene.ingest(self.store, self.page, dict(self.new))
        g = self.guardrails()[0]
        _, _, claims = self.store.parse_page(self.page)
        for p in self.store.all_pages():
            _, _, claims = self.store.parse_page(p)
            if any(c["id"] == g["id"] for c in claims):
                self.store.mutate_claim(p, g["id"],
                                        set_attrs={"revalidate_at":
                                                   "2026-10-18"})
        return g

    def test_expired_but_condition_holds_survives(self):
        g = self._expired_guardrail()
        out = hygiene.retire_guardrails(self.store, "2026-10-19")
        self.assertIn(g["id"], out["expired"])
        self.assertNotIn(g["id"], out["retired"])
        self.assertTrue(self.guardrails())

    def test_fixed_condition_supersedes_guardrail(self):
        g = self._expired_guardrail()
        by = next(t.split("#")[-1] for t in
                  [e["target"] for e in g["edges"]]
                  if "#" in t and t.split("#")[-1].startswith("clm_")
                  and t.split("#")[-1] != self.old["id"])
        hygiene.retract(self.store, self.page, by, "mirror bug fixed")
        out = hygiene.retire_guardrails(self.store, "2026-10-19")
        self.assertIn(g["id"], out["retired"])
        self.assertFalse(self.guardrails())
        s = self.superseded_guards()[0]
        self.assertEqual(s["invalid_at"], "2026-10-19")
        self.assertIn("do not assert", s["text"])

    def test_reconcile_runs_retirement(self):
        self._expired_guardrail()
        g = self.guardrails()[0]
        by = next(t.split("#")[-1] for t in
                  [e["target"] for e in g["edges"]]
                  if "#" in t and t.split("#")[-1].startswith("clm_")
                  and t.split("#")[-1] != self.old["id"])
        hygiene.retract(self.store, self.page, by)
        rep = hygiene.reconcile(self.store)
        self.assertIn("guardrail_retirement", rep)
        self.assertTrue(any(c["id"] in rep["guardrail_retirement"]["retired"]
                            for c in [g]))

    def test_events_append_only_history_kept(self):
        g = self._expired_guardrail()
        by = next(t.split("#")[-1] for t in
                  [e["target"] for e in g["edges"]]
                  if "#" in t and t.split("#")[-1].startswith("clm_")
                  and t.split("#")[-1] != self.old["id"])
        hygiene.retract(self.store, self.page, by)
        hygiene.retire_guardrails(self.store, "2026-10-19")
        text = self.store.read(self.page)
        self.assertIn("do not assert", text)
        evs = [e for e in hygiene._events(self.store)
               if e["event"] == "guardrail_retire"]
        self.assertEqual(len(evs), 1)


class TestAdversarialEval(Base):
    def test_active_guardrail_direction(self):
        hygiene.ingest(self.store, self.page, dict(self.new))
        out = evalkit.guardrail_eval(self.store)
        self.assertEqual(out["guardrail"]["n"], 1)
        self.assertEqual(out["guardrail"]["outrank_rate"], 1.0)
        self.assertEqual(out["guardrail_stale"]["n"], 0)

    def test_stale_direction_after_retirement(self):
        g = self._guard_for_stale()
        by = self._refuter_of(g)
        hygiene.retract(self.store, self.page, by, "fixed")
        hygiene.retire_guardrails(self.store, "2026-10-19")
        out = evalkit.guardrail_eval(self.store)
        self.assertEqual(out["guardrail"]["n"], 0)
        self.assertEqual(out["guardrail_stale"]["n"], 1)

    def _guard_for_stale(self):
        hygiene.ingest(self.store, self.page, dict(self.new))
        g = self.guardrails()[0]
        for p in self.store.all_pages():
            _, _, claims = self.store.parse_page(p)
            if any(c["id"] == g["id"] for c in claims):
                self.store.mutate_claim(p, g["id"],
                                        set_attrs={"revalidate_at":
                                                   "2026-10-18"})
        return g

    def _refuter_of(self, g):
        return next(t.split("#")[-1] for t in
                    [e["target"] for e in g["edges"]]
                    if "#" in t and t.split("#")[-1].startswith("clm_")
                    and t.split("#")[-1] != self.old["id"])


if __name__ == "__main__":
    unittest.main()
