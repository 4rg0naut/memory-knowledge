import datetime
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request

from mem import cli, codec, hygiene, index, migrate, providers, rules, schema
from mem import sources
from mem.extract import extract
from mem.server import Handler, serve
from mem.store import Store
from http.server import ThreadingHTTPServer


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="mem-test-")
        self.store = Store(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def mkclaim(self, text="Acme Corp hq: Lyon", pred="hq",
                status="unverified", conf=0.7, day=None,
                source="raw/2026-09-29_acme.md"):
        return {
            "text": text, "pred": pred, "status": status,
            "confidence": conf,
            "date": day or datetime.date.today().isoformat(),
            "edges": [{"type": "derived_from", "target": source}],
        }


class TestSchema(Base):
    def test_roundtrip(self):
        c = self.mkclaim()
        block = schema.format_claim(c)
        lines = block.splitlines()
        parsed = schema.parse_claim_block(lines[0], lines[1:])
        self.assertEqual(parsed["text"], c["text"])
        self.assertEqual(parsed["pred"], "hq")
        self.assertEqual(parsed["status"], "unverified")
        self.assertAlmostEqual(parsed["confidence"], 0.7)
        self.assertEqual(parsed["edges"][0]["target"],
                         "raw/2026-09-29_acme.md")

    def test_unknown_edge_rejected(self):
        c = self.mkclaim()
        c["edges"].append({"type": "depends_on", "target": "x"})
        with self.assertRaises(ValueError):
            schema.parse_claim_block(*self._split(schema.format_claim(c)))

    def _split(self, block):
        lines = block.splitlines()
        return lines[0], lines[1:]

    def test_effective_decay(self):
        c = self.mkclaim(conf=0.9, status="verified", day="2026-06-21")
        today = datetime.date(2026, 9, 29)
        eff = schema.effective_confidence(c, today)
        self.assertAlmostEqual(eff, 0.9 * 1.0 * (1 / (1 + 100 * 0.01)),
                               places=6)

    def test_mini_yaml_roundtrip(self):
        entries = [{"file": "wiki/entities/acme-corp.md",
                    "summary": 'French "logistics", co',
                    "tags": ["company", "france"],
                    "updated": "2026-09-29", "claim_count": 12,
                    "unverified_count": 5}]
        loaded = schema.load_index(schema.dump_index(entries))
        self.assertEqual(loaded, entries)


class TestStore(Base):
    def test_raw_dedup_by_hash_across_dates(self):
        rel1, dup = self.store.write_raw("http://acme.example/a", "body x",
                                         "2026-09-28")
        self.assertFalse(dup)
        rel2, dup = self.store.write_raw("http://acme.example/a", "body x",
                                         "2026-09-29")
        self.assertTrue(dup)
        self.assertEqual(rel2, rel1)

    def test_page_creation_and_claim_roundtrip(self):
        page = self.store.page_for_subject("Acme Corp")
        c = self.mkclaim()
        c["id"] = schema.new_id(page + c["text"])
        self.store.append_claim(page, c)
        front, _, claims = self.store.parse_page(page)
        self.assertEqual(front["title"], "Acme Corp")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["id"], c["id"])

    def test_path_escape(self):
        with self.assertRaises(ValueError):
            self.store.read("../outside.md")

    def test_events_append(self):
        self.store.append_event({"event": "emit", "claim": "clm_x"})
        self.store.append_event({"event": "verify", "claim": "clm_x"})
        lines = self.store.read("events.jsonl").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["event"], "verify")


