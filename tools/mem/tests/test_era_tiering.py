"""G-G2: era-aware quote_ok tiering — the evidence path consults the
emit event's recorded quote_ok instead of guessing from coverage."""

import json
import shutil
import tempfile
import unittest

from mem import hygiene
from mem.store import Store

BODY = ("Acme quarterly burn: 42_000 USD recorded in ledger.csv "
        "for the mini migration budget review.\n")
PARA_BODY = ("checkpointing the capture pipeline prevented journal "
             "corruption during quota exhaustion on mini, and the "
             "mount retry loop stopped hammering the shared volume.\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-era-")
        self.store = Store(self.root)
        self.rel = self.store.write_raw("mem://fin/q3", BODY,
                                        "2026-10-15")[0]
        self.prel = self.store.write_raw("mem://ops/p1", PARA_BODY,
                                         "2026-10-15")[0]
        self.store.ensure_page("wiki/entities/acme.md")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def claim(self, text, rel=None, cid="clm_era0000001"):
        return {"text": text, "pred": "other", "status": "unverified",
                "confidence": 0.7, "date": "2026-10-15", "id": cid,
                "edges": [{"type": "derived_from",
                           "target": rel or self.rel}]}

    def emit(self, cid, quote_ok):
        self.store.append_event({"event": "emit", "claim": cid,
                                 "quote_ok": quote_ok})


class TestQuoteEraLookup(Base):
    def test_quote_ok_true_is_quote_era(self):
        c = self.claim("Acme burn: 42_000 USD recorded in ledger.csv")
        self.emit(c["id"], True)
        self.assertEqual(hygiene.quote_era(self.store, c), "quote")

    def test_no_event_or_none_is_pregate(self):
        c = self.claim("Acme burn: 42_000 USD recorded in ledger.csv")
        self.assertEqual(hygiene.quote_era(self.store, c), "pre-gate")
        self.emit(c["id"], None)
        self.assertEqual(hygiene.quote_era(self.store, c), "pre-gate")

    def test_quote_ok_false_is_pregate(self):
        c = self.claim("Acme burn: 42_000 USD recorded in ledger.csv")
        self.emit(c["id"], False)
        self.assertEqual(hygiene.quote_era(self.store, c), "pre-gate")


class TestEraPolicy(Base):
    def test_quote_era_verbatim_ok(self):
        c = self.claim("Acme burn: 42_000 USD recorded in ledger.csv")
        self.emit(c["id"], True)
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "ok")
        self.assertEqual(detail, self.rel)

    def test_quote_era_paraphrase_passes_attributed(self):
        c = self.claim("Acme burn: quarterly ledger figure recorded "
                       "for the budget review", rel=self.rel)
        self.emit(c["id"], True)
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "ok")
        self.assertIn("quote-era", detail)

    def test_quote_era_invented_fails_verbatim_required(self):
        c = self.claim("Acme burn: quarterly metamorphosis "
                       "vaporization ledger")
        self.emit(c["id"], True)
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "unlocatable")
        self.assertIn("verbatim required", detail)

    def test_pregate_paraphrase_ok_explicit_attribution(self):
        c = self.claim("capture rule: checkpointing stopped journal "
                       "corruption mitigation", rel=self.prel)
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "ok")
        self.assertIn("pre-gate capture: verbatim not required", detail)

    def test_pregate_low_coverage_fails_attributed(self):
        c = self.claim("capture rule: metamorphosis vaporization "
                       "quarantined corruption", rel=self.prel)
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "unlocatable")
        self.assertIn("pre-gate capture", detail)

    def test_verdicts_identical_across_eras_for_same_evidence(self):
        """Additive-only proof: same claim, same evidence, era only
        changes attribution of the detail string, never the verdict."""
        text = ("capture rule: checkpointing stopped journal corruption "
                "mitigation")
        c1 = self.claim(text, rel=self.prel, cid="clm_pregate0001")
        c2 = self.claim(text, rel=self.prel, cid="clm_quoteer00001")
        self.emit(c2["id"], True)
        s1, d1 = hygiene.evidence_status(self.store, c1)
        s2, d2 = hygiene.evidence_status(self.store, c2)
        self.assertEqual(s1, s2)
        self.assertIn("pre-gate", d1)
        self.assertIn("quote-era", d2)


class TestReconcileDistinguishesEras(Base):
    def test_report_separates_tiers(self):
        ok = self.claim("Acme burn: 42_000 USD recorded in ledger.csv",
                        cid="clm_ok000000001")
        self.emit(ok["id"], True)
        self.store.append_claim("wiki/entities/acme.md", ok)
        bad = self.claim("Acme burn: quarterly metamorphosis "
                         "vaporization ledger", cid="clm_bad0000001")
        self.emit(bad["id"], True)
        self.store.append_claim("wiki/entities/acme.md", bad)
        rep = hygiene.reconcile(self.store)
        self.assertEqual(rep["counts"]["ok_quote_era"], 1)
        self.assertEqual(rep["counts"]["unlocatable_quote_era"], 1)
        self.assertTrue(all("quote_era" in p for p in rep["problems"]))
        raw = json.loads(self.store.read("metadata/audit_report.json"))
        self.assertIn("ok_pregate_era", raw["counts"])


if __name__ == "__main__":
    unittest.main()
