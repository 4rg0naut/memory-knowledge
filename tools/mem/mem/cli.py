"""CLI: python -m mem <command>. One entry point, zero deps."""

import argparse
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

from . import (chunking, daily, distill, evalkit, extract, graph as
               graphmod, hygiene, index, providers, readpath, schema,
               sources, temporal)
from .store import Store

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 3))


def _iso_date(value):
    """argparse type for every user-supplied date (G-G4 review #9):
    unvalidated strings silently lexicographic-compare their way to
    plausible-looking wrong answers (`mem asof hello` -> empty set);
    reject non-ISO at the door with a usage error instead."""
    try:
        return datetime.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "not an ISO date (YYYY-MM-DD): %r" % value)


def home():
    return os.environ.get("MEM_HOME", os.path.join(REPO, "memory"))


def _fetch(url):  # compat alias
    return sources._fetch_url(url)


def _strip_html(text):  # compat alias
    return sources.strip_html(text)


def _ingest(store, source, *, kind=None, force=False, provider=None,
            claims=None, dump_prompt=False, ollama_url=None, model=None,
            stdin=None, opener=None, producer=None, session_id=None):
    """Shared ingest pipeline: resolve source -> raw+lineage -> provider
    extract (quote-gated) -> hygiene -> index -> git backstop."""
    producer = producer or os.environ.get("OPENFOX_AGENT", "human")
    session_id = session_id or os.environ.get("OPENFOX_SESSION_ID")
    rkind, raw_text, lin = sources.resolve(source, kind=kind,
                                           opener=opener, stdin=stdin,
                                           producer=producer,
                                           session_id=session_id)
    provider = provider or None
    if dump_prompt:
        p = providers.get_provider(provider)
        print(providers.system_for(sources.prompt_kind(rkind))
              + "\n---\n" + providers.build_prompt(raw_text,
                                                  sources.prompt_kind(
                                                      rkind)))
        return 0, {"raw": None, "stored": [], "warnings": [],
                   "prompt_kind": sources.prompt_kind(rkind)}
    today = datetime.date.today().isoformat()
    raw_rel, dup = store.write_raw(lin["origin"], raw_text, today,
                                   kind=rkind,
                                   producer=lin.get("producer"),
                                   session_id=lin.get("session_id"))
    if dup and not force:
        return 0, {"skipped": "duplicate", "raw": raw_rel}
    ctx = {"candidates": claims, "raw_text": raw_text}
    extracted, warnings = extract.extract(
        raw_text, url=ollama_url, model=model, kind=sources.prompt_kind(
            rkind), provider=provider, ctx=ctx, opener=None)
    results = []
    for c in extracted:
        page = store.page_for_subject(c["subject"])
        text = "%s %s: %s" % (c["subject"], c["pred"], c["value"])
        claim = {
            "text": text,
            "pred": c["pred"],
            "status": "unverified",
            "confidence": c["confidence"],
            "date": today,
            "edges": [{"type": "derived_from", "target": raw_rel}],
        }
        try:
            r = hygiene.ingest(store, page, claim,
                               source_quote=c["source_quote"],
                               raw_rel=raw_rel)
            r["page"] = page
            results.append(r)
        except ValueError as e:
            store.remove_if_empty(page)
            warnings.append("rejected: %s" % e)
    entries = index.rebuild(store)
    store.git_commit("mem: ingest %s (%d claims)" % (source,
                                                      len(results)))
    return 0, {"raw": raw_rel, "stored": results, "warnings": warnings,
               "kind": rkind, "lineage": lin,
               "index_pages": len(entries)}


def cmd_scrape(args, store):
    claims = None
    if getattr(args, "claims", None):
        claims = providers.load_claims_arg(args.claims)
    code, out = _ingest(store, args.source,
                        kind=getattr(args, "kind", None),
                        force=args.force,
                        provider=getattr(args, "provider", None),
                        claims=claims,
                        dump_prompt=getattr(args, "dump_prompt", False),
                        producer=getattr(args, "producer", None),
                        session_id=getattr(args, "session_id", None))
    print(json.dumps(out, indent=2))
    return code


