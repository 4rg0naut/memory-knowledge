import json
import unittest

from mem import codec, hygiene
from mem.store import Store
import shutil
import tempfile

BODY = ("Acme quarterly burn: 42_000 USD recorded in ledger.csv "
        "for the mini migration budget review.\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-s5-")
        self.store = Store(self.root)
        self.rel = self.store.write_raw("mem://fin/q3", BODY,
                                        "2026-10-15")[0]
        self.store.ensure_page("wiki/entities/acme.md")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def claim(self, text="Acme burn: 42_000 USD recorded in ledger.csv",
              edges=None):
        return {"text": text, "pred": "other", "status": "unverified",
                "confidence": 0.7, "date": "2026-10-15",
                "edges": edges if edges is not None else
                [{"type": "derived_from", "target": self.rel}]}


class TestEvidenceStatus(Base):
    def test_ok(self):
        status, detail = hygiene.evidence_status(self.store, self.claim())
        self.assertEqual(status, "ok")
        self.assertEqual(detail, self.rel)

    def test_stale_on_content_drift(self):
        front, _body = codec.split_frontmatter(self.store.read(self.rel))
        self.store.write(self.rel,
                         codec.build_frontmatter(front)
                         + "totally different body text\n")
        status, detail = hygiene.evidence_status(self.store, self.claim())
        self.assertEqual(status, "stale")
        self.assertIn("content_hash", detail)

    def test_unlocatable_passage(self):
        c = self.claim(text="Acme burn: 99_000 EUR in a phantom file")
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "unlocatable")
        self.assertIn("passage", detail)

    def test_unlocatable_missing_source(self):
        c = self.claim(edges=[{"type": "derived_from",
                              "target": "raw/nope.md"}])
        status, _ = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "unlocatable")

    def test_unlocatable_no_source(self):
        status, _ = hygiene.evidence_status(self.store, self.claim(edges=[]))
        self.assertEqual(status, "unlocatable")

    def test_legacy_paraphrase_survives_coverage(self):
        body = ("turn 1 — checkpointing the capture pipeline prevented "
                "journal corruption during quota exhaustion on mini, and "
                "the events.jsonl retry loop stopped hammering the mount.\n")
        rel = self.store.write_raw("mem://fin/q4", body, "2026-10-16")[0]
        c = self.claim(text="capture rule: checkpointing prevented "
                           "journal corruption in the pipeline",
                       edges=[{"type": "derived_from", "target": rel}])
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "ok")
        self.assertIn("coverage", detail)

    def test_invented_tokens_stay_unlocatable(self):
        c = self.claim(text="Acme burn: quarterly metamorphosis "
                           "vaporization ledger",
                       edges=[{"type": "derived_from", "target": self.rel}])
        status, detail = hygiene.evidence_status(self.store, c)
        self.assertEqual(status, "unlocatable")
        self.assertIn("coverage", detail)


class TestKernelCli(Base):
    def _cli(self, argv):
        import contextlib
        import io
        from mem import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["--home", self.store.root] + argv)
        return code, buf.getvalue()

    def test_reconcile_exit_code_sees_all_problems(self):
        page = "wiki/entities/acme.md"
        hygiene.ingest(self.store, page, self.claim())
        bad = self.claim(text="Acme burn: 55_000 EUR nowhere phantom")
        self.store.append_claim(page, bad)
        code, out = self._cli(["reconcile"])
        self.assertEqual(code, 1)
        rep = json.loads(out)
        self.assertTrue(any(p["evidence"] == "unlocatable"
                            for p in rep["problems"]))

    def test_reconcile_exit_zero_when_clean(self):
        page = "wiki/entities/acme.md"
        hygiene.ingest(self.store, page, self.claim())
        self._cli(["index"])
        code, out = self._cli(["reconcile"])
        self.assertEqual(code, 0, out)

    def test_distill_missing_source_hard_error(self):
        code, out = self._cli(["distill", "--source", "raw/typo.md"])
        self.assertEqual(code, 2)
        self.assertIn("no such raw source", out)

    def test_distill_empty_reports_null_compression(self):
        code, out = self._cli(["distill", "--source", self.rel])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["objects"], 0)
        self.assertIsNone(d["compression"])

    def test_eval_rejects_unknown_mode(self):
        code, out = self._cli(["eval", "--modes", "fuse"])
        self.assertEqual(code, 2)
        self.assertIn("unknown mode", out)