class TestIngest(Base):
    def test_anonymous_rejected(self):
        c = self.mkclaim()
        c["edges"] = []
        with self.assertRaises(ValueError) as ctx:
            hygiene.ingest(self.store, self.store.page_for_subject("Acme"), c)
        self.assertIn("anonymous", str(ctx.exception))

    def test_self_verified_rejected(self):
        c = self.mkclaim(status="verified")
        with self.assertRaises(ValueError) as ctx:
            hygiene.ingest(self.store, self.store.page_for_subject("Acme"), c)
        self.assertIn("verified", str(ctx.exception))

    def test_contradiction_flags_old(self):
        page = self.store.page_for_subject("Acme Corp")
        old = self.mkclaim(text="Acme Corp hq: Lyon", day="2026-09-01")
        r1 = hygiene.ingest(self.store, page, old)
        new = self.mkclaim(text="Acme Corp hq: Paris", day="2026-09-29",
                           source="raw/2026-09-29_b.md")
        r2 = hygiene.ingest(self.store, page, new)
        self.assertEqual(r2["contradicted"], [r1["id"]])
        _, _, claims = self.store.parse_page(page)
        statuses = {c["id"]: c["status"] for c in claims}
        self.assertEqual(statuses[r1["id"]], "contradicted")
        self.assertEqual(statuses[r2["id"]], "unverified")
        conflicts = hygiene.contradictions(self.store)
        self.assertEqual(len(conflicts), 1)

    def test_corroboration_promotes(self):
        page = self.store.page_for_subject("Acme Corp")
        r1 = hygiene.ingest(self.store, page,
                            self.mkclaim(text="Acme Corp founded: 2010"))
        r2 = hygiene.ingest(
            self.store, page,
            self.mkclaim(text="Acme Corp founded: 2010",
                         source="raw/2026-09-29_b.md"))
        self.assertEqual(r2["action"], "corroborated_existing")
        _, _, claims = self.store.parse_page(page)
        self.assertEqual(claims[0]["status"], "corroborated")

    def test_exact_duplicate_ignored(self):
        page = self.store.page_for_subject("Acme Corp")
        hygiene.ingest(self.store, page,
                       self.mkclaim(text="Acme Corp founded: 2010"))
        r2 = hygiene.ingest(self.store, page,
                            self.mkclaim(text="Acme Corp founded: 2010"))
        self.assertEqual(r2["action"], "duplicate_ignored")
        _, _, claims = self.store.parse_page(page)
        self.assertEqual(len(claims), 1)

    def test_inference_cap(self):
        page = self.store.page_for_subject("Acme Corp")
        c = self.mkclaim(conf=0.95)
        c["edges"] = [{"type": "derived_from",
                       "target": "agent-inference"}]
        with self.assertRaises(ValueError):
            hygiene.ingest(self.store, page, c)


class TestVerifyRetract(Base):
    def test_verify_human_only(self):
        page = self.store.page_for_subject("Acme Corp")
        r = hygiene.ingest(self.store, page, self.mkclaim())
        with self.assertRaises(PermissionError):
            hygiene.verify(self.store, page, r["id"], "src", actor="agent")
        hygiene.verify(self.store, page, r["id"], "http://acme.example/a",
                       actor="human")
        _, _, claims = self.store.parse_page(page)
        self.assertEqual(claims[0]["status"], "verified")

    def test_retract_terminal_flagged_not_deleted(self):
        page = self.store.page_for_subject("Acme Corp")
        r = hygiene.ingest(self.store, page, self.mkclaim())
        hygiene.retract(self.store, page, r["id"], "source unreliable")
        _, _, claims = self.store.parse_page(page)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["status"], "retracted")

    def test_lint_flags_self_verified_without_event(self):
        page = self.store.page_for_subject("Acme Corp")
        c = self.mkclaim(status="unverified")
        c["id"] = schema.new_id("x")
        c["status"] = "verified"
        c["confidence"] = 0.1
        self.store.append_claim(page, c)
        checks = [i["check"] for i in hygiene.lint(self.store)]
        self.assertIn("self_verified", checks)

    def test_stale_report(self):
        page = self.store.page_for_subject("Acme Corp")
        hygiene.ingest(self.store, page,
                       self.mkclaim(conf=0.3, day="2026-01-01"))
        rows = hygiene.stale_report(self.store)
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["effective"], 0.3)


class TestExtract(unittest.TestCase):
    RAW = "Acme Corp was founded in 2010. HQ is in Lyon."

    def opener_ok(self, url, model, system, prompt, timeout):
        return json.dumps({"claims": [
            {"subject": "Acme Corp", "predicate": "founded",
             "value": "2010", "confidence": 0.9,
             "source_quote": "Acme Corp was founded in 2010."},
            {"subject": "Acme Corp", "predicate": "hq",
             "value": "Marseille", "confidence": 0.8,
             "source_quote": "HQ is in Marseille, France."}]})

    def test_quote_gate_drops_hallucination(self):
        claims, warnings = extract(self.RAW, opener=self.opener_ok)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["pred"], "founded")
        self.assertTrue(any("quote not in source" in w for w in warnings))

    def test_retry_then_skip(self):
        calls = {"n": 0}

        def broken(url, model, system, prompt, timeout):
            calls["n"] += 1
            return "not json at all"

        claims, warnings = extract(self.RAW, opener=broken)
        self.assertEqual(claims, [])
        self.assertEqual(calls["n"], 2)
        self.assertTrue(any("skipped" in w for w in warnings))

    def test_predicate_out_of_vocab_maps_other(self):
        def op(url, model, system, prompt, timeout):
            return json.dumps({"claims": [
                {"subject": "Acme", "predicate": "headquartered_in_france",
                 "value": "Lyon", "confidence": 0.7,
                 "source_quote": "HQ is in Lyon."}]})
        claims, _ = extract(self.RAW, opener=op)
        self.assertEqual(claims[0]["pred"], "other")

    def test_trailing_prose_after_json_tolerated(self):
        def op(url, model, system, prompt, timeout):
            return ('{"claims": [{"subject": "Acme", "predicate": "hq",'
                    ' "value": "Lyon", "confidence": 0.7,'
                    ' "source_quote": "HQ is in Lyon."}]} Hope that helps!')
        claims, _ = extract(self.RAW, opener=op)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["value"], "Lyon")

    def test_stream_false_in_request(self):
        captured = {}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(
                    {"message": {"role": "assistant",
                                 "content": '{"claims": []}'}}).encode()

        def fake_urlopen(req, timeout):
            captured.update(json.loads(req.data))
            return FakeResp()

        orig = providers.urllib.request.urlopen
        providers.urllib.request.urlopen = fake_urlopen
        try:
            providers.OllamaProvider().call("http://x", "m", "sys",
                                            "p", 5)
        finally:
            providers.urllib.request.urlopen = orig
        self.assertIs(captured["stream"], False)
        self.assertEqual(captured["format"], "json")