def cmd_query(args, store):
    hits = index.route(store, args.text)
    out = []
    for e in hits:
        _, _, claims = store.parse_page(e["file"])
        ranked = index.rank_claims(claims, args.text)[: args.top_k]
        out.append({"page": e["file"], "summary": e["summary"],
                    "claims": [{"id": c["id"], "text": c["text"],
                                "status": c["status"],
                                "quote_ref": (schema.claim_edges(
                                    c, "derived_from") or [None])[0],
                                "effective": round(
                                    schema.effective_confidence(
                                        c, datetime.date.today()), 3)}
                               for _, c in ranked if c["status"] !=
                               "retracted"]})
    print(json.dumps(out, indent=2))
    return 0


def cmd_show(args, store):
    front, body, claims = store.parse_page(args.page)
    today = datetime.date.today()
    print(store.read(args.page))
    print("\n# computed effective confidence")
    for c in claims:
        eff = schema.effective_confidence(c, today)
        flag = " [STALE-FLAG]" if (eff < schema.FLAG_THRESHOLD
                                   and c["status"] != "retracted") else ""
        print("%s  %-12s %.3f%s  %s" % (c["id"], c["status"], eff, flag,
                                        c["text"][:60]))
    return 0


def cmd_lint(args, store):
    issues = hygiene.lint(store)
    print(json.dumps(issues, indent=2))
    return 1 if issues else 0


def cmd_stale(args, store):
    print(json.dumps(hygiene.stale_report(store), indent=2))
    return 0


def cmd_contradictions(args, store):
    print(json.dumps(hygiene.contradictions(store), indent=2))
    return 0


def cmd_orphans(args, store):
    print(json.dumps(hygiene.orphans(store), indent=2))
    return 0


def cmd_verify(args, store):
    hygiene.verify(store, args.page, args.claim, args.source,
                   actor=args.actor)
    store.git_commit("mem: verify %s" % args.claim)
    print(json.dumps({"ok": True, "claim": args.claim, "status":
                      "verified"}))
    return 0


def cmd_retract(args, store):
    hygiene.retract(store, args.page, args.claim, args.reason)
    store.git_commit("mem: retract %s" % args.claim)
    print(json.dumps({"ok": True, "claim": args.claim, "status":
                      "retracted"}))
    return 0


def cmd_index(args, store):
    entries = index.rebuild(store)
    print(json.dumps({"pages": len(entries)}))
    return 0


def cmd_audit(args, store):
    _, _, claims = store.parse_page(args.page)
    target = next((c for c in claims if c["id"] == args.claim), None)
    if not target:
        print("claim not found", file=sys.stderr)
        return 1
    chain = [e for e in hygiene._events(store)
             if e.get("claim") == args.claim]
    print(json.dumps({"claim": target, "events": chain}, indent=2))
    return 0


def cmd_serve(args, store):
    from .server import serve
    serve(store, port=args.port, listen=args.listen,
          write_port=args.write_port, write_listen=args.write_listen)
    return 0


# --- experiment kernel (ADR-0011): S1-S5 + E1/E2 --------------------------

def cmd_distill(args, store):
    if args.source:
        if not store.exists(args.source):
            print(json.dumps({"error": "no such raw source: %s"
                                   % args.source}))
            return 2
        rels = [args.source]
    else:
        rels = store.list_rel("raw")
    stats = [distill.distill_raw(store, r) for r in rels]
    overall_src = sum(s["source_tokens"] for s in stats)
    overall_dis = sum(s["distilled_tokens"] for s in stats)
    out = {"per_raw": stats,
           "objects": sum(s["objects"] for s in stats),
           "rejected": sum(s["rejected"] for s in stats),
           "skipped_short": sum(s["skipped_short"] for s in stats),
           "source_tokens": overall_src, "distilled_tokens": overall_dis,
           "compression": (round(overall_src / overall_dis, 2)
                           if overall_dis else None),
           "min_vocab_retention": min([s["vocab_retention"] for s in stats],
                                      default=1.0)}
    if any(s["objects"] for s in stats):
        store.git_commit("mem: distill %d objects" % out["objects"])
    print(json.dumps(out, indent=2))
    return 0


