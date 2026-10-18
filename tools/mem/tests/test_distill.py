import datetime
import json
import unittest

from mem import distill
from mem.store import Store
import tempfile
import shutil

SESSION = """## Transcript excerpt

turn 14 — tool-call failure (run_command):
zsh aborted with "== not found" after `echo ===` in deploy-memory.sh.
Note: zsh glob-expands leading =word; a bare === separator fails.
Fix adopted: quote separators or split into separate commands so the
run_command harness on macOS keeps working for every later migration
step of the mini rollout plan. Verified twice on the studio host with
a dry run of the same bootstrap script, and the audit trail shows the
retry loop stopped hammering the share after the patch landed in the
deploy sequence. The same class of quoting failure had previously hit
the backup-memory.sh wrapper on the mini, so the fix was applied to
both scripts before the fleet rollout continued past stage two, and
the changelog entry names both files so future greps find this note.

turn 27 — decision: keep mem scrape as an alias of mem ingest because
mini LaunchDaemon and MCP clients call scrape; the tools/ocl/ocl emit
path must not break mid-flight for any fleet machine. The rationale
lives in the changelog and the release notes for the hub bundle, so
an operator reading history later can see why the alias survives even
though ingest is the canonical verb going forward for every new host
that joins the tailnet memory fleet during the rollout window.
"""


class TestSegment(unittest.TestCase):
    def test_turn_boundaries(self):
        ex = distill.segment_exchanges(SESSION)
        self.assertEqual(len(ex), 2)
        self.assertTrue(ex[0]["text"].startswith("turn 14"))
        self.assertEqual(ex[0]["end_line"] + 1, ex[1]["start_line"])

    def test_trivial_skipped(self):
        self.assertEqual(distill.segment_exchanges("turn 1\nshort"), [])

    def test_no_markers_no_loss(self):
        text = "one two three four five six seven\nx" * 3
        ex = distill.segment_exchanges(text)
        joined = " ".join(e["text"] for e in ex)
        for word in ("one", "five"):
            self.assertIn(word, joined)


class TestDistill(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-d-")
        self.store = Store(self.root)
        self.rel = self.store.write_raw("mem://session/x", SESSION,
                                        "2026-10-18")[0]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_compound_object_fields(self):
        ex = distill.segment_exchanges(self.store.read(self.rel).split("---\n", 1)[-1])
        obj = distill.distill_exchange(ex[0], self.rel, "2026-10-18")
        for k in ("id", "exchange_core", "specific_context",
                  "room_assignments", "files_touched", "source"):
            self.assertIn(k, obj)
        self.assertTrue(obj["id"].startswith("dst_"))
        self.assertIn("deploy-memory.sh", obj["files_touched"])
        self.assertEqual(obj["source"]["file"], self.rel)
        self.assertLessEqual(len(obj["room_assignments"]), 3)
        self.assertIn(obj["specific_context"],
                      "\n".join(self.store.read(self.rel).split("\n")
                                [ex[0]["start_line"] - 1:ex[0]["end_line"]]))

    def test_verify_gate_rejects_invention(self):
        ex = distill.segment_exchanges("turn 1\n" + "zsh separator failure "
                                       "in deploy-memory.sh " * 10)
        obj = distill.distill_exchange(ex[0], "raw/x.md")
        self.assertEqual(distill.verify_distill(obj, "zsh separator failure "
                                                "in deploy-memory.sh " * 10),
                         [])
        obj["files_touched"].append("invented.rs")
        self.assertTrue(distill.verify_distill(obj, "zsh"))

    def test_distill_raw_end_to_end(self):
        before = self.store.read(self.rel)
        stats = distill.distill_raw(self.store, self.rel, "2026-10-18")
        self.assertGreaterEqual(stats["objects"], 1)
        self.assertEqual(self.store.read(self.rel), before)  # raw untouched
        objs = distill.load_distilled(self.store)
        self.assertEqual(len(objs), stats["objects"])
        for o in objs:
            self.assertGreater(o["tokens_source"], 0)
            self.assertGreater(o["tokens_distilled"], 0)
        # idempotent: second run adds nothing
        again = distill.distill_raw(self.store, self.rel, "2026-10-18")
        self.assertEqual(again["objects"], 0)

    def test_token_reduction_recorded(self):
        long_turn = "turn 9 — incident: " + (
            "the ingest pipeline failed while writing events.jsonl because "
            "the disk quota on mini tailnet share exceeded during a large "
            "session journal capture of knowledge/inbox entries and the "
            "retry loop rewrote partial JSON lines repeatedly until the "
            "capture of raw/2026-10-18_session.md aborted with SIGKILL. "
            * 6)
        body = long_turn + "\nsplit into separate commands fixed it; see " \
                          "raw/2026-10-18_session.md events.jsonl recovery.\n"
        rel = self.store.write_raw("mem://s/2", body, "2026-10-18")[0]
        stats = distill.distill_raw(self.store, rel, "2026-10-18")
        self.assertGreaterEqual(stats["compression"], 1.0)
        o = distill.load_distilled(self.store)[-1]
        self.assertLess(o["tokens_distilled"], o["tokens_source"])

    def test_short_exchanges_skipped(self):
        body = ("turn 1 — quick note: fixed a typo in the README and "
                "closed a stale issue; nothing else happened, this "
                "capture is deliberately too short to distill.\n")
        rel = self.store.write_raw("mem://s/3", body, "2026-10-18")[0]
        stats = distill.distill_raw(self.store, rel, "2026-10-18")
        self.assertEqual(stats["objects"], 0)
        self.assertEqual(stats["skipped_short"], 1)

    def test_core_cut_at_word_boundary(self):
        body = ("turn 5 — the extraordinarily fragile bootstrap of "
                "deploy-memory.sh kept failing because the wrapper "
                "was re-run without re-quoting the separator arguments "
                "on the mini host under the tailnet share mount, and "
                "the retry loop hid the real zsh quoting error from "
                "every operator who read the captured log afterwards.")
        ex = distill.segment_exchanges(body)[0]
        obj = distill.distill_exchange(ex, "raw/x.md")
        self.assertLessEqual(len(obj["exchange_core"]),
                             distill.CORE_MAX + 60)
        self.assertEqual(distill.verify_distill(obj, body), [])
        for tok in distill._TOKEN_RE.findall(obj["exchange_core"]):
            if len(tok) > 5:
                self.assertIn(tok.casefold(), body.casefold())


if __name__ == "__main__":
    unittest.main()