class TestModelCheck(Base):
    def promote(self):
        page = "wiki/entities/acme.md"
        r = hygiene.ingest(self.store, page, self.claim())
        return page, r["id"]

    def test_corroborates_never_verifies(self):
        page, cid = self.promote()
        out = hygiene.model_check(self.store, page, cid)
        self.assertEqual(out["method"], "model_check")
        self.assertEqual(out["status"], "corroborated")
        _, _, claims = self.store.parse_page(page)
        c = next(x for x in claims if x["id"] == cid)
        self.assertEqual(c["status"], "corroborated")
        self.assertNotEqual(c["status"], "verified")
        events = [json.loads(l) for l in
                  self.store.read("events.jsonl").splitlines() if l.strip()]
        mc = [e for e in events if e["event"] == "model_check"]
        self.assertEqual(len(mc), 1)
        self.assertEqual(mc[0]["method"], "model_check")
        self.assertNotEqual(mc[0]["to"], "verified")

    def test_refused_when_evidence_not_ok(self):
        page = "wiki/entities/acme.md"
        r = hygiene.ingest(self.store, page, self.claim(
            edges=[{"type": "derived_from", "target": "raw/gone.md"}]))
        with self.assertRaises(ValueError):
            hygiene.model_check(self.store, page, r["id"])

    def test_missing_claim_keyerror(self):
        page = "wiki/entities/acme.md"
        self.store.ensure_page(page)
        with self.assertRaises(KeyError):
            hygiene.model_check(self.store, page, "clm_nope")

    def test_human_only_verify(self):
        page, cid = self.promote()
        with self.assertRaises(PermissionError):
            hygiene.verify(self.store, page, cid, "raw://x",
                           actor="model")


class TestReconcile(Base):
    def test_report_written_counts_problems(self):
        page = "wiki/entities/acme.md"
        hygiene.ingest(self.store, page, self.claim())
        bad = self.claim(text="Acme burn: 77_000 GBP in phantom.csv",
                         edges=[{"type": "derived_from",
                                 "target": self.rel}])
        bad["id"] = "clm_bad0001"
        bad["status"] = "verified"
        self.store.append_claim(page, bad)
        rep = hygiene.reconcile(self.store)
        got = json.loads(self.store.read("metadata/audit_report.json"))
        self.assertEqual(got, rep)
        self.assertGreaterEqual(rep["counts"]["ok"], 1)
        self.assertGreaterEqual(rep["counts"]["unlocatable"], 1)
        self.assertGreaterEqual(rep["counts"].get("self_verified", 0), 1)
        problem = next(p for p in rep["problems"]
                       if p["claim"] == "clm_bad0001")
        self.assertEqual(problem["evidence"], "unlocatable")
        self.assertIn("verified without verify event",
                      problem.get("note", ""))
        self.assertIn(page, rep["unindexed_pages"])

    def test_duplicate_claim_id_flagged(self):
        page = "wiki/entities/acme.md"
        hygiene.ingest(self.store, page, self.claim())
        dup = self.claim()
        dup["id"] = self.store.parse_page(page)[2][0]["id"]
        self.store.append_claim(page, dup)
        rep = hygiene.reconcile(self.store)
        self.assertGreaterEqual(rep["counts"]["duplicate_id"], 1)
        row = next(p for p in rep["problems"]
                   if p["evidence"] == "duplicate_id")
        self.assertEqual(row["page"], page)


class TestRoundTwoGates(Base):
    """Regression gates for review findings #7-#10 (2026-10-18 r2)."""

    def test_self_verified_ok_evidence_fails_exit(self):
        page = "wiki/entities/acme.md"
        c = {"text": "Acme burn: 42_000 USD recorded in ledger.csv",
             "pred": "other", "status": "verified", "confidence": 0.7,
             "date": "2026-10-15",
             "edges": [{"type": "derived_from", "target": self.rel}]}
        self.store.append_claim(page, c)
        rep = hygiene.reconcile(self.store)
        self.assertEqual(rep["counts"].get("self_verified"), 1)
        row = next(p for p in rep["problems"]
                   if p.get("note") == "verified without verify event")
        self.assertEqual(row["evidence"], "ok")
        import contextlib
        import io
        from mem import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli.main(["--home", self.store.root, "index"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["--home", self.store.root, "reconcile"])
        self.assertEqual(code, 1, buf.getvalue())
        rep = json.loads(buf.getvalue())
        self.assertFalse(rep["unindexed_pages"])
        self.assertTrue(any("verified without verify event"
                            in p.get("note", "") for p in rep["problems"]))

    def test_load_distilled_torn_line_reported_not_fatal(self):
        from mem import distill
        self.store.write("distill/exchanges.jsonl",
                         json.dumps({"id": "dst_ok", "x": 1}) + "\n"
                         + '{"id": "dst_torn", "x": ')
        objs = distill.load_distilled(self.store)
        self.assertEqual([o["id"] for o in objs], ["dst_ok"])
        evs = [e for e in hygiene._events(self.store)
               if e["event"] == "exchanges_view_torn_lines"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["dropped"], 1)

    def test_asof_rejects_non_iso_date(self):
        import contextlib
        import io
        from mem import cli
        buf = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(buf), \
                contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--home", self.store.root, "asof", "hello"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("ISO date", err.getvalue())

    def test_graph_query_hints_when_view_missing(self):
        import contextlib
        import io
        from mem import cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cli.main(["--home", self.store.root, "graph", "acme"])
        self.assertEqual(code, 0)
        self.assertIn("--build", json.loads(buf.getvalue()).get("hint", ""))

    def test_reconcile_checked_counts_claims_once(self):
        page = "wiki/entities/acme.md"
        hygiene.ingest(self.store, page, self.claim())
        hygiene.ingest(self.store, page, self.claim())  # duplicate_ignored
        rep = hygiene.reconcile(self.store)
        _, _, claims = self.store.parse_page(page)
        self.assertEqual(rep["checked"], len(claims))


if __name__ == "__main__":
    unittest.main()