def cmd_daily(args, store):
    created = daily.build_daily(store, today=args.date)
    store.git_commit("mem: daily cards %d" % len(created))
    print(json.dumps({"created": created}, indent=2))
    return 0


def cmd_consolidate(args, store):
    units = daily.consolidate(store, window_days=args.window,
                              max_units=args.max_units)
    index.rebuild(store)
    store.git_commit("mem: consolidate %d units" % len(units))
    print(json.dumps({"units": units}, indent=2))
    return 0


def cmd_graph(args, store):
    if args.build:
        n = graphmod.build(store)
        store.git_commit("mem: graph build %d edges" % n)
        print(json.dumps({"edges": n, "rel": graphmod.GRAPH_REL},
                         indent=2))
        return 0
    hits = graphmod.expand(args.query or "", store, asof=args.asof)
    out = {"entities": len(hits),
           "sample": dict(list(sorted(
               hits.items(), key=lambda t: t[1]["distance"]))[:8])}
    if not store.exists(graphmod.GRAPH_REL):
        out["hint"] = ("graph view not built — zero hits means no edges "
                       "exist yet, not no matches; run: mem graph --build")
    print(json.dumps(out, indent=2))
    return 0


def cmd_recall(args, store):
    out = readpath.recall(store, args.text, mode=args.mode,
                          k=args.top_k, budget=args.budget,
                          asof=args.asof)
    print(json.dumps(out, indent=2))
    return 0


def cmd_asof(args, store):
    rows = [{"page": p, "id": c["id"], "text": c["text"][:90],
             "status": c["status"], "date": c["date"],
             "valid_at": c.get("valid_at"),
             "invalid_at": c.get("invalid_at")}
            for p, c in temporal.active_claims(store, args.date)]
    print(json.dumps({"as_of": args.date, "active": rows}, indent=2))
    return 0


def cmd_eval(args, store):
    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
    bad = [m for m in modes if m not in evalkit.MODES]
    if bad:
        print(json.dumps({"error": "unknown mode(s): %s (valid: %s)"
                               % (", ".join(bad), ", ".join(evalkit.MODES))}))
        return 2
    if args.bootstrap:
        qs = evalkit.build_queryset(store, n=args.n, seed=args.seed)
        evalkit.save_queryset(store, qs)
    st = evalkit.stamp(store)
    if args.rotations > 1:
        rot = evalkit.run_rotation(
            store, seeds=[args.seed + i for i in range(args.rotations)],
            modes=modes, budget=args.budget)
        out = {"stamp": st, "rotation": rot}
        if args.emit and "error" not in rot:
            out["claim"] = evalkit.emit_claim(store, {
                "ts": rot["ts"], "budget": rot["budget"],
                "modes": rot["modes"],
                "graph_decision": rot["graph_decision"]})
        store.git_commit("mem: eval rotation %s (%d seeds)" % (
            ",".join(str(s) for s in rot.get("seeds", [])),
            len(rot.get("seeds", []))))
        print(json.dumps(out, indent=2))
        return 0 if "error" not in rot else 1
    report = evalkit.run(store, modes=modes, budget=args.budget,
                         seed=args.seed)
    out = {"stamp": st, "report": report}
    if args.emit and "error" not in report:
        out["claim"] = evalkit.emit_claim(store, report)
    store.git_commit("mem: eval %s" % report.get("queryset_sha", "-"))
    print(json.dumps(out, indent=2))
    return 0 if "error" not in report else 1