class TestIndexRouter(Base):
    def test_route_and_rank(self):
        page = self.store.page_for_subject("Acme Corp")
        for t in ["Acme Corp hq: Lyon", "Acme Corp revenue: 5M EUR"]:
            hygiene.ingest(self.store, page, self.mkclaim(text=t))
        index.rebuild(self.store)
        hits = index.route(self.store, "where is acme hq")
        self.assertEqual(hits[0]["file"], "wiki/entities/acme-corp.md")
        _, _, claims = self.store.parse_page(hits[0]["file"])
        ranked = index.rank_claims(claims, "acme hq lyon")
        self.assertIn("hq", ranked[0][1]["text"])


class ServerMixin:
    def start_server(self):
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            type("Bound", (Handler,), {"store": self.store}))
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def stop_server(self):
        self.httpd.shutdown()

    def post(self, path, obj):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(obj).encode(),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=15) as r:
            return r.status, json.loads(r.read())


class TestServer(Base, ServerMixin):
    def setUp(self):
        super().setUp()
        self.start_server()
        self.raw_rel, _ = self.store.write_raw("http://acme.example/a",
                                              "founded in 2010 in Lyon",
                                              "2026-09-29")

    def tearDown(self):
        self.stop_server()
        super().tearDown()

    def test_healthz(self):
        code, body = self.get("/healthz")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_valid_claim_stored(self):
        code, body = self.post("/claims", {
            "claim": {"text": "Acme Corp founded: 2010", "pred": "founded",
                      "confidence": 0.9, "sources": ["raw/x.md"],
                      "source_quote": "founded in 2010"},
            "raw": self.raw_rel,
            "page": "wiki/entities/acme-corp.md"})
        self.assertEqual(code, 201)
        self.assertTrue(body["id"].startswith("clm_"))

    def test_anonymous_post_rejected_422(self):
        code, body = self.post("/claims", {
            "claim": {"text": "Acme Corp hq: Lyon", "pred": "hq"},
            "raw": self.raw_rel})
        self.assertEqual(code, 422)
        self.assertIn("anonymous", body["error"])

    def test_agent_verified_post_rejected_422(self):
        code, body = self.post("/claims", {
            "claim": {"text": "Acme Corp hq: Lyon", "pred": "hq",
                      "status": "verified", "sources": ["raw/x.md"]},
            "raw": self.raw_rel})
        self.assertEqual(code, 422)

    def test_hallucinated_quote_rejected_422(self):
        code, body = self.post("/claims", {
            "claim": {"text": "Acme Corp hq: Paris", "pred": "hq",
                      "sources": ["raw/x.md"],
                      "source_quote": "HQ is in Paris since 1999"},
            "raw": self.raw_rel})
        self.assertEqual(code, 422)
        self.assertIn("hallucination", body["error"])

    def test_concurrent_writes_serialize(self):
        results = []

        def writer(i):
            code, body = self.post("/claims", {
                "claim": {"text": "Acme Corp owns: plant-%d" % i,
                          "pred": "owns", "sources": ["raw/x.md"],
                          "source_quote": "founded in 2010"},
                "raw": self.raw_rel,
                "page": "wiki/entities/acme-corp.md"})
            results.append(code)

        threads = [threading.Thread(target=writer, args=(i,))
                   for i in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results, [201] * 6)
        _, _, claims = self.store.parse_page("wiki/entities/acme-corp.md")
        owned = [c for c in claims if c["pred"] == "owns"]
        self.assertEqual(len(owned), 6)

    def test_mcp_tools_list_and_query(self):
        rid = 1
        body = {"jsonrpc": "2.0", "id": rid, "method": "tools/list"}
        req = urllib.request.Request(
            self.base + "/mcp", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read())
        names = [t["name"] for t in out["result"]["tools"]]
        self.assertIn("query", names)
        self.assertIn("scrape", names)

    def test_mcp_verify_agent_actor_is_error(self):
        code, stored = self.post("/claims", {
            "claim": {"text": "Acme Corp founded: 2010", "pred": "founded",
                      "sources": ["raw/x.md"],
                      "source_quote": "founded in 2010"},
            "raw": self.raw_rel,
            "page": "wiki/entities/acme-corp.md"})
        body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "verify", "arguments": {
                    "page": "wiki/entities/acme-corp.md",
                    "claim": stored["id"], "actor": "agent"}}}
        req = urllib.request.Request(
            self.base + "/mcp", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            out = json.loads(r.read())
        self.assertTrue(out["result"]["isError"])


class TestReadWriteSplit(Base, ServerMixin):
    def start_server(self):
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            type("BoundRO", (Handler,),
                 {"store": self.store, "allow_writes": False,
                  "write_hint": 8521}))
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]

    def setUp(self):
        super().setUp()
        self.start_server()
        self.raw_rel, _ = self.store.write_raw("http://acme.example/a",
                                               "founded in 2010 in Lyon",
                                               "2026-09-29")
        index.rebuild(self.store)

    def tearDown(self):
        self.stop_server()
        super().tearDown()

    def test_post_rejected_405_on_readonly(self):
        code, body = self.post("/claims", {
            "claim": {"text": "Acme Corp founded: 2010",
                      "pred": "founded", "sources": ["raw/x.md"]},
            "raw": self.raw_rel})
        self.assertEqual(code, 405)
        self.assertIn("mem-writer", body["error"])

    def test_mcp_post_rejected_on_readonly(self):
        code, _ = self.post("/mcp", {"jsonrpc": "2.0", "id": 1,
                                     "method": "tools/list"})
        self.assertEqual(code, 405)

    def test_get_reads_work_on_readonly(self):
        code, body = self.get("/query?text=acme+hq")
        self.assertEqual(code, 200)
        code, body = self.get("/lint")
        self.assertEqual(code, 200)
        code, body = self.get("/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(body["writes_via"], 8521)

    def test_serve_binds_both_ports(self):
        import socket
        import time
        from mem.server import serve
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        pub = s.getsockname()[1]
        s.close()
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        wport = s.getsockname()[1]
        s.close()
        threading.Thread(
            target=serve, args=(self.store,),
            kwargs={"port": pub, "listen": "127.0.0.1",
                    "write_port": wport, "write_listen": "127.0.0.1"},
            daemon=True).start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                urllib.request.urlopen(
                    "http://127.0.0.1:%d/healthz" % wport,
                    timeout=2).read()
                break
            except Exception:
                time.sleep(0.1)
        else:
            self.fail("write listener never came up")
        req = urllib.request.Request(
            "http://127.0.0.1:%d/claims" % wport,
            data=json.dumps({"claim": {"text": "Acme Corp founded: 2010",
                                       "pred": "founded",
                                       "sources": ["raw/x.md"]},
                             "raw": self.raw_rel}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertEqual(r.status, 201)
        req = urllib.request.Request(
            "http://127.0.0.1:%d/claims" % pub,
            data=b"{}", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                self.fail("public POST should 405, got %d" % r.status)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 405)


class TestOrphanPrevention(Base, ServerMixin):
    def setUp(self):
        super().setUp()
        self.start_server()
        self.raw_rel, _ = self.store.write_raw("http://acme.example/a",
                                               "founded in 2010 in Lyon",
                                               "2026-09-29")

    def tearDown(self):
        self.stop_server()
        super().tearDown()

    def test_rejected_claim_leaves_no_orphan_page(self):
        code, _ = self.post("/claims", {
            "claim": {"text": "Probe corp hq: Nowhere", "pred": "hq",
                      "subject": "Probe corp hq: Nowhere",
                      "status": "verified",
                      "sources": ["raw/x.md"],
                      "source_quote": "founded in 2010"},
            "raw": self.raw_rel})
        self.assertEqual(code, 422)
        page = "wiki/entities/probe-corp-hq-nowhere.md"
        self.assertFalse(self.store.exists(page),
                         "orphan page left after rejected claim")

    def test_ensure_page_default_title_is_basename(self):
        rel = "wiki/entities/acme-corp.md"
        self.store.ensure_page(rel)
        front, _, _ = self.store.parse_page(rel)
        self.assertEqual(front["title"], "acme-corp")


PRE_V1_PAGE = """---
title: acme-corp
type: entity
tags: [company]
created: 2026-09-29
updated: 2026-09-29
---

# acme-corp

- Acme Corp hq: Lyon {id: clm_aaa111, pred: hq, status: unverified, confidence: 0.70, date: 2026-09-29}
  derived_from::[[raw/2026-09-29_acme.md]]
"""


class TestCodec(Base):
    def test_new_page_is_stamped(self):
        rel = self.store.page_for_subject("Acme Corp")
        front, _, _ = self.store.parse_page(rel)
        self.assertEqual(front["format"], codec.FMT)

    def test_prev1_page_parses(self):
        self.store.write("wiki/entities/acme-corp.md", PRE_V1_PAGE)
        front, _, claims = self.store.parse_page("wiki/entities/acme-corp.md")
        self.assertNotIn("format", front)
        self.assertEqual(claims[0]["id"], "clm_aaa111")

    def test_stamp_insert_idempotent(self):
        once = codec.stamp_insert(PRE_V1_PAGE)
        self.assertIn("format: mem-wiki@2", once)
        self.assertEqual(once, codec.stamp_insert(once))

    def test_stamp_preserves_claim_body(self):
        stamped = codec.stamp_insert(PRE_V1_PAGE)
        self.assertIn("clm_aaa111", stamped)
        self.assertIn("derived_from::[[raw/2026-09-29_acme.md]]", stamped)

    def test_event_lines_stamped(self):
        self.store.append_event({"event": "emit", "claim": "clm_x"})
        line = self.store.read("events.jsonl").splitlines()[0]
        self.assertEqual(json.loads(line)["fmt"], "mem-wiki@2")

    def test_index_roundtrip_via_codec(self):
        entries = [{"file": "wiki/entities/x.md", "summary": "s",
                    "tags": ["t"], "updated": "2026-10-04",
                    "claim_count": 1, "unverified_count": 0}]
        self.assertEqual(codec.load_index(codec.dump_index(entries)),
                         entries)


class TestMigrate(Base):
    def setUp(self):
        super().setUp()
        self.store.write("wiki/entities/acme-corp.md", PRE_V1_PAGE)
        self.store.write_raw("http://acme.example/x", "body y", "2026-09-29")

    def test_dry_run_changes_nothing(self):
        res = migrate.apply(self.store, dry=True)
        self.assertEqual(len(res["migrated"]), 1)  # the pre-v1 page
        self.assertIn("wiki/entities/acme-corp.md", migrate.plan(self.store))
        self.assertEqual(self.store.read("wiki/entities/acme-corp.md"),
                         PRE_V1_PAGE)
        self.assertFalse(self.store.exists("migrations"))

    def test_apply_archives_and_stamps(self):
        res = migrate.apply(self.store, dry=False)
        page = self.store.read("wiki/entities/acme-corp.md")
        self.assertIn("format: mem-wiki@2", page)
        archived = res["migrated"][0]["archive"]
        self.assertEqual(self.store.read(archived), PRE_V1_PAGE)
        front, _, claims = self.store.parse_page("wiki/entities/acme-corp.md")
        self.assertEqual(claims[0]["id"], "clm_aaa111")
        evts = [e for e in hygiene._events(self.store)
                if e["event"] == "migrate"]
        self.assertEqual(len(evts), 1)

    def test_second_run_is_clean(self):
        migrate.apply(self.store, dry=False)
        res2 = migrate.apply(self.store, dry=False)
        self.assertEqual(res2["migrated"], [])


class TestRulesAsData(Base):
    def _dir(self, layers):
        d = tempfile.mkdtemp(prefix="mem-rules-")
        for name, text in layers.items():
            with open(os.path.join(d, name), "w") as f:
                f.write(text)
        return d

    def test_base_defaults_active(self):
        eff = {r["name"]: r for r in rules.effective()}
        self.assertTrue(eff["inference_cap"]["enabled"])
        self.assertAlmostEqual(eff["inference_cap"]["params"]["cap"], 0.8)
        self.assertEqual(eff["derived_from_required"]["provenance"],
                         "base.yaml")

    def test_patch_disables_gate_no_code_edit(self):
        d = self._dir({
            "base.yaml": "rules:\n  - name: inference_cap\n    enabled: "
                         "true\n    params:\n      cap: 0.8\n",
            "patch.yml": "rules:\n  - name: inference_cap\n    enabled: "
                         "false\n"})
        eff = {r["name"]: r for r in rules.effective(d)}
        self.assertFalse(eff["inference_cap"]["enabled"])
        self.assertEqual(eff["inference_cap"]["provenance"], "patch.yml")
        c = self.mkclaim(conf=0.95)
        c["edges"] = [{"type": "derived_from", "target": "agent-inference"}]
        self.assertEqual(rules.enforce(c, directory=d), [])
        blocked = rules.enforce(c, directory=self._dir({
            "base.yaml": "rules:\n  - name: inference_cap\n    enabled: "
                         "true\n    params:\n      cap: 0.8\n"}))
        self.assertIn("exceeds cap", blocked[0])

    def test_quote_match_rule_gate(self):
        d = self._dir({"base.yaml": "rules:\n  - name: quote_match\n"
                                    "    enabled: true\n"})
        c = self.mkclaim()
        reasons = rules.enforce(c, ctx={"source_quote": "Lyon is nice",
                                        "raw_text": "Acme hq moved."},
                               directory=d)
        self.assertIn("hallucination gate", reasons[0])
        ok = rules.enforce(c, ctx={"source_quote": "moved.",
                                   "raw_text": "Acme hq moved."},
                          directory=d)
        self.assertEqual(ok, [])

    def test_layers_ordered_later_wins(self):
        d = self._dir({
            "base.yaml": "rules:\n  - name: text_nonempty\n    enabled: "
                         "true\n",
            "patch.yml": "rules:\n  - name: text_nonempty\n    enabled: "
                         "false\n"})
        layers = [f for f, _ in rules.load_layers(d)]
        self.assertEqual(layers, ["base.yaml", "patch.yml"])
        eff = {r["name"]: r for r in rules.effective(d)}
        self.assertFalse(eff["text_nonempty"]["enabled"])

    def test_hygiene_uses_rule_engine(self):
        os.environ["MEM_RULES_DIR"] = self._dir({
            "base.yaml": "rules:\n  - name: derived_from_required\n"
                         "    enabled: false\n"})
        try:
            c = self.mkclaim()
            c["edges"] = []
            self.assertEqual(hygiene.validate_claim(c), [])
        finally:
            del os.environ["MEM_RULES_DIR"]


MANUAL_GOOD = [{"subject": "Acme Corp", "predicate": "hq",
                "value": "Lyon", "confidence": 0.9,
                "source_quote": "Acme moved its HQ to Lyon."}]
MANUAL_BAD = [{"subject": "Acme Corp", "predicate": "revenue",
               "value": "9M", "confidence": 0.9,
               "source_quote": "Acme earns nine million euros."}]


class TestProviders(Base):
    RAW = "Acme moved its HQ to Lyon. Founded 2019 in Paris."

    def test_selection_defaults_and_errors(self):
        os.environ.pop("MEM_PROVIDER", None)
        self.assertEqual(providers.get_provider().name, "ollama")
        os.environ["MEM_PROVIDER"] = "manual"
        try:
            self.assertEqual(providers.get_provider().name, "manual")
        finally:
            del os.environ["MEM_PROVIDER"]
        with self.assertRaises(ValueError):
            providers.get_provider("nosuch")

    def test_manual_provider_quote_gate(self):
        p = providers.get_provider("manual")
        claims, warns = p.extract(self.RAW, ctx={"candidates":
                                                 MANUAL_GOOD + MANUAL_BAD})
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["pred"], "hq")
        self.assertIn("quote not in source", warns[0])

    def test_manual_without_candidates_warns(self):
        claims, warns = providers.get_provider("manual").extract(self.RAW)
        self.assertEqual(claims, [])
        self.assertIn("--claims", warns[0])

    def test_openai_compat_provider_roundtrip(self):
        os.environ["MEM_OPENAI_BASE_URL"] = "http://example.test/v1"
        os.environ["MEM_OPENAI_MODEL"] = "some-model"
        os.environ["MEM_OPENAI_API_KEY"] = "k123"
        sent = {}

        def fake_opener(url, model, system, prompt, timeout=120):
            sent.update(url=url, model=model, system=system, prompt=prompt)
            return json.dumps({"claims": MANUAL_GOOD})

        try:
            claims, warns = providers.get_provider(
                "openai-compatible").extract(self.RAW, opener=fake_opener)
            self.assertEqual(len(claims), 1)
            self.assertEqual(sent["model"], "some-model")
            self.assertIn("HQ", sent["prompt"])
        finally:
            for k in ("MEM_OPENAI_BASE_URL", "MEM_OPENAI_MODEL",
                      "MEM_OPENAI_API_KEY"):
                del os.environ[k]

    def test_openai_compat_http_shape(self):
        captured = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"choices": [{"message": {"content":
                        json.dumps({"claims": MANUAL_GOOD})}}]}
                        ).encode()

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            captured["body"] = json.loads(req.data)
            return Resp()

        real = providers.urllib.request.urlopen
        providers.urllib.request.urlopen = fake_urlopen
        os.environ["MEM_OPENAI_BASE_URL"] = "http://x.test/v1"
        try:
            p = providers.OpenAICompatProvider()
            content = p.call("http://x.test/v1", "m", "sys", "prompt")
            claims, _ = providers.filter_candidates(
                providers.parse_json_first(content)["claims"], self.RAW)
            self.assertEqual(len(claims), 1)
            self.assertEqual(captured["url"],
                             "http://x.test/v1/chat/completions")
            self.assertIn("Bearer", captured["auth"] or "")
        finally:
            providers.urllib.request.urlopen = real
            del os.environ["MEM_OPENAI_BASE_URL"]

    def test_switch_provider_one_env_line(self):
        from mem import extract as extract_mod

        def fake_opener(url, model, system, prompt, timeout=120):
            return json.dumps({"claims": MANUAL_GOOD})
        os.environ["MEM_PROVIDER"] = "ollama"
        try:
            a, _ = extract_mod.extract(self.RAW, opener=fake_opener)
        finally:
            os.environ["MEM_PROVIDER"] = "manual"
        b, _ = extract_mod.extract(self.RAW,
                                  ctx={"candidates": MANUAL_GOOD})
        del os.environ["MEM_PROVIDER"]
        self.assertEqual([c["value"] for c in a],
                         [c["value"] for c in b])


