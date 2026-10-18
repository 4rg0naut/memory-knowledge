"""G-G4: multi-writer + crash-consistency boundary of the file-first
store. Audit findings are encoded as tests: every wiki/index mutation
goes through store.write (tmp + os.replace atomic rename); the
events.jsonl append path can only tear its trailing line, and every
reader of an append log REPORTS torn lines instead of choking or
silently accepting them.

Supported boundary (docs/concurrency.md): single machine, multiple
writers coordinated via fcntl flock + atomic rename. Multi-machine
shared-filesystem writers are NOT supported (flock is not reliable
across NFS-family mounts).
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from mem import codec, hygiene
from mem.store import Store

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-cc-")
        self.store = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_py(self, code, env=None, ok=True):
        e = dict(os.environ)
        e["PYTHONPATH"] = HERE
        if env:
            e.update(env)
        p = subprocess.run([sys.executable, "-c", code], cwd=HERE,
                           env=e, capture_output=True, text=True)
        if ok:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p


class TestWritePathAudit(unittest.TestCase):
    def test_no_open_w_bypasses_atomic_rename(self):
        """Only store.write may open a text file for writing (and it
        must be the tmp path of the rename); everything else goes
        through store.write."""
        offenders = []
        for path in glob.glob(os.path.join(HERE, "mem", "*.py")):
            if os.path.basename(path) == "store.py":
                continue
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if 'open(' in line and ('"w"' in line or "'w'" in line
                                            or '"a"' in line
                                            or "'a'" in line):
                        offenders.append("%s:%d %s" % (
                            os.path.basename(path), n, line.strip()))
        self.assertEqual(offenders, [],
                         "direct write-mode opens bypass atomic rename")

    def test_store_write_is_atomic_rename(self):
        import inspect
        src = inspect.getsource(Store.write)
        self.assertIn("os.replace", src)
        self.assertIn("tmp", src)


class TestTornAppends(Base):
    def test_torn_event_line_is_reported_not_fatal(self):
        self.store.append_event({"event": "emit", "claim": "clm_a1",
                                 "page": "p"})
        self.store.append_event({"event": "verify", "claim": "clm_a1",
                                 "page": "p"})
        text = self.store.read("events.jsonl")
        # simulate crash mid-append: truncate the final line mid-JSON
        self.store.write("events.jsonl", text[:-6])
        hygiene._EVENT_CACHE_TTL.clear()
        evs = hygiene._events(self.store)          # must not raise
        self.assertEqual(len(evs), 1)              # valid line kept
        rep = hygiene.reconcile(self.store)
        self.assertEqual(rep["torn_event_lines"], 1)
        self.assertTrue(any(p["evidence"] == "torn_line"
                            for p in rep["problems"]))

    def test_torn_that_parses_is_a_complete_record(self):
        """Truncation of only trailing whitespace after a complete JSON
        object yields a complete record — honest boundary, documented,
        not a silent half-object."""
        self.store.append_event({"event": "emit", "claim": "clm_b1"})
        text = self.store.read("events.jsonl").rstrip("\n") + "   \n"
        self.store.write("events.jsonl", text[:-1])
        recs, torn = codec.read_jsonl(self.store.read("events.jsonl"))
        self.assertEqual(len(recs), 1)
        self.assertEqual(torn, [])

    def test_graph_view_torn_line_dropped_and_recorded(self):
        from mem import graph
        self.store.write(graph.GRAPH_REL,
                         json.dumps({"src": "a", "dst": "b",
                                     "type": "co_mentioned",
                                     "valid_at": None, "invalid_at": None,
                                     "via": "x"}) + "\n"
                         + '{"src": "c", "dst": "d", "type": "co')
        edges = graph.load_graph(self.store)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["src"], "a")
        evs = hygiene._events(self.store)
        self.assertTrue(any(e["event"] == "graph_view_torn_lines"
                            for e in evs))


class TestCrashInjection(Base):
    def test_kill_before_rename_final_file_intact(self):
        self.store.write("wiki/entities/x.md", "OLD CONTENT\n")
        code = ("from mem.store import Store\n"
                "s = Store(%r)\n"
                "s.write('wiki/entities/x.md', 'NEW CONTENT'*500)\n" % self.root)
        p = self.run_py(code, env={"MEM_CRASH_POINT": "pre-rename"},
                        ok=False)
        self.assertNotEqual(p.returncode, 0)          # was SIGKILLed
        self.assertEqual(self.store.read("wiki/entities/x.md"),
                         "OLD CONTENT\n")             # never torn
        tmps = [f for f in os.listdir(self.store.path("wiki/entities"))
                if f.endswith(".tmp")]
        self.assertEqual(len(tmps), 1)                # orphan tmp only

    def test_kill_mid_tmp_final_file_intact(self):
        self.store.write("wiki/entities/x.md", "OLD CONTENT\n")
        code = ("from mem.store import Store\n"
                "s = Store(%r)\n"
                "s.write('wiki/entities/x.md', 'NEW CONTENT'*500)\n" % self.root)
        self.run_py(code, env={"MEM_CRASH_POINT": "mid-tmp"}, ok=False)
        self.assertEqual(self.store.read("wiki/entities/x.md"),
                         "OLD CONTENT\n")

    def test_digest_detects_manual_tear_of_final_file(self):
        """No rename protection covers external corruption (bad sync
        tool, hand edit): the pinned content_hash is the second line of
        defense and reconcile must see it."""
        rel = self.store.write_raw("mem://x", "alpha bravo charlie "
                                  "delta echo payload line\n", "2026-10-01")[0]
        claim = {"text": "alpha bravo charlie", "pred": "other",
                 "status": "unverified", "confidence": 0.7,
                 "date": "2026-10-01",
                 "edges": [{"type": "derived_from", "target": rel}]}
        self.store.ensure_page("wiki/entities/x.md")
        self.store.append_claim("wiki/entities/x.md", claim)
        body = self.store.read(rel)
        self.store.write(rel, body[: len(body) // 2])   # torn final file
        status, detail = hygiene.evidence_status(self.store, claim)
        self.assertEqual(status, "stale")
        self.assertIn("content_hash", detail)

    def test_git_backstop_recovery(self):
        rel = self.store.write_raw("mem://x", "alpha bravo charlie "
                                  "delta echo payload line\n", "2026-10-01")[0]
        self.store.ensure_page("wiki/entities/x.md")
        self.store.append_claim("wiki/entities/x.md", {
            "text": "alpha bravo charlie", "pred": "other",
            "status": "unverified", "confidence": 0.7, "date": "2026-10-01",
            "edges": [{"type": "derived_from", "target": rel}]})
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True,
                       capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "baseline"], cwd=self.root,
                       check=True, capture_output=True)
        body = self.store.read(rel)
        self.store.write(rel, body[: len(body) // 2])
        rep = hygiene.reconcile(self.store)
        self.assertTrue(rep["problems"])
        subprocess.run(["git", "checkout", "--", rel], cwd=self.root,
                       check=True, capture_output=True)
        claim = {"text": "alpha bravo charlie", "pred": "other",
                 "status": "unverified", "confidence": 0.7,
                 "date": "2026-10-01",
                 "edges": [{"type": "derived_from", "target": rel}]}
        status, _ = hygiene.evidence_status(self.store, claim)
        self.assertEqual(status, "ok")


class TestConcurrentWriters(Base):
    WORKER = (
        "from mem.store import Store\n"
        "from mem import hygiene, schema\n"
        "import sys\n"
        "root, i = sys.argv[1], int(sys.argv[2])\n"
        "s = Store(root)\n"
        "rel, _ = s.write_raw('mem://cc/%d' % i, 'concurrent capture "
        "alpha bravo charlie delta echo payload for writer %d\\n' % i, "
        "'2026-10-01')\n"
        "page = s.page_for_subject('acme')\n"
        "for j in range(3):\n"
        "    hygiene.ingest(s, page, {\n"
        "        'text': 'acme rule p%d: distinct claim value %d with "
        "alpha bravo charlie' % (i, j),\n"
        "        'pred': schema.PREDICATES[i * 3 + j],\n"
        "        'status': 'unverified', 'confidence': 0.6,\n"
        "        'date': '2026-10-01',\n"
        "        'edges': [{'type': 'derived_from', 'target': rel}]})\n"
    )

    def test_parallel_procs_ingest_without_loss_or_tears(self):
        # distinct preds per (writer, claim): every ingest is a fresh
        # append — the strongest test that no writer's line is lost
        procs = []
        for i in range(4):
            e = dict(os.environ)
            e["PYTHONPATH"] = HERE
            p = subprocess.Popen(
                [sys.executable, "-c", self.WORKER, self.root, str(i)],
                cwd=HERE, env=e,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            procs.append(p)
        codes = [(p.wait(), p.stderr.read()) for p in procs]
        self.assertEqual([c for c, _ in codes], [0] * 4,
                         "\n".join(s for c, s in codes if c))
        _, _, claims = self.store.parse_page("wiki/entities/acme.md")
        self.assertEqual(len(claims), 12)
        recs, torn = codec.read_jsonl(self.store.read("events.jsonl"))
        self.assertEqual(torn, [])
        self.assertEqual(sum(1 for r in recs if r["event"] == "emit"), 12)


class TestStaleTmpSweep(unittest.TestCase):
    """Review #11: process-unique tmp names (F-10) are never reused by
    later writers, so crash orphans need an explicit sweep — stale ones
    go, young ones (possibly a live writer) stay."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.store = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_stale_orphan_swept_fresh_kept(self):
        import time as _t
        self.store.write("wiki/entities/a.md", "one\n")
        stale = "wiki/entities/a.md.999-1-deadbee.tmp"
        self.store.write(stale, "half-written")
        old = _t.time() - 7200
        os.utime(self.store.path(stale), (old, old))
        fresh = "wiki/entities/a.md.998-1-cafebab.tmp"
        self.store.write(fresh, "in flight")
        other = "wiki/entities/b.md.997-1-abdecf.tmp"
        self.store.write(other, "b's own orphan")
        self.store.write("wiki/entities/a.md", "two\n")
        self.assertFalse(os.path.exists(self.store.path(stale)),
                         "stale crash orphan should be swept")
        self.assertTrue(os.path.exists(self.store.path(fresh)),
                        "young tmp may belong to a live writer")
        self.assertTrue(os.path.exists(self.store.path(other)),
                        "sweep must not touch other targets")
        self.assertEqual(self.store.read("wiki/entities/a.md"), "two\n")


if __name__ == "__main__":
    unittest.main()
