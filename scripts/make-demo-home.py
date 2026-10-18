#!/usr/bin/env python3
"""Regenerate the sanitized demo memory home (ADR-0013 publish layer).

Builds demo/memory/ from demo/sources/* via the real mem pipeline
(scrape --provider manual, quote-gated; no model calls), so the demo is
honest about provenance: every claim line traces to a raw file that is
in the published tree.

Run from the repo root:
    tools/mem/.venv/bin/python scripts/make-demo-home.py

Output: demo/memory/ (raw/, wiki/, index.yaml, events.jsonl,
benchmarks/queryset.jsonl, metadata/). Filenames embed the checkout
path, so re-run after checking out elsewhere and commit the refresh.
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo")
BUILD = os.path.join(DEMO, ".build")
HOME = os.path.join(BUILD, "home")
MEM = [sys.executable, "-m", "mem"]

# Manual-provider candidates per source (subject, predicate, value,
# confidence, source_quote). Quotes are verbatim substrings of the raw
# files — the quote gate holds the generator honest.
CANDIDATES = {
    "harbor-fleet.md": [
        {"subject": "Harbor Robotics", "predicate": "hq",
         "value": "Rotterdam", "confidence": 0.95,
         "source_quote": "headquarters in Rotterdam, founded 2021."},
        {"subject": "R200 warehouse robot", "predicate": "uses_tech",
         "value": "Nimbus-9 SoC", "confidence": 0.95,
         "source_quote": "The R200 warehouse robot runs on the Nimbus-9 SoC."},
        {"subject": "R200 unified memory", "predicate": "other",
         "value": "128 GB across all production SKUs", "confidence": 0.9,
         "source_quote": "The R200 unified memory is 128 GB across all production SKUs,"
                         " per the hardware sheet."},
        {"subject": "fleet firmware", "predicate": "status_of",
         "value": "4.2.1 as of the October rollout", "confidence": 0.95,
         "source_quote": "Fleet firmware status_of: 4.2.1 as of the October rollout."},
        {"subject": "depot sync job", "predicate": "gotcha",
         "value": "rsync without --delete leaves orphaned files alive on the mirror",
         "confidence": 0.9,
         "source_quote": "The depot sync job has a known gotcha: rsync without"
                         " --delete leaves orphaned files from withdrawn rosters"
                         " alive on the mirror."},
        {"subject": "R200 pick arm", "predicate": "other",
         "value": "310 picks per hour under standard bin mix", "confidence": 0.85,
         "source_quote": "The R200 pick arm sustains 310 picks per hour under"
                         " the standard bin mix."},
    ],
    "harbor-financials.md": [
        {"subject": "Harbor Robotics", "predicate": "revenue",
         "value": "4.2M EUR FY2025", "confidence": 0.95,
         "source_quote": "Harbor Robotics reported FY2025 revenue of 4.2M EUR,"
                         " up 38% year over year."},
        {"subject": "Harbor Robotics", "predicate": "other",
         "value": "Series B of 30M EUR led by Delft Ventures", "confidence": 0.9,
         "source_quote": "The company closed a Series B of 30M EUR led by"
                         " Delft Ventures."},
        {"subject": "Harbor Robotics second office", "predicate": "located_in",
         "value": "Gdansk", "confidence": 0.9,
         "source_quote": "the company opened a second office in Gdansk for"
                         " firmware work."},
    ],
    "harbor-correction.md": [
        {"subject": "R200 unified memory", "predicate": "other",
         "value": "64 GB on all production SKUs", "confidence": 0.95,
         "source_quote": "The R200 unified memory is 64 GB on all production"
                         " SKUs; the 128 GB figure came from a pre-production"
                         " prototype datasheet, not from the shipping unit."},
    ],
    "harbor-standup-2026-10-15.md": [
        {"subject": "marketing deck", "predicate": "gotcha",
         "value": "R200 slide still shows the retired 128 GB figure",
         "confidence": 0.9,
         "source_quote": "the marketing deck still shows 128 GB on the R200 slide"},
        {"subject": "depot sync cron wrapper", "predicate": "gotcha",
         "value": "drops the delete flag in the cron migration, so withdrawn rosters resurrect on the mirror",
         "confidence": 0.9,
         "source_quote": "the rsync wrapper drops the delete flag somewhere in the cron migration"},
    ],
    "harbor-platforms.md": [
        {"subject": "R300 robot", "predicate": "uses_tech",
         "value": "Nimbus-12 SoC", "confidence": 0.95,
         "source_quote": "The R300 robot will use the Nimbus-12 SoC, which"
                         " pairs two dies for 128 GB unified memory."},
        {"subject": "Nimbus-12 SoC", "predicate": "other",
         "value": "128 GB unified memory via two paired dies", "confidence": 0.9,
         "source_quote": "The R300 robot will use the Nimbus-12 SoC, which"
                         " pairs two dies for 128 GB unified memory."},
        {"subject": "Harbor DevDay", "predicate": "published",
         "value": "Nimbus-12 design win announcement", "confidence": 0.9,
         "source_quote": "The Nimbus-12 design win was announced at the"
                         " Harbor DevDay."},
    ],
}

SOURCE_ORDER = ["harbor-fleet.md", "harbor-financials.md",
                "harbor-correction.md", "harbor-standup-2026-10-15.md",
                "harbor-platforms.md"]


def run(*args, check=True):
    env = dict(os.environ, MEM_HOME=HOME, OPENFOX_AGENT="demo-harness",
               OPENFOX_SESSION_ID="demo-publish",
               PYTHONPATH=os.path.join(ROOT, "tools", "mem"))
    print("+", " ".join(str(a) for a in args))
    r = subprocess.run(args, env=env, cwd=ROOT, capture_output=True,
                       text=True)
    if check and r.returncode != 0:
        print(r.stdout)
        print(r.stderr, file=sys.stderr)
        raise SystemExit("FAILED: %s (exit %d)" % (args[-3:], r.returncode))
    return r


def find_claim(page_rel, pred):
    import re
    path = os.path.join(HOME, page_rel)
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if ", pred: %s," % pred in line:
                m = re.search(r"\{id: (clm_[0-9a-f]+)", line)
                if m:
                    return m.group(1)
    raise SystemExit("claim with pred=%s not found in %s" % (pred, page_rel))


def build_knowledge_and_ledger():
    """Demo inbox capture + evidence snapshot + ocl ledger roundtrip
    (mirrors docs/roundtrip.md on invented Harbor content)."""
    kdir = os.path.join(DEMO, "knowledge")
    for sub in ("inbox", "evidence"):
        os.makedirs(os.path.join(kdir, sub), exist_ok=True)
    capture = os.path.join(kdir, "inbox", "harbor-devday-2026-10-16.md")
    with open(capture, "w", encoding="utf-8") as fh:
        fh.write(CAPTURE_MD)
    evidence = os.path.join(kdir, "evidence",
                            "harbor-devday-post-2026-10-16.json")
    with open(evidence, "w", encoding="utf-8") as fh:
        fh.write(EVIDENCE_JSON)
    import base64
    import hashlib
    digest = base64.urlsafe_b64encode(hashlib.sha256(
        EVIDENCE_JSON.encode("utf-8")).digest()).decode().rstrip("=")

    store = os.path.join(DEMO, "claims", "claims.jsonl")
    os.makedirs(os.path.dirname(store), exist_ok=True)
    if os.path.exists(store):
        os.remove(store)
    ocl = [sys.executable, os.path.join(ROOT, "tools", "ocl", "ocl.py")]
    uri = "file://knowledge/inbox/harbor-devday-2026-10-16.md"

    def oclcmd(*args, check=True):
        env = dict(os.environ)
        r = subprocess.run([*ocl, "--store", store, *args], env=env,
                           cwd=ROOT, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise SystemExit("ocl failed: %s\n%s" % (args, r.stderr))
        return r

    print(oclcmd("emit", "--text",
                 "Harbor Robotics unveiled the R300 robot at DevDay 2026.",
                 "--type", "factual", "--source-uri", uri,
                 "--asserted-at", "2026-10-16T09:00:00Z",
                 "--source-digest", digest,
                 "--selector", "uri_fragment:r300-unveil").stdout.strip())
    print(oclcmd("emit", "--text",
                 "The Nimbus-12 SoC pairs two dies for 128 GB unified "
                 "memory.", "--type", "factual", "--source-uri", uri,
                 "--asserted-at", "2026-10-16T09:01:00Z",
                 "--source-digest", digest,
                 "--selector", "uri_fragment:nimbus12-spec").stdout.strip())
    print(oclcmd("emit", "--text",
                 "The R300 cuts fleet cost up to 22% versus the R200 "
                 "baseline.", "--type", "inference", "--source-uri", uri,
                 "--asserted-at", "2026-10-16T09:02:00Z",
                 "--source-digest", digest,
                 "--selector", "uri_fragment:fleet-cost-claim").stdout.strip())
    print(oclcmd("emit", "--text",
                 "Harbor reported no operator overtime in Q3.",
                 "--type", "factual", "--source-uri", uri,
                 "--asserted-at", "2026-10-16T09:03:00Z",
                 "--source-digest", digest,
                 "--selector", "uri_fragment:overtime-claim").stdout.strip())
    out = {}
    ids = [json.loads(line)["claim"]["claim_id"]
           for line in open(store, encoding="utf-8")
           if json.loads(line)["event_type"] == "claim.emitted"]
    out["ids"] = ids
    print(oclcmd("verify", ids[0], "--result", "supported",
                 "--method", "source_attestation",
                 "--validator-id", "did:example:operator",
                 "--validator-type", "human",
                 "--evidence-uri", "file://knowledge/evidence/"
                 "harbor-devday-post-2026-10-16.json",
                 "--evidence-digest", digest).stdout.strip())
    print(oclcmd("dispute", ids[3],
                 "--rationale", "Q3 incident log lists two weekend runs; "
                 "the overtime claim is at odds with the log",
                 "--evidence-uri", "file://knowledge/evidence/"
                 "harbor-devday-post-2026-10-16.json").stdout.strip())
    r = oclcmd("check", ids[3])
    out["check_output"] = r.stdout.strip()
    print(r.stdout.strip())
    with open(os.path.join(DEMO, "claims-roundtrip-output.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)


CAPTURE_MD = """# Harbor DevDay capture (2026-10-16)