class TestSources(Base):
    def test_classify(self):
        self.assertEqual(sources.classify("https://x.ai/a"), "url")
        self.assertEqual(sources.classify("-"), "stdin")
        self.assertEqual(sources.classify(
            "knowledge/inbox/ask-brave-2026-09-27.md"), "session")
        self.assertEqual(sources.classify("notes.txt"), "file")

    def test_lineage_identical_across_kinds(self):
        path = os.path.join(self.root, "src.md")
        with open(path, "w") as f:
            f.write("Hello world. Keep it.")
        k1, t1, l1 = sources.resolve(path)
        import io
        k2, t2, l2 = sources.resolve("-", stdin=io.StringIO(t1))
        self.assertEqual(k1, "file")
        self.assertEqual(k2, "stdin")
        for lin in (l1, l2):
            self.assertEqual(sorted(lin), ["content_hash", "origin",
                                           "retrieved_at"])
        self.assertEqual(l1["content_hash"], l2["content_hash"])

    def test_session_prompt_family(self):
        self.assertEqual(sources.prompt_kind("session"), "session")
        self.assertIn("transcript", providers.system_for("session"))
        self.assertNotIn("transcript", providers.system_for("web"))

    def _claims_file(self, payload):
        p = os.path.join(self.root, "claims.json")
        with open(p, "w") as f:
            json.dump(payload, f)
        return p

    def test_ingest_manual_file_end_to_end(self):
        src = os.path.join(self.root, "ask-brave-export.md")
        with open(src, "w") as f:
            f.write("# Chat\n\nUser: Where is Acme HQ?\n"
                    "Assistant: Acme moved its HQ to Lyon.\n")
        cf = self._claims_file([{
            "subject": "Acme Corp", "predicate": "hq", "value": "Lyon",
            "confidence": 0.9,
            "source_quote": "Acme moved its HQ to Lyon."}])
        code = cli.main(["--home", self.root, "ingest", src,
                         "--provider", "manual", "--claims", cf])
        self.assertEqual(code, 0)
        page = "wiki/entities/acme-corp.md"
        _, _, claims = self.store.parse_page(page)
        self.assertEqual(claims[0]["status"], "unverified")
        raws = [r for r in os.listdir(os.path.join(self.root, "raw"))
                if r.endswith(".md")]
        self.assertTrue(any("kind: session" in self.store.read("raw/" + r)
                            for r in raws))

    def test_ingest_hallucinated_quote_rejected(self):
        src = os.path.join(self.root, "session-notes.md")
        with open(src, "w") as f:
            f.write("Real talk happened.")
        cf = self._claims_file([{
            "subject": "Acme Corp", "predicate": "hq", "value": "Mars",
            "confidence": 0.9, "source_quote": "Not in the text."}])
        cli.main(["--home", self.root, "ingest", src,
                  "--provider", "manual", "--claims", cf])
        self.assertEqual(self.store.all_pages(), [])

    def test_ingest_stdin_source(self):
        cf = self._claims_file([{
            "subject": "Acme Corp", "predicate": "hq", "value": "Lyon",
            "confidence": 0.9, "source_quote": "HQ is in Lyon."}])
        real = sys.stdin
        sys.stdin = __import__("io").StringIO("HQ is in Lyon. End.")
        try:
            code = cli.main(["--home", self.root, "ingest", "-",
                             "--provider", "manual", "--claims", cf])
        finally:
            sys.stdin = real
        self.assertEqual(code, 0)
        self.assertEqual(len(self.store.all_pages()), 1)

    def test_dump_prompt_visible(self):
        src = os.path.join(self.root, "s.md")
        with open(src, "w") as f:
            f.write("Some text.")
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            cli.main(["--home", self.root, "ingest", src,
                      "--provider", "manual", "--dump-prompt"])
        out = buf.getvalue()
        self.assertIn("Schema", out)
        self.assertIn("Some text.", out)