def cmd_evidence(args, store):
    rows = []
    for page in store.all_pages():
        _, _, claims = store.parse_page(page)
        for c in claims:
            status, detail = hygiene.evidence_status(store, c)
            rows.append({"page": page, "claim": c["id"],
                         "quote_era": hygiene.quote_era(store, c),
                         "evidence": status, "detail": detail[:100]})
    print(json.dumps(rows, indent=2))
    return 0


def cmd_modelcheck(args, store):
    out = hygiene.model_check(store, args.page, args.claim)
    store.git_commit("mem: model_check %s" % args.claim)
    print(json.dumps(out, indent=2))
    return 0


def cmd_reconcile(args, store):
    report = hygiene.reconcile(store)
    store.git_commit("mem: reconcile %d problems" % len(
        report["problems"]))
    print(json.dumps(report, indent=2))
    return 1 if report["problems"] or report["unindexed_pages"] else 0


def cmd_migrate(args, store):
    from . import migrate
    result = migrate.apply(store, dry=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


def cmd_rules(args, store):
    if args.rules_cmd == "list":
        print(json.dumps({"dir": rules.rules_dir(),
                          "layers": [f for f, _ in
                                     rules.load_layers()],
                          "effective": rules.effective()}, indent=2))
        return 0
    print("unknown rules subcommand", file=sys.stderr)
    return 2


def build_parser():
    p = argparse.ArgumentParser(prog="mem")
    p.add_argument("--home", default=None, help="memory root (env MEM_HOME)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scrape", aliases=["ingest"],
                       help="ingest any source: url, file, dir, stdin "
                            "(-), session log")
    s.add_argument("source", help="url | path | dir | -")
    s.add_argument("--force", action="store_true",
                   help="re-extract even if raw already stored")
    s.add_argument("--kind", choices=["url", "file", "dir", "stdin",
                                      "session"], default=None)
    s.add_argument("--provider", default=None,
                   help="ollama | openai-compatible | manual "
                        "(default: $MEM_PROVIDER or ollama)")
    s.add_argument("--claims", default=None,
                   help="manual provider: JSON file or - for stdin")
    s.add_argument("--dump-prompt", action="store_true",
                   help="print the extraction prompt, do not call")
    s.add_argument("--producer", default=None,
                   help="who captured this (default $OPENFOX_AGENT)")
    s.add_argument("--session-id", default=None,
                   help="session id for lineage (default "
                        "$OPENFOX_SESSION_ID)")
    s.set_defaults(fn=cmd_scrape)
    s = sub.add_parser("query")
    s.add_argument("text")
    s.add_argument("--top-k", type=int, default=5)
    s.set_defaults(fn=cmd_query)
    s = sub.add_parser("show")
    s.add_argument("page")
    s.set_defaults(fn=cmd_show)
    sub.add_parser("lint").set_defaults(fn=cmd_lint)
    sub.add_parser("stale").set_defaults(fn=cmd_stale)
    sub.add_parser("contradictions").set_defaults(fn=cmd_contradictions)
    sub.add_parser("orphans").set_defaults(fn=cmd_orphans)
    s = sub.add_parser("verify")
    s.add_argument("page")
    s.add_argument("claim")
    s.add_argument("source")
    s.add_argument("--actor", default="human")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("retract")
    s.add_argument("page")
    s.add_argument("claim")
    s.add_argument("--reason", default="")
    s.set_defaults(fn=cmd_retract)
    sub.add_parser("index").set_defaults(fn=cmd_index)
    s = sub.add_parser("audit")
    s.add_argument("page")
    s.add_argument("claim")
    s.set_defaults(fn=cmd_audit)
    s = sub.add_parser("migrate", help="stamp files to the current format (mem-wiki@2)")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(fn=cmd_migrate)
    s = sub.add_parser("rules")
    rs = s.add_subparsers(dest="rules_cmd", required=True)
    rs.add_parser("list").set_defaults(rules_action=True)
    s.set_defaults(fn=cmd_rules)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int,
                   default=int(os.environ.get("MEM_PORT", "8520")))
    s.add_argument("--listen", default=os.environ.get("MEM_LISTEN",
                                                      "127.0.0.1"))
    s.add_argument("--write-port", type=int,
                   default=int(os.environ.get("MEM_WRITE_PORT", "0")),
                   help="also listen for writes on this port; when set, "
                        "--listen port becomes read-only (GET only)")
    s.add_argument("--write-listen",
                   default=os.environ.get("MEM_WRITE_LISTEN", "0.0.0.0"))
    s.set_defaults(fn=cmd_serve)
    # --- experiment kernel (ADR-0011) ---
    s = sub.add_parser("distill", help="distill exchanges into compound "
                       "objects (literal-appearance verified)")
    s.add_argument("--source", default=None, help="raw/<file>.md (default: "
                                                  "all raw)")
    s.set_defaults(fn=cmd_distill)
    s = sub.add_parser("daily", help="build daily/ workbench cards from "
                       "uncarded raw sources")
    s.add_argument("--date", default=None, type=_iso_date,
                   help="ISO date YYYY-MM-DD (default: today)")
    s.set_defaults(fn=cmd_daily)
    s = sub.add_parser("consolidate", help="promote up to N recent distilled "
                       "units into digest claims (quote-gated)")
    s.add_argument("--window", type=int, default=2)
    s.add_argument("--max-units", type=int, default=5)
    s.set_defaults(fn=cmd_consolidate)
    s = sub.add_parser("graph", help="entity graph with bitemporal edges "
                       "(--build to rebuild; query for hops)")
    s.add_argument("--build", action="store_true")
    s.add_argument("query", nargs="?", default=None)
    s.add_argument("--asof", default=None, type=_iso_date,
                   help="ISO date YYYY-MM-DD (bitemporal filter)")
    s.set_defaults(fn=cmd_graph)
    s = sub.add_parser("recall", help="hybrid read path (FTS5 + vectors + "
                       "CombMNZ fusion + token-budget packer)")
    s.add_argument("text")
    s.add_argument("--mode", default="fused",
                   choices=["baseline", "distilled", "fused", "graph"])
    s.add_argument("--top-k", type=int, default=8)
    s.add_argument("--budget", type=int, default=600,
                   help="token budget for the packed context")
    s.add_argument("--asof", default=None, type=_iso_date,
                   help="ISO date YYYY-MM-DD (bitemporal filter)")
    s.set_defaults(fn=cmd_recall)
    s = sub.add_parser("asof", help="claims believed active on a date")
    s.add_argument("date", type=_iso_date,
                   help="ISO date YYYY-MM-DD")
    s.set_defaults(fn=cmd_asof)
    s = sub.add_parser("eval", help="recall harness with tokens-per-query "
                       "and bootstrap CIs; protocol-stamped; --emit -> "
                       "ledger claim")
    s.add_argument("--bootstrap", action="store_true",
                   help="derive queryset from corpus first")
    s.add_argument("--n", type=int, default=200)
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--rotations", type=int, default=1,
                   help="run the harness across N seed-rotated querysets; "
                        "reports pooled CIs + per-seed variance")
    s.add_argument("--budget", type=int, default=600)
    s.add_argument("--modes",
                   default="baseline,distilled,fused,graph")
    s.add_argument("--emit", action="store_true",
                   help="emit headline claim via ocl (rule 6)")
    s.set_defaults(fn=cmd_eval)
    s = sub.add_parser("evidence", help="evidence_status per claim "
                       "(ok|stale|unlocatable)")
    s.set_defaults(fn=cmd_evidence)
    s = sub.add_parser("modelcheck", help="machine verification (stamps "
                       "corroborated, never verified)")
    s.add_argument("page")
    s.add_argument("claim")
    s.set_defaults(fn=cmd_modelcheck)
    s = sub.add_parser("reconcile", help="standing audit -> "
                       "metadata/audit_report.json (exit 1 on problems)")
    s.set_defaults(fn=cmd_reconcile)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    store = Store(args.home or home())
    return args.fn(args, store)


if __name__ == "__main__":
    sys.exit(main())