Manual capture of the Harbor Robotics DevDay post (paraphrase from the
live page; fidelity caveats apply, primary source digested separately).

Harbor Robotics unveiled the R300 robot at DevDay 2026.

The Nimbus-12 SoC pairs two dies for 128 GB unified memory.

Marketing claims fleet-cost savings of up to 22% versus the R200
baseline.

The post states there was no operator overtime in Q3.
"""

EVIDENCE_JSON = """{
 "url": "https://harborrobotics.example/devday-2026",
 "retrieved": "2026-10-16",
 "published": "2026-10-15",
 "r300": {"soc": "Nimbus-12", "memory": "128 GB unified",
          "dies": 2},
 "fleet_cost_claim": {"up_to_pct": 22, "baseline": "R200",
                      "self_reported": true},
 "overtime_claim": {"period": "Q3", "statement": "no operator overtime"}
}
"""


def main():
    if os.path.exists(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(HOME)
    run("git", "init", "-q", HOME)
    run("git", "-C", HOME, "config", "user.name", "demo-harness")
    run("git", "-C", HOME, "config", "user.email",
        "demo@example.invalid")

    raws = {}
    for name in SOURCE_ORDER:
        claims_file = os.path.join(BUILD, "claims-%s.json" % name)
        with open(claims_file, "w", encoding="utf-8") as fh:
            json.dump(CANDIDATES[name], fh, indent=1)
        r = run(sys.executable, *MEM[1:], "scrape",
                os.path.join("demo", "sources", name),
                "--kind", "file", "--provider", "manual",
                "--claims", claims_file, "--producer", "demo-harness")
        out = json.loads(r.stdout)
        raws[name] = out["raw"]
        for s in out["stored"]:
            print("  stored %s [%s] %s" % (s["id"], s.get("page", "?"),
                                           s.get("action", "?")))
            for g in s.get("guardrails", []) or []:
                print("  guardrail %s" % g)

    # Human verification on two lines (leave the rest at honest floor).
    run(sys.executable, *MEM[1:], "verify",
        "wiki/entities/harbor-robotics.md",
        find_claim(os.path.join("wiki", "entities", "harbor-robotics.md"),
                   "revenue"),
        raws["harbor-financials.md"], "--actor", "human")
    run(sys.executable, *MEM[1:], "verify",
        "wiki/entities/depot-sync-job.md",
        find_claim(os.path.join("wiki", "entities", "depot-sync-job.md"),
                   "gotcha"),
        raws["harbor-fleet.md"], "--actor", "human")

    run(sys.executable, *MEM[1:], "index")
    r = run(sys.executable, *MEM[1:], "distill", check=False)
    try:
        ds = json.loads(r.stdout)
        print("distill: %d objects, %d rejected, %d skipped_short"
              % (ds["objects"], ds["rejected"], ds["skipped_short"]))
    except (ValueError, KeyError):
        print("distill: unexpected output (exit %d)" % r.returncode)
    run(sys.executable, *MEM[1:], "graph", "--build")
    run(sys.executable, *MEM[1:], "eval", "--bootstrap", "--seed", "42")
    r = run(sys.executable, *MEM[1:], "reconcile", check=False)
    print("reconcile exit=%d" % r.returncode)
    run(sys.executable, *MEM[1:], "contradictions", check=False)
    run(sys.executable, *MEM[1:], "recall",
        "rsync delete flag depot mirror gotcha", check=False)

    out = os.path.join(DEMO, "memory")
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(HOME, out, ignore=shutil.ignore_patterns(".git"))
    build_knowledge_and_ledger()
    print("wrote %s (+ knowledge/, claims/)" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