SESSION_FIXTURE = """# OpenFox session export

- session_id: 921f4d34
launchd caches the job definition at load time; editing a plist on disk
changes nothing. argv cannot contain NUL bytes on POSIX; the trap is
`__file__` is relative under `unittest discover`. The
`content_hash: (\\w+)` search regex no longer matched after quoting.
Keep `mem scrape` as an alias: mini's LaunchDaemon, MCP clients, and muscle memory all call scrape;
Commit at each task boundary and push to the mini hub.
"""

SESSION_CLAIMS = [
    {"subject": "launchd", "predicate": "gotcha", "value": "edits to "
     "loaded plists are ignored until reload", "confidence": 0.9,
     "source_quote": "launchd caches the job definition at load time"},
    {"subject": "python-subprocess", "predicate": "incident", "value":
     "NUL byte in argv ValueError", "confidence": 0.9,
     "source_quote": "argv cannot contain NUL bytes on POSIX"},
    {"subject": "unittest-discovery", "predicate": "incident", "value":
     "__file__ relative breaks repo-root math", "confidence": 0.9,
     "source_quote": "`__file__` is relative under `unittest discover`"},
    {"subject": "mem-codec", "predicate": "incident", "value": "quoted "
     "frontmatter broke raw dedupe regex", "confidence": 0.85,
     "source_quote": "search regex no longer matched"},
    {"subject": "mem-scrape-alias", "predicate": "decision", "value":
     "keep scrape alias for fleet compat", "confidence": 0.85,
     "source_quote": "mini's LaunchDaemon, MCP clients, and muscle "
                     "memory all call scrape;"},
    {"subject": "commit-hygiene", "predicate": "decision", "value":
     "commit at task boundaries, push to hub", "confidence": 0.85,
     "source_quote": "Commit at each task boundary and push to the mini "
                     "hub."},
    {"subject": "mem-codec", "predicate": "gotcha", "value": "low "
     "confidence noise", "confidence": 0.2,
     "source_quote": "launchd caches the job definition at load time"},
    {"subject": "hallucination", "predicate": "incident", "value":
     "fabricated", "confidence": 0.95,
     "source_quote": "the mini spontaneously time-travelled"},
]


