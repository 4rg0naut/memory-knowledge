import datetime
import unittest

from mem import codec, hygiene, temporal
from mem.store import Store
import shutil
import tempfile

REF = "2026-10-18"


class TestResolve(unittest.TestCase):
    def r(self, phrase, ref=REF):
        return temporal.resolve_relative("deployed " + phrase + " on mini",
                                         ref)

    def test_phrases(self):
        self.assertEqual(self.r("today"), "2026-10-18")
        self.assertEqual(self.r("yesterday"), "2026-10-17")
        self.assertEqual(self.r("3 days ago"), "2026-10-15")
        self.assertEqual(self.r("2 weeks ago"), "2026-10-04")
        self.assertEqual(self.r("1 month ago"), "2026-09-18")
        self.assertEqual(self.r("last month"), "2026-09-01")
        self.assertEqual(self.r("last week"), "2026-10-11")
        self.assertEqual(self.r("last quarter"), "2026-07-01")
        self.assertEqual(self.r("last year"), "2025-10-18")

    def test_month_end_clamp(self):
        self.assertEqual(self.r("1 month ago", "2026-03-31"), "2026-02-28")

    def test_no_phrase(self):
        self.assertIsNone(temporal.resolve_relative("fixed the parser",
                                                    REF))

    def test_first_match_wins(self):
        got = temporal.resolve_relative("yesterday, or 3 days ago maybe",
                                        REF)
        self.assertEqual(got, "2026-10-17")


class TestStamp(unittest.TestCase):
    def test_stamp_sets_valid_at(self):
        c = {"text": "mini was migrated 2 weeks ago",
             "date": REF, "status": "unverified"}
        self.assertEqual(temporal.stamp_claim(c), "2026-10-04")
        self.assertEqual(c["valid_at"], "2026-10-04")

    def test_explicit_valid_at_kept(self):
        c = {"text": "done yesterday", "date": REF,
             "valid_at": "2026-01-02", "status": "unverified"}
        self.assertIsNone(temporal.stamp_claim(c))
        self.assertEqual(c["valid_at"], "2026-01-02")

    def test_no_phrase_no_attr(self):
        c = {"text": "plain fact", "date": REF, "status": "unverified"}
        self.assertIsNone(temporal.stamp_claim(c))
        self.assertNotIn("valid_at", c)


class TestAsOf(unittest.TestCase):
    def claim(self, date, invalid_at=None):
        c = {"date": date, "status": "unverified"}
        if invalid_at:
            c["invalid_at"] = invalid_at
        return c

    def test_window(self):
        c = self.claim("2026-10-01", "2026-10-10")
        self.assertFalse(temporal.as_of(c, "2026-09-20"))
        self.assertTrue(temporal.as_of(c, "2026-10-05"))
        self.assertFalse(temporal.as_of(c, "2026-10-10"))
        self.assertFalse(temporal.as_of(c, "2026-10-11"))

    def test_open_window(self):
        self.assertTrue(temporal.as_of(self.claim("2026-10-01"),
                                       "2099-01-01"))


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-t-")
        self.store = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def mkclaim(self, text, pred="hq", date="2026-01-01"):
        self.store.ensure_page("wiki/entities/acme.md")
        return {"text": text, "pred": pred, "status": "unverified",
                "confidence": 0.7, "date": date,
                "edges": [{"type": "derived_from",
                           "target": "raw/2026-09-29_acme.md"}]}


class TestIngestStamping(Base):
    def test_relative_resolved_at_emit(self):
        c = self.mkclaim("Acme Corp hq: moved to Lyon last month",
                         date="2026-05-05")
        hygiene.ingest(self.store, "wiki/entities/acme.md", c)
        _, _, claims = self.store.parse_page("wiki/entities/acme.md")
        self.assertEqual(claims[0]["valid_at"], "2026-04-01")

    def test_supersede_sets_invalid_at(self):
        old = hygiene.ingest(self.store, "wiki/entities/acme.md",
                             self.mkclaim("Acme Corp hq: Lyon"))["id"]
        hygiene.ingest(self.store, "wiki/entities/acme.md",
                       self.mkclaim("Acme Corp hq: Paris",
                                    date="2026-05-05"))
        _, _, claims = self.store.parse_page("wiki/entities/acme.md")
        oldc = next(c for c in claims if c["id"] == old)
        self.assertEqual(oldc["status"], "contradicted")
        self.assertEqual(oldc["invalid_at"], "2026-05-05")

    def test_active_claims_asof(self):
        old = hygiene.ingest(self.store, "wiki/entities/acme.md",
                             self.mkclaim("Acme Corp hq: Lyon"))["id"]
        r2 = hygiene.ingest(self.store, "wiki/entities/acme.md",
                            self.mkclaim("Acme Corp hq: Paris",
                                         date="2026-05-05"))
        new = r2["id"]
        guard = r2["guardrails"][0]
        march = {c["id"] for _, c in temporal.active_claims(
            self.store, "2026-03-01")}
        june = {c["id"] for _, c in temporal.active_claims(
            self.store, "2026-06-01")}
        self.assertEqual(march, {old})
        self.assertEqual(june, {new, guard})

    def test_timeline(self):
        cid = hygiene.ingest(self.store, "wiki/entities/acme.md",
                             self.mkclaim("Acme Corp hq: Lyon"))["id"]
        t = temporal.timeline(self.store, cid)
        self.assertEqual(t["claim"], cid)
        self.assertEqual(t["validity"]["page"], "wiki/entities/acme.md")
        self.assertIn("emit", [e["event"] for e in t["events"]])


class TestCodecV2(unittest.TestCase):
    def line(self, valid_at="2026-01-01", invalid_at=None):
        attrs = ("id: clm_x, pred: hq, status: unverified, "
                 "confidence: 0.70, date: 2026-01-01")
        if valid_at:
            attrs += ", valid_at: %s" % valid_at
        if invalid_at:
            attrs += ", invalid_at: %s" % invalid_at
        return "- Acme hq: Lyon {%s}" % attrs

    def test_roundtrip(self):
        c = codec.parse_claim(self.line(invalid_at="2026-05-05"), [])
        self.assertEqual(c["valid_at"], "2026-01-01")
        self.assertEqual(c["invalid_at"], "2026-05-05")

    def test_bad_iso_rejected(self):
        with self.assertRaises(ValueError):
            codec.parse_claim(self.line(valid_at="last month"), [])

    def test_v1_line_still_parses(self):
        c = codec.parse_claim(self.line(valid_at=None), [])
        self.assertNotIn("valid_at", c)

    def test_set_claim_attr_replace_and_append(self):
        line = self.line(valid_at=None)
        got = codec.set_claim_attr(line, "invalid_at", "2026-05-05")
        self.assertIn("invalid_at: 2026-05-05", got)
        got2 = codec.set_claim_attr(got, "invalid_at", "2026-06-06")
        self.assertIn("invalid_at: 2026-06-06", got2)
        self.assertNotIn("2026-05-05", got2)
        c = codec.parse_claim(got2, [])
        self.assertEqual(c["invalid_at"], "2026-06-06")

    def test_stamp_insert_v1_to_v2(self):
        v1 = ("---\ntitle: acme\nformat: mem-wiki@1\ntype: entity\n"
              "tags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n"
              "---\n# acme\n")
        v2 = codec.stamp_insert(v1)
        self.assertIn("format: %s" % codec.FMT, v2)
        self.assertNotIn("mem-wiki@1", v2)
        self.assertIn("# acme\n", v2)
        self.assertEqual(codec.stamp_insert(v2), v2)  # idempotent


if __name__ == "__main__":
    unittest.main()
