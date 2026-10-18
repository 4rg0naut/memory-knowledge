"""rules-as-data: declarative hygiene gates with layered composition (ADR-0008).

Layer order (later wins, merged by rule name):
  1. rules/base.yaml            (shipped defaults)
  2. rules/host-<hostname>.yaml (host profile, optional)
  3. rules/patch.yml            (one personal patch, optional)
MEM_RULES_DIR overrides the directory searched (only that dir is used,
its base.yaml + host/patch layers are then resolved inside it).

`mem rules list` prints the effective set including the file each
value came from (provenance). No code edit is needed to disable a gate.
"""

import os
import socket

LAYER_NAMES = ("base.yaml", "host-%s.yaml", "patch.yml")

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "rules")


def rules_dir():
    return os.environ.get("MEM_RULES_DIR") or DEFAULT_DIR


def _scalar(raw):
    raw = raw.strip()
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw.strip('"')


def parse_rules_yaml(text):
    """Parse the controlled rules-file subset -> list of rule dicts."""
    rules, cur, in_params = [], None, False
    base_indent = 0
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if "#" in raw else raw.rstrip()
        if not line.strip():
            in_params = False
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if indent == 0:
            in_params = False
            continue
        if stripped.startswith("- "):
            cur = {"params": {}}
            rules.append(cur)
            in_params = False
            base_indent = indent
            stripped = stripped[2:]
            k, _, v = stripped.partition(":")
            cur[k.strip()] = _scalar(v)
            continue
        if cur is None:
            continue
        k, _, v = stripped.partition(":")
        k, v = k.strip(), v.strip()
        if indent > base_indent and in_params:
            cur["params"][k] = _scalar(v)
        elif v == "":
            in_params = k == "params"
            if k == "params":
                cur.setdefault("params", {})
        else:
            in_params = False
            cur[k] = _scalar(v)
    return rules


def _host_name():
    return socket.gethostname().split(".")[0]


def load_layers(directory=None):
    directory = directory or rules_dir()
    files = [LAYER_NAMES[0], LAYER_NAMES[1] % _host_name(),
             LAYER_NAMES[2]]
    layers = []
    for fname in files:
        path = os.path.join(directory, fname)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                layers.append((fname, parse_rules_yaml(f.read())))
    return layers


def effective(directory=None):
    """Merge layers by rule name (later wins); add provenance per rule."""
    out = {}
    for fname, rules in load_layers(directory):
        for r in rules:
            if "name" not in r:
                continue
            entry = {"name": r["name"],
                     "enabled": bool(r.get("enabled", True)),
                     "params": r.get("params", {}),
                     "provenance": fname}
            if r["name"] in out and entry["enabled"] != out[r["name"]]["enabled"]:
                entry["overrode"] = "%s:%s" % (out[r["name"]]["provenance"],
                                               "enabled=%s" % out[
                                                   r["name"]]["enabled"])
            out[r["name"]] = entry
    return list(out.values())


# --- checks (dispatcher by rule name) -------------------------------------

def _derived_from_required(claim, params, ctx):
    if not any(e["type"] == "derived_from" for e in claim.get("edges", [])):
        return "anonymous claim: derived_from::[[...]] required"


def _pred_required(claim, params, ctx):
    if "pred" not in claim:
        return "missing pred attribute"


def _text_nonempty(claim, params, ctx):
    if not claim.get("text", "").strip():
        return "empty claim text"


def _no_agent_verified(claim, params, ctx):
    if claim.get("status") == "verified":
        return "agents cannot write status: verified (use /verify)"


def _inference_cap(claim, params, ctx):
    from . import schema
    if schema.is_inference(claim):
        cap = float(params.get("cap", schema.INFERENCE_CAP))
        conf = claim.get("confidence", 0)
        if conf > cap:
            return ("inference confidence %.2f exceeds cap %.2f"
                    % (conf, cap))


def _quote_match(claim, params, ctx):
    raw = ctx.get("raw_text")
    quote = ctx.get("source_quote")
    if raw is None or quote is None:
        if params.get("require_quote", False):
            return "source_quote required by quote_match rule"
        return None
    if quote not in raw:
        return "source_quote not found in raw (hallucination gate)"


CHECKS = {
    "derived_from_required": _derived_from_required,
    "pred_required": _pred_required,
    "text_nonempty": _text_nonempty,
    "no_agent_verified": _no_agent_verified,
    "inference_cap": _inference_cap,
    "quote_match": _quote_match,
}


def enforce(claim, ctx=None, directory=None, at_ingest=True):
    """Run enabled rules over a claim -> list of rejection reasons."""
    ctx = ctx or {}
    reasons = []
    for r in effective(directory):
        if not r["enabled"]:
            continue
        check = CHECKS.get(r["name"])
        if check is None:
            reasons.append("unknown rule: %s" % r["name"])
            continue
        if r["name"] == "no_agent_verified" and not at_ingest:
            continue
        reason = check(claim, r["params"], ctx)
        if reason:
            reasons.append(reason)
    return reasons