class TestSessionJournal(Base):
    def setUp(self):
        super().setUp()
        self.src = os.path.join(self.root, "openfox-session-export.md")
        with open(self.src, "w") as f:
            f.write(SESSION_FIXTURE)
        self.cf = os.path.join(self.root, "claims.json")
        with open(self.cf, "w") as f:
            json.dump(SESSION_CLAIMS, f)

    def _ingest(self):
        cli.main(["--home", self.root, "ingest", self.src,
                  "--kind", "session", "--provider", "manual",
                  "--claims", self.cf, "--producer", "openfox",
                  "--session-id", "921f4d34"])

    def test_incident_predicates_valid(self):
        for p in ("incident", "decision", "gotcha"):
            self.assertIn(p, schema.PREDICATES)

    def test_five_incident_claims_queryable_with_quote_ref(self):
        self._ingest()
        out = __import__("io").StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(out):
            cli.main(["--home", self.root, "query",
                      "why does launchd ignore edited plists"])
        pages = json.loads(out.getvalue())
        texts = [c["text"] for pg in pages for c in pg["claims"]]
        self.assertTrue(any("launchd" in t for t in texts), texts)
        refs = [c["quote_ref"] for pg in pages for c in pg["claims"]
                if c["quote_ref"]]
        self.assertTrue(any("openfox-session-export" in r for r in refs),
                        refs)

    def test_total_stored_at_least_five_and_noise_rejected(self):
        import io as _io
        from contextlib import redirect_stdout
        buf = _io.StringIO()
        with redirect_stdout(buf):
            self._ingest()
        out = json.loads(buf.getvalue())
        self.assertGreaterEqual(len(out["stored"]), 5)
        self.assertTrue(any("quote not in source" in w
                            for w in out["warnings"]))
        total = sum(len(self.store.parse_page(p)[2])
                    for p in self.store.all_pages())
        self.assertGreaterEqual(total, 5)
        low = [c for p in self.store.all_pages()
               for c in self.store.parse_page(p)[2] if c["confidence"]
               < 0.5]
        self.assertEqual(len(low), 1)

    def test_lineage_in_raw_frontmatter(self):
        self._ingest()
        raws = [r for r in os.listdir(os.path.join(self.root, "raw"))
                if r.endswith(".md")]
        fm = self.store.read("raw/" + raws[0])
        self.assertIn("producer: openfox", fm)
        self.assertIn("session_id: 921f4d34", fm)
        self.assertIn("kind: session", fm)


if __name__ == "__main__":
    unittest.main()
