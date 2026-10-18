#!/usr/bin/env python3
"""Compare verify-bench outputs against benchmarks/expected_results.json.

Usage: python3 scripts/compare_expected.py EVAL_JSON [PRUNE_JSON]
       EXPECTED_JSON [--skip-prune] [--update]

EVAL_JSON is the raw `{stamp, report}` document printed by `mem eval`.
--update rewrites EXPECTED_JSON from the actual outputs (regeneration
flow for verify-bench.sh --update) instead of gating on them.
Exit 0 = PASS (or written), 1 = FAIL (drift printed as a diff table).
"""

import json
import platform
import sys


def check_numbers(expected, actual, tol, path, failures):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            failures.append("%s: expected object, got %r" % (path, actual))
            return
        for k, v in expected.items():
            if k in ("tolerance", "requires", "note", "suite", "seed"):
                continue
            if k not in actual:
                failures.append("%s.%s: missing" % (path, k))
                continue
            check_numbers(v, actual[k], tol, "%s.%s" % (path, k), failures)
    elif isinstance(expected, bool):
        if expected != actual:
            failures.append("%s: %r != %r" % (path, actual, expected))
    elif isinstance(expected, (int, float)):
        if actual is None or abs(actual - expected) > tol:
            failures.append("%s: %r vs expected %r (tol %s)"
                            % (path, actual, expected, tol))
    else:
        if expected != actual:
            failures.append("%s: %r != %r" % (path, actual, expected))


def build_expected(old, report, psummary):
    modes = {}
    for m, v in report.get("modes", {}).items():
        spec = {"mrr": v["mrr"], "p_at_1": v["p_at_1"], "n": v["n"],
                "mean_grade": v["mean_grade"]}
        toks = {t: x.get("tokens_per_query")
                for t, x in v.get("per_type", {}).items() if x.get("n")}
        if toks:
            spec["tokens"] = toks
        modes[m] = spec
    old_me = old.get("mem_eval", {})
    me = {"queryset_sha": report.get("queryset_sha"),
          "seed": old_me.get("seed", 42),
          "modes": modes,
          "adversarial": {
              "guardrail": report.get("adversarial", {}).get("guardrail")},
          "tolerance": old_me.get("tolerance", 0.01)}
    out = {"note": old.get(
        "note",
        "Expected outputs for scripts/verify-bench.sh; regenerate with "
        "scripts/verify-bench.sh --update."),
        "mem_eval": me}
    pg = dict(old.get("prune_gate_vision", {}))
    if psummary:
        pg["images"] = psummary.get("images")
        pg["scored"] = psummary.get("scored")
        rm = psummary.get("recall_mean")
        if rm is not None:
            pg["recall_mean_min"] = round(max(0.0, rm - 0.1), 2)
        pg.setdefault("suite", "synthetic")
        pg.setdefault("requires",
                      "macOS + swiftc (Vision framework); skipped elsewhere")
        out["prune_gate_vision"] = pg
    elif "prune_gate_vision" in old:
        out["prune_gate_vision"] = pg
    return out


def main(argv):
    skip_prune = "--skip-prune" in argv
    update = "--update" in argv
    argv = [a for a in argv if a not in ("--skip-prune", "--update")]
    eval_path = argv[0]
    prune_path = None
    exp_path = argv[-1]
    if len(argv) == 3:
        prune_path = argv[1]
    with open(exp_path, encoding="utf-8") as fh:
        expected = json.load(fh)
    with open(eval_path, encoding="utf-8") as fh:
        report = json.load(fh)["report"]

    if update:
        psummary = None
        if prune_path:
            with open(prune_path, encoding="utf-8") as fh:
                psummary = json.load(fh)["summary"]
        new = build_expected(expected, report, psummary)
        with open(exp_path, "w", encoding="utf-8") as fh:
            json.dump(new, fh, indent=2)
            fh.write("\n")
        print("updated %s from measured outputs (python %s | %s/%s)"
              % (exp_path, platform.python_version(),
                 platform.system(), platform.machine()))
        return 0

    me = expected["mem_eval"]
    tol = me.get("tolerance", 0.01)
    failures = []
    if report.get("queryset_sha") != me["queryset_sha"]:
        failures.append("mem_eval.queryset_sha: %r != %r (queryset drift)"
                        % (report.get("queryset_sha"), me["queryset_sha"]))
    modes = json.loads(json.dumps(me["modes"]))
    for m, spec in modes.items():
        flat = spec.pop("tokens", None)
        if flat:
            spec.setdefault("per_type", {})
            for t, v in flat.items():
                spec["per_type"].setdefault(t, {})["tokens_per_query"] = v
    check_numbers(modes, report["modes"], tol, "mem_eval.modes", failures)
    check_numbers(me["adversarial"], report.get("adversarial", {}), tol,
                  "mem_eval.adversarial", failures)

    pg = expected.get("prune_gate_vision")
    prune_status = "skipped"
    psummary = None
    if pg and not skip_prune and prune_path:
        with open(prune_path, encoding="utf-8") as fh:
            psummary = json.load(fh)["summary"]
        prune_status = "run"
        if psummary.get("images") != pg["images"]:
            failures.append("prune.images: %r != %r"
                            % (psummary.get("images"), pg["images"]))
        if psummary.get("scored") != pg["scored"]:
            failures.append("prune.scored: %r != %r"
                            % (psummary.get("scored"), pg["scored"]))
        rm = psummary.get("recall_mean")
        if rm is None or rm < pg["recall_mean_min"] - 0.001:
            failures.append("prune.recall_mean: %r < min %r"
                            % (rm, pg["recall_mean_min"]))
    elif pg and not skip_prune and not prune_path:
        prune_status = "skipped (no PRUNE_JSON supplied)"

    print("env: python %s | %s/%s" % (platform.python_version(),
                                      platform.system(),
                                      platform.machine()))
    print("mem_eval: %s (n=%d)"
          % ("ok" if not any(f.startswith("mem_eval") for f in failures)
             else "FAIL", report["modes"].get("baseline", {}).get("n", 0)))
    print("prune_gate: %s" % prune_status)
    if failures:
        for f in failures:
            print("DRIFT %s" % f)
        print("verify-bench FAIL (%d drifts)" % len(failures),
              file=sys.stderr)
        return 1
    print("verify-bench PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
