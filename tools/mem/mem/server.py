"""Stdlib HTTP server: validated writes, locks, git backstop. + /mcp shim."""

import datetime
import json
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import cli, extract, hygiene, index, schema, sources
from .store import Store

VERSION = "0.1.0"


class Handler(BaseHTTPRequestHandler):
    store = None  # injected
    allow_writes = True  # False on the public read-only listener

    def log_message(self, fmt, *args):
        pass

    # --- plumbing ---

    def _json(self, code, obj):
        body = json.dumps(obj, indent=2, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # --- routing ---

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        try:
            if url.path == "/healthz":
                self._json(200, {"ok": True, "version": VERSION,
                                 "home": self.store.root,
                                 "writes_via": None if self.allow_writes
                                 else self.write_hint})
            elif url.path == "/index":
                self._json(200, {"index.yaml": self.store.read(
                    "index.yaml")})
            elif url.path == "/query":
                self.api_query({"text": q.get("text", [""])[0],
                                "top_k": int(q.get("top_k", ["5"])[0])})
            elif url.path == "/show":
                self.api_show({"page": q.get("page", [""])[0]})
            elif url.path == "/lint":
                self.api_lint({})
            elif url.path == "/stale":
                self.api_stale({})
            elif url.path == "/contradictions":
                self.api_contradictions({})
            elif url.path == "/orphans":
                self.api_orphans({})
            else:
                self._json(404, {"error": "not found"})
        except KeyError as e:
            self._json(404, {"error": str(e)})
        except ValueError as e:
            self._json(422, {"error": str(e)})

    def do_POST(self):
        if not self.allow_writes:
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            return self._json(405, {
                "error": "read-only listener: writes require the "
                         "mem-writer port (see writes_via in /healthz)"})
        try:
            body = self._body()
        except json.JSONDecodeError as e:
            return self._json(400, {"error": "invalid json: %s" % e})
        try:
            handler = getattr(self, "api_" + self.path.strip("/").replace(
                "/", "_"), None)
            if self.path == "/mcp":
                return self.api_mcp(body)
            if handler is None:
                return self._json(404, {"error": "no such endpoint"})
            handler(body)
        except PermissionError as e:
            self._json(403, {"error": str(e)})
        except KeyError as e:
            self._json(404, {"error": str(e)})
        except ValueError as e:
            self._json(422, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self._json(500, {"error": "%s: %s" % (type(e).__name__, e)})

    # --- endpoints ---

    def api_claims(self, body):
        claim = body.get("claim") or {}
        date = datetime.date.today().isoformat()
        raw_rel = body.get("raw")
        sources = claim.get("sources") or []
        edges = [{"type": "derived_from", "target": s} for s in sources]
        parsed = {"text": claim.get("text", ""),
                  "pred": claim.get("pred", "other"),
                  "status": claim.get("status", "unverified"),
                  "confidence": float(claim.get("confidence", 0.5)),
                  "date": date, "edges": edges}
        quote = claim.get("source_quote")
        if quote and raw_rel and self.store.exists(raw_rel):
            if quote not in self.store.read(raw_rel):
                raise ValueError("source_quote not found in %s "
                                 "(hallucination gate)" % raw_rel)
        elif not raw_rel:
            raise ValueError("raw source required for POST /claims")
        page = body.get("page")
        if page:
            self.store.ensure_page(page)
        else:
            page = self.store.page_for_subject(
                claim.get("subject", claim.get("text", "misc")))
        try:
            result = hygiene.ingest(self.store, page, parsed,
                                    source_quote=quote, raw_rel=raw_rel)
        except Exception:
            self.store.remove_if_empty(page)
            raise
        result["page"] = page
        index.rebuild(self.store)
        self.store.git_commit("mem: claim %s -> %s" % (result["id"], page))
        self._json(201, result)

    def api_scrape(self, body):
        source = body.get("url") or body.get("source")
        if source is None and "text" in body:
            origin = body.get("origin", "http-post")
            text = body["text"]
            today = datetime.date.today().isoformat()
            raw_rel, dup = self.store.write_raw(origin, text, today,
                                                kind=body.get("kind",
                                                             "web"))
            if dup and not body.get("force"):
                return self._json(200, {"skipped": "duplicate",
                                        "raw": raw_rel})
            claims = body.get("claims")
            ctx = {"candidates": claims, "raw_text": text}
            extracted, warnings = extract.extract(
                text, kind=sources.prompt_kind(body.get("kind", "web")),
                provider=body.get("provider"), ctx=ctx)
            return self._store_extracted(extracted, warnings, raw_rel,
                                         text)
        if not source:
            raise ValueError("url, source, or text required")
        code, out = cli._ingest(self.store, source,
                                kind=body.get("kind"),
                                force=bool(body.get("force")),
                                provider=body.get("provider"),
                                claims=body.get("claims"))
        self._json(200 if "skipped" in out else 201, out)

    def _store_extracted(self, extracted, warnings, raw_rel, text):
        date = datetime.date.today().isoformat()
        stored = []
        for c in extracted:
            page = self.store.page_for_subject(c["subject"])
            try:
                result = hygiene.ingest(
                    self.store, page,
                    {"text": "%s %s: %s" % (c["subject"], c["pred"],
                                            c["value"]),
                     "pred": c["pred"], "status": "unverified",
                     "confidence": c["confidence"], "date": date,
                     "edges": [{"type": "derived_from",
                                "target": raw_rel}]},
                    source_quote=c["source_quote"], raw_rel=raw_rel)
            except ValueError as e:
                self.store.remove_if_empty(page)
                warnings.append("rejected: %s" % e)
                continue
            result["page"] = page
            stored.append(result)
        index.rebuild(self.store)
        self.store.git_commit("mem: ingest inline (%d claims)"
                              % len(stored))
        self._json(201, {"raw": raw_rel, "stored": stored,
                         "warnings": warnings})

    def api_query(self, body):
        text = body.get("text", "")
        top_k = int(body.get("top_k", 5))
        today = datetime.date.today()
        out = []
        for e in index.route(self.store, text):
            _, _, claims = self.store.parse_page(e["file"])
            ranked = index.rank_claims(claims, text)[:top_k]
            out.append({"page": e["file"], "summary": e["summary"],
                        "claims": [{"id": c["id"], "text": c["text"],
                                    "status": c["status"],
                                    "quote_ref": (schema.claim_edges(
                                        c, "derived_from") or [None])[0],
                                    "effective": round(
                                        schema.effective_confidence(c, today),
                                        3),
                                    "sources": schema.claim_edges(
                                        c, "derived_from")}
                                   for _, c in ranked
                                   if c["status"] != "retracted"]})
        self._json(200, out)

    def api_show(self, body):
        page = body["page"]
        _, _, claims = self.store.parse_page(page)
        today = datetime.date.today()
        self._json(200, {"page": page, "text": self.store.read(page),
                         "computed": [{"id": c["id"], "status": c["status"],
                                       "effective": round(
                                           schema.effective_confidence(
                                               c, today), 3)}
                                      for c in claims]})

    def api_verify(self, body):
        hygiene.verify(self.store, body["page"], body["claim"],
                       body.get("source", "manual"),
                       actor=body.get("actor", "human"))
        index.rebuild(self.store)
        self.store.git_commit("mem: verify %s" % body["claim"])
        self._json(200, {"ok": True, "claim": body["claim"],
                         "status": "verified"})

    def api_retract(self, body):
        hygiene.retract(self.store, body["page"], body["claim"],
                        body.get("reason", ""))
        index.rebuild(self.store)
        self.store.git_commit("mem: retract %s" % body["claim"])
        self._json(200, {"ok": True, "claim": body["claim"],
                         "status": "retracted"})

    def api_lint(self, body):
        self._json(200, hygiene.lint(self.store))

    def api_stale(self, body):
        self._json(200, hygiene.stale_report(self.store))

    def api_contradictions(self, body):
        self._json(200, hygiene.contradictions(self.store))

    def api_orphans(self, body):
        self._json(200, hygiene.orphans(self.store))

    def api_audit(self, body):
        _, _, claims = self.store.parse_page(body["page"])
        target = next((c for c in claims if c["id"] == body["claim"]), None)
        if not target:
            raise KeyError("claim not found: %s" % body["claim"])
        events = [e for e in hygiene._events(self.store)
                  if e.get("claim") == body["claim"]]
        self._json(200, {"claim": target, "events": events})

    # --- MCP (JSON-RPC 2.0, minimal) ---

    MCP_TOOLS = [
        {"name": "query", "description": "Route a question through "
         "index.yaml and return ranked claims with confidence.",
         "inputSchema": {"type": "object",
                         "properties": {"text": {"type": "string"},
                                        "top_k": {"type": "integer"}},
                         "required": ["text"]}},
        {"name": "show", "description": "Render a wiki page with computed "
         "effective confidence.",
         "inputSchema": {"type": "object",
                         "properties": {"page": {"type": "string"}},
                         "required": ["page"]}},
        {"name": "lint", "description": "Hygiene violations report.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "contradictions", "description": "Unresolved conflicts.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "scrape", "description": "Ingest a source (url, server-"
         "side path, or inline text), extract claims with the configured "
         "provider, quote-gate, validate and store. Only write path for "
         "agents. Manual provider: pass claims list.",
         "inputSchema": {"type": "object",
                         "properties": {"url": {"type": "string"},
                                        "source": {"type": "string"},
                                        "text": {"type": "string"},
                                        "kind": {"type": "string"},
                                        "provider": {"type": "string"},
                                        "claims": {"type": "array"}},
                         "required": []}},
        {"name": "verify", "description": "Human confirmation of a claim. "
         "Fails unless actor is human.",
         "inputSchema": {"type": "object",
                         "properties": {"page": {"type": "string"},
                                        "claim": {"type": "string"},
                                        "source": {"type": "string"},
                                        "actor": {"type": "string"}},
                         "required": ["page", "claim"]}},
        {"name": "retract", "description": "Mark a claim retracted.",
         "inputSchema": {"type": "object",
                         "properties": {"page": {"type": "string"},
                                        "claim": {"type": "string"},
                                        "reason": {"type": "string"}},
                         "required": ["page", "claim"]}},
    ]

    _MCP_DISPATCH = {"query": "api_query", "show": "api_show",
                     "lint": "api_lint",
                     "contradictions": "api_contradictions",
                     "scrape": "api_scrape", "verify": "api_verify",
                     "retract": "api_retract"}

    class _Capture:
        def __init__(self):
            self.payload = None

        def _json(self, code, obj):
            self.payload = (code, obj)

        def _body(self):
            return {}

    def api_mcp(self, body):
        method = body.get("method")
        params = body.get("params", {})
        rid = body.get("id")
        if method == "initialize":
            return self._json(200, {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mem", "version": VERSION}}})
        if method == "notifications/initialized":
            return self._json(200, {"jsonrpc": "2.0", "id": rid,
                                    "result": {}})
        if method == "tools/list":
            return self._json(200, {"jsonrpc": "2.0", "id": rid,
                                    "result": {"tools": self.MCP_TOOLS}})
        if method == "tools/call":
            name = params.get("name")
            fn = getattr(self, self._MCP_DISPATCH.get(name, "nope"), None)
            if fn is None:
                return self._json(200, {"jsonrpc": "2.0", "id": rid,
                                        "error": {"code": -32601,
                                                  "message": "no tool"}})
            cap = self._Capture()
            old = self._json
            self._json = cap._json
            try:
                fn(params.get("arguments", {}))
            except PermissionError as e:
                cap.payload = (403, {"error": str(e)})
            except (KeyError, ValueError) as e:
                cap.payload = (422, {"error": str(e)})
            finally:
                self._json = old
            code, payload = cap.payload or (500, {"error": "no result"})
            ok = code < 400
            return self._json(200, {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text",
                             "text": json.dumps(payload, default=str)}],
                "isError": not ok}})
        return self._json(200, {"jsonrpc": "2.0", "id": rid,
                                "error": {"code": -32601,
                                          "message": "unknown method"}})


def serve(store, port=8520, listen="127.0.0.1", write_port=0,
          write_listen="0.0.0.0"):
    if not store.exists("index.yaml"):
        index.rebuild(store)
    if write_port:
        public = type("BoundRO", (Handler,), {"store": store,
                                              "allow_writes": False,
                                              "write_hint": write_port})
        writer = type("BoundRW", (Handler,), {"store": store,
                                              "allow_writes": True,
                                              "write_hint": write_port})
        whttpd = ThreadingHTTPServer((write_listen, write_port), writer)
        threading.Thread(target=whttpd.serve_forever, daemon=True).start()
        print("mem write listener on http://%s:%d (tag:mem-writer only)"
              % (write_listen, write_port))
    else:
        public = type("Bound", (Handler,), {"store": store,
                                            "write_hint": None})
    httpd = ThreadingHTTPServer((listen, port), public)
    print("mem serving %s on http://%s:%d%s" % (
        store.root, listen, port,
        "" if write_port else " (read+write)"))
    httpd.serve_forever()
