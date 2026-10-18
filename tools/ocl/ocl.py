#!/usr/bin/env python3
"""ocl - OpenClaims ledger: a lean, clean-room CLI for claim provenance.

Conforms to the OpenClaims v0.1 event model (schemas vendored under
vendor/openclaims/). Append-only JSONL store, RFC 8785-style canonical
digests, hash-chained events. Offline-friendly: when OCL_URL is set,
writes POST to the remote ledger and spool locally on failure; `ocl
sync` flushes the spool.

This implementation is clean-room (MIT, our own), conforming to the
OpenClaims v0.1 specification by github.com/openclaims-ai/openclaims.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jcs import DEFAULT_SCHEMA_URL, SPEC_VERSION, event_digest, verify_event_digest  # noqa: E402
from ocl_validate import validate_event  # noqa: E402

REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
DEFAULT_STORE = os.environ.get("OCL_STORE", os.path.join(REPO_ROOT, "claims", "claims.jsonl"))
DEFAULT_SPOOL = os.environ.get("OCL_SPOOL", os.path.join(REPO_ROOT, "claims", "spool.jsonl"))

PRODUCER_ID = os.environ.get("OCL_PRODUCER_ID", "urn:agent:openfox")
PRODUCER_TYPE = os.environ.get("OCL_PRODUCER_TYPE", "service")
PRODUCER_NAME = os.environ.get("OCL_PRODUCER_NAME", "OpenFox agent")
FACET_SCHEMA_BASE = "https://openfox.local/schemas/"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:26])


def producer():
    return {"agent_id": PRODUCER_ID, "agent_type": PRODUCER_TYPE, "name": PRODUCER_NAME}


def facet(name, payload):
    payload = dict(payload)
    payload.setdefault("_producer", PRODUCER_ID)
    payload.setdefault("_schemaURL", "%s%s" % (FACET_SCHEMA_BASE, name))
    return payload


def parse_selector(spec):
    parts = spec.split(":")
    kind = parts[0]
    if kind in ("text_span", "byte_range"):
        return {"type": kind, "start": int(parts[1]), "end": int(parts[2])}
    if kind == "page_span":
        return {"type": kind, "page": int(parts[1]), "start": int(parts[2]), "end": int(parts[3])}
    if kind == "json_pointer":
        return {"type": kind, "path": spec.split(":", 1)[1]}
    if kind == "uri_fragment":
        return {"type": kind, "fragment": spec.split(":", 1)[1]}
    raise ValueError("unsupported selector spec: %s" % spec)


def read_events(path):
    events = []
    if not os.path.exists(path):
        return events
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit("store %s:%d corrupt: %s" % (path, line_no, exc))
    return events


def append_event(event, store=None):
    store = store or DEFAULT_STORE
    os.makedirs(os.path.dirname(os.path.abspath(store)), exist_ok=True)
    with open(store, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=False, ensure_ascii=False) + "\n")


def prev_chain_state(store):
    events = read_events(store)
    if not events:
        return None, None
    last = events[-1]
    return last.get("event_id"), last.get("digest")


def deliver(event, store):
    url = os.environ.get("OCL_URL")
    if url:
        endpoint = url.rstrip("/") + "/events"
        body = json.dumps(event).encode("utf-8")
        request = urllib.request.Request(
            endpoint, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not payload.get("valid", True):
                    raise RuntimeError("server rejected event: %s" % payload)
                return "remote"
        except Exception as exc:  # noqa: BLE001 - fall back to spool
            append_event(event, DEFAULT_SPOOL)
            sys.stderr.write("warning: remote unavailable (%s); spooled\n" % exc)
            return "spooled"
    append_event(event, store)
    return "local"


def build_event(event_type, fields, store, with_chain=True):
    prev_id, prev_digest = prev_chain_state(store) if with_chain else (None, None)
    event = {
        "event_id": new_id("evt"),
        "event_type": event_type,
        "event_time": now(),
        "spec_version": SPEC_VERSION,
        "schema_url": DEFAULT_SCHEMA_URL,
        "producer": producer(),
    }
    if prev_id:
        event["auditable_trace"] = {
            "event_ids": [prev_id],
            "hash_chain": [prev_digest] if prev_digest else [],
        }
    event.update(fields)
    event["digest"] = event_digest(event)
    result = validate_event(event)
    if not result["valid"]:
        for err in result["errors"]:
            sys.stderr.write("invalid event: %s: %s\n" % (err["path"], err["message"]))
        raise SystemExit(2)
    return event, deliver(event, store)


def cmd_emit(args):
    claim = {
        "claim_id": args.claim_id or new_id("clm"),
        "text": args.text,
        "claim_type": args.type,
        "asserted_at": args.asserted_at or now(),
    }
    if args.derived_from:
        claim["derived_from_claims"] = args.derived_from
    if args.facet:
        name, path = args.facet.split("=", 1)
        with open(path, encoding="utf-8") as handle:
            claim["facets"] = {name.split("/")[-1]: facet(name, json.load(handle))}
    fields = {"claim": claim}
    sources, evidence = [], []
    if args.source_uri:
        source_id = new_id("src")
        source = {"source_id": source_id, "uri": args.source_uri, "retrieved_at": now()}
        if args.source_digest:
            source["digest"] = {
                "algorithm": "sha256",
                "encoding": "base64url",
                "value": args.source_digest,
            }
        sources.append(source)
        ev = {
            "evidence_id": new_id("ev"),
            "source_ref": source_id,
            "claim_ref": claim["claim_id"],
            "selector": parse_selector(args.selector or "uri_fragment:full"),
            "support_type": args.support_type,
            "observed_at": now(),
        }
        evidence.append(ev)
    if sources:
        fields["sources"] = sources
    if evidence:
        fields["evidence"] = evidence
    fields.setdefault("sources", [])
    fields.setdefault("evidence", [])
    event, where = build_event("claim.emitted", fields, args.store)
    print(json.dumps({"ok": True, "event_id": event["event_id"], "claim_id": claim["claim_id"], "stored": where}))


def cmd_verify(args):
    verification = {
        "verification_id": new_id("ver"),
        "verification_result": args.result,
        "verification_method": args.method,
        "claim_status": "disputed" if args.result == "contradicted" else "active",
        "validator": {
            "agent_id": args.validator_id,
            "agent_type": args.validator_type,
            "name": args.validator_name or args.validator_id,
        },
        "verified_at": args.verified_at or now(),
    }
    if args.confidence is not None:
        verification["confidence"] = args.confidence
    fields = {"claim_ref": args.claim_ref, "verification": verification}
    fields["evidence"] = []
    if args.evidence_uri:
        source_id = new_id("src")
        fields["sources"] = [
            {"source_id": source_id, "uri": args.evidence_uri, "retrieved_at": now()}
        ]
        fields["evidence"].append(
            {
                "evidence_id": new_id("ev"),
                "source_ref": source_id,
                "claim_ref": args.claim_ref,
                "selector": parse_selector(
                    args.selector or "uri_fragment:verification"
                ),
                "support_type": "supports_directly"
                if args.result == "supported"
                else "contradicts",
                "observed_at": now(),
            }
        )
    if args.evidence_digest:
        fields["evidence"][-1]["content_digest"] = {
            "algorithm": "sha256",
            "encoding": "base64url",
            "value": args.evidence_digest,
        }
    if args.tool_name:
        fields["tool_runs"] = [
            {
                "tool_run_id": new_id("run"),
                "tool_type": args.tool_type or "verifier",
                "tool": {"name": args.tool_name, "version": args.tool_version or "0.0.0"},
            }
        ]
    event, where = build_event("claim.verified", fields, args.store)
    print(
        json.dumps(
            {
                "ok": True,
                "event_id": event["event_id"],
                "claim_ref": args.claim_ref,
                "result": args.result,
                "stored": where,
            }
        )
    )


def cmd_dispute(args):
    if not args.rationale and not args.evidence_uri and not args.contradicts:
        raise SystemExit("dispute requires --rationale, --evidence-uri or --contradicts")
    fields = {"claim_ref": args.claim_ref}
    if args.rationale:
        fields["dispute_rationale"] = args.rationale
    if args.contradicts:
        fields.setdefault("claim", None)
    if args.evidence_uri:
        source_id = new_id("src")
        fields["sources"] = [
            {"source_id": source_id, "uri": args.evidence_uri, "retrieved_at": now()}
        ]
        fields["contradicting_evidence"] = [
            {
                "evidence_id": new_id("ev"),
                "source_ref": source_id,
                "claim_ref": args.claim_ref,
                "selector": parse_selector(args.selector or "uri_fragment:dispute"),
                "support_type": "contradicts",
                "observed_at": now(),
            }
        ]
    if args.contradicts:
        fields.setdefault("claim", {})
        fields["claim"] = {
            "claim_id": new_id("clm"),
            "text": args.contradicts_text or "contradicting claim referenced",
            "claim_type": "factual",
            "asserted_at": now(),
            "relations": [{"relation_type": "contradicts", "claim_ref": args.claim_ref}],
        }
    else:
        fields.pop("claim", None)
    event, where = build_event("claim.disputed", fields, args.store)
    print(json.dumps({"ok": True, "event_id": event["event_id"], "claim_ref": args.claim_ref, "stored": where}))


def cmd_retract(args):
    event, where = build_event(
        "claim.retracted",
        {"claim_ref": args.claim_ref, "retracted_at": args.retracted_at or now()},
        args.store,
    )
    print(json.dumps({"ok": True, "event_id": event["event_id"], "claim_ref": args.claim_ref, "stored": where}))


def cmd_check(args):
    found = check_claim(args.claim_ref, args.store)
    if found is None:
        raise SystemExit("claim %s not found in %s" % (args.claim_ref, args.store or DEFAULT_STORE))
    print(json.dumps(found, indent=2))


def check_claim(claim_ref, store=None):
    events = read_events(store or DEFAULT_STORE)
    states = [event for event in events if event_involves(event, claim_ref)]
    if not states:
        return None
    status = "asserted"
    result = None
    method = None
    history = []
    for event in states:
        etype = event.get("event_type")
        entry = {"event_id": event["event_id"], "type": etype, "time": event.get("event_time")}
        if etype == "claim.verified":
            verification = event.get("verification", {})
            result = verification.get("verification_result")
            method = verification.get("verification_method")
            status = verification.get("claim_status", status)
            entry.update({"result": result, "method": method})
        elif etype == "claim.disputed":
            status = "disputed"
            entry["rationale"] = event.get("dispute_rationale")
        elif etype == "claim.retracted":
            status = "retracted"
        elif etype == "claim.emitted":
            status = "active" if status == "asserted" else status
        history.append(entry)
    return {
        "claim_ref": claim_ref,
        "status": status,
        "last_result": result,
        "last_method": method,
        "events": len(history),
        "history": history,
    }


def event_involves(event, claim_ref):
    if event.get("claim_ref") == claim_ref:
        return True
    claim = event.get("claim") or {}
    if claim.get("claim_id") == claim_ref:
        return True
    for evidence in (event.get("evidence") or []) + (event.get("contradicting_evidence") or []):
        if evidence.get("claim_ref") == claim_ref:
            return True
    return False


def cmd_query(args):
    events = read_events(args.store)
    emitted = {}
    for event in events:
        if event.get("event_type") == "claim.emitted" and event.get("claim"):
            emitted[event["claim"]["claim_id"]] = event
    rows = []
    for claim_id, event in emitted.items():
        state = check_claim(claim_id, args.store)
        if args.status and state["status"] != args.status:
            continue
        if args.method and state.get("last_method") != args.method:
            continue
        text = event["claim"]["text"]
        if args.text and args.text.lower() not in text.lower():
            continue
        rows.append(
            {
                "claim_ref": claim_id,
                "status": state["status"],
                "result": state.get("last_result"),
                "method": state.get("last_method"),
                "text": text,
                "sources": [s.get("uri") for s in (event.get("sources") or [])],
            }
        )
    if args.cite:
        for row in rows:
            tag = "%s/%s" % (row["result"] or "unverified", row["method"] or "none")
            print("[claim:%s|%s] %s%s" % (row["claim_ref"], tag, row["text"],
                                           (" <- " + row["sources"][0]) if row["sources"] and args.cite == "full" else ""))
    else:
        print(json.dumps(rows, indent=2))


def cmd_chain(args):
    store = args.store or DEFAULT_STORE
    events = read_events(store)
    if not events:
        print(json.dumps({"ok": True, "events": 0, "store": store}))
        return
    previous_id = None
    previous_digest = None
    for index, event in enumerate(events):
        ok_digest = verify_event_digest(event)
        trace = event.get("auditable_trace") or {}
        ids = trace.get("event_ids") or []
        chain = trace.get("hash_chain") or []
        expected_id = previous_id
        expected_digest = previous_digest
        link_ok = (
            (expected_id is None and not ids)
            or (ids == [expected_id] and chain == [expected_digest])
        )
        if args.verify and not (ok_digest and link_ok):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "index": index,
                        "event_id": event.get("event_id"),
                        "digest_ok": ok_digest,
                        "link_ok": link_ok,
                    }
                )
            )
            raise SystemExit(1)
        previous_id = event.get("event_id")
        previous_digest = event.get("digest")
    print(json.dumps({"ok": True, "events": len(events), "store": store}))


def cmd_conform(args):
    fixtures_dir = args.fixtures_dir or os.path.join(
        REPO_ROOT, "vendor", "openclaims", "fixtures"
    )
    failures = []
    passed_valid = passed_invalid = 0
    valid_dir = os.path.join(fixtures_dir, "valid")
    for name in sorted(os.listdir(valid_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(valid_dir, name), encoding="utf-8") as handle:
            event = json.load(handle)
        result = validate_event(event)
        if result["valid"]:
            passed_valid += 1
        else:
            failures.append({"fixture": "valid/%s" % name, "unexpected_errors": result["errors"]})
    invalid_dir = os.path.join(fixtures_dir, "invalid")
    if os.path.isdir(invalid_dir):
        for name in sorted(os.listdir(invalid_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(invalid_dir, name), encoding="utf-8") as handle:
                event = json.load(handle)
            result = validate_event(event)
            if result["valid"]:
                failures.append({"fixture": "invalid/%s" % name, "unexpected_errors": ["expected invalid"]})
            else:
                passed_invalid += 1
                print("rejected invalid/%s: %s" % (name, result["errors"][0]["message"]))
    ok = not failures
    print(
        json.dumps(
            {
                "ok": ok,
                "valid_pass": passed_valid,
                "invalid_rejected": passed_invalid,
                "failures": failures,
            },
            indent=2,
        )
    )
    if not ok:
        raise SystemExit(1)


def cmd_serve(args):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    store = args.store or DEFAULT_STORE

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *log_args):  # quiet
            sys.stderr.write(fmt % log_args + "\n")

        def do_GET(self):
            if self.path == "/chain/verify":
                import io
                import contextlib

                buffer = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buffer):
                        chain_args = argparse.Namespace(store=store, verify=True)
                        cmd_chain(chain_args)
                    self._json(200, json.loads(buffer.getvalue()))
                except SystemExit:
                    self._json(500, json.loads(buffer.getvalue()))
                return
            if self.path.startswith("/claims/"):
                claim_ref = self.path.split("/claims/", 1)[1]
                state = check_claim(claim_ref, store)
                if state is None:
                    self._json(404, {"error": "not found"})
                else:
                    self._json(200, state)
                return
            self._json(404, {"error": "no such endpoint"})

        def do_POST(self):
            if self.path != "/events":
                self._json(404, {"error": "no such endpoint"})
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                event = json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError as exc:
                self._json(400, {"valid": False, "errors": [str(exc)]})
                return
            result = validate_event(event)
            if not result["valid"]:
                self._json(422, {"valid": False, "errors": result["errors"]})
                return
            append_event(event, store)
            self._json(200, {"valid": True, "event_id": event["event_id"]})

    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    sys.stderr.write("ocl serve %s:%s store=%s\n" % (args.bind, args.port, store))
    server.serve_forever()


def cmd_sync(args):
    spool = args.spool or DEFAULT_SPOOL
    if not os.path.exists(spool):
        print(json.dumps({"ok": True, "flushed": 0}))
        return
    events = read_events(spool)
    flushed = 0
    for event in events:
        result = deliver(event, args.store)
        if result == "spooled":
            break
        flushed += 1
    remaining = events[flushed:]
    with open(spool, "w", encoding="utf-8") as handle:
        for event in remaining:
            handle.write(json.dumps(event) + "\n")
    print(json.dumps({"ok": True, "flushed": flushed, "remaining": len(remaining)}))


def cmd_append(args):
    event = json.load(sys.stdin)
    result = validate_event(event)
    if not result["valid"]:
        for err in result["errors"]:
            sys.stderr.write("invalid event: %s: %s\n" % (err["path"], err["message"]))
        raise SystemExit(2)
    where = deliver(event, args.store)
    print(json.dumps({"ok": True, "event_id": event["event_id"], "stored": where}))


def parser():
    root = argparse.ArgumentParser(prog="ocl", description=__doc__.splitlines()[0])
    root.add_argument("--store", default=None, help="JSONL store path (env OCL_STORE)")
    sub = root.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("emit", help="append a claim.emitted event")
    p.add_argument("--text", required=True)
    p.add_argument("--type", required=True, choices=["factual", "calculation", "inference", "recommendation", "prediction"])
    p.add_argument("--claim-id", default=None)
    p.add_argument("--asserted-at", default=None)
    p.add_argument("--derived-from", nargs="*", default=None)
    p.add_argument("--source-uri", default=None)
    p.add_argument("--source-digest", default=None)
    p.add_argument("--selector", default=None)
    p.add_argument("--support-type", default="provenance_only",
                   choices=["supports_directly", "supports_partially", "computed_from", "contradicts", "context_only", "provenance_only"])
    p.add_argument("--facet", default=None, help="name=path.json")
    p.set_defaults(func=cmd_emit)

    p = sub.add_parser("verify", help="append a claim.verified event")
    p.add_argument("claim_ref")
    p.add_argument("--result", required=True, choices=["supported", "contradicted", "inconclusive"])
    p.add_argument("--method", required=True, choices=["human_review", "model_check", "source_attestation", "consensus", "formal_proof"])
    p.add_argument("--validator-id", default="urn:agent:openfox-verifier")
    p.add_argument("--validator-type", default="pipeline")
    p.add_argument("--validator-name", default=None)
    p.add_argument("--confidence", type=float, default=None)
    p.add_argument("--evidence-uri", default=None)
    p.add_argument("--evidence-digest", default=None)
    p.add_argument("--selector", default=None)
    p.add_argument("--tool-name", default=None)
    p.add_argument("--tool-type", default=None)
    p.add_argument("--tool-version", default=None)
    p.add_argument("--verified-at", default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("dispute", help="append a claim.disputed event")
    p.add_argument("claim_ref")
    p.add_argument("--rationale", default=None)
    p.add_argument("--evidence-uri", default=None)
    p.add_argument("--selector", default=None)
    p.add_argument("--contradicts", default=None, help="text of the contradicting claim being emitted alongside")
    p.add_argument("--contradicts-text", default=None)
    p.set_defaults(func=cmd_dispute)

    p = sub.add_parser("retract", help="append a claim.retracted event")
    p.add_argument("claim_ref")
    p.add_argument("--retracted-at", default=None)
    p.set_defaults(func=cmd_retract)

    p = sub.add_parser("check", help="current state of a claim (replay)")
    p.add_argument("claim_ref")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("query", help="list claims with status/method/source tags")
    p.add_argument("--status", default=None, choices=["active", "disputed", "retracted", "asserted"])
    p.add_argument("--method", default=None)
    p.add_argument("--text", default=None)
    p.add_argument("--cite", const="short", nargs="?", choices=["short", "full"], default=None,
                   help="render citation lines (C7 injection discipline)")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("chain", help="verify digests + hash chain")
    p.add_argument("--verify", action="store_true")
    p.set_defaults(func=cmd_chain)

    p = sub.add_parser("conform", help="run conformance against vendored fixtures")
    p.add_argument("fixtures_dir", nargs="?", default=None)
    p.set_defaults(func=cmd_conform)

    p = sub.add_parser("serve", help="minimal HTTP ledger API (C6)")
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("OCL_PORT", 8500)))
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("sync", help="flush offline spool to remote ledger")
    p.add_argument("--spool", default=None)
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("append", help="append a raw event from stdin JSON")
    p.set_defaults(func=cmd_append)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.store is None:
        args.store = DEFAULT_STORE
    args.func(args)


if __name__ == "__main__":
    main()
