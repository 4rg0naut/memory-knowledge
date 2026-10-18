"""Claim line format, predicate vocabulary, status machine, mini-YAML."""

import hashlib
import re
import unicodedata

PREDICATES = [
    "founded", "hq", "revenue", "employees", "uses_model", "makes",
    "owns", "located_in", "partner_of", "pricing", "status_of",
    "uses_tech", "published", "incident", "decision", "gotcha",
    "other",
]

EDGES = ["derived_from", "corroborated_by", "contradicts", "superseded_by",
         "relates_to"]

STATUSES = ["unverified", "corroborated", "verified", "contradicted",
            "retracted", "guardrail", "superseded"]

STATUS_WEIGHT = {
    "unverified": 0.5,
    "corroborated": 0.75,
    "verified": 1.0,
    "contradicted": 0.1,
    "retracted": 0.0,
    "guardrail": 0.95,
    "superseded": 0.2,
}

INFERENCE_SOURCE = "agent-inference"
INFERENCE_CAP = 0.8
STALE_THRESHOLD = 0.3
FLAG_THRESHOLD = 0.2

_ATTR_RE = re.compile(r"\{([^}]*)\}")
_EDGE_RE = re.compile(r"^\s+([a-z_]+)::\[\[([^\]]+)\]\]\s*$")
_CLAIM_RE = re.compile(r"^- (.+?) \{(.*)\}\s*$")


def new_id(text):
    return "clm_" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def norm(value):
    v = unicodedata.normalize("NFKD", str(value)).casefold().strip()
    return re.sub(r"\s+", " ", v)


def slugify(text):
    s = unicodedata.normalize("NFKD", str(text)).casefold()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "misc"


def effective_confidence(claim, today):
    """confidence x status_weight x temporal_decay; age in days from claim date."""
    import datetime
    d = datetime.date.fromisoformat(claim["date"])
    age = max(0, (today - d).days)
    decay = 1.0 / (1.0 + age * 0.01)
    return claim["confidence"] * STATUS_WEIGHT[claim["status"]] * decay


def format_claim(claim):
    """Delegates to codec (single format owner, ADR-0004)."""
    from . import codec
    return codec.format_claim(claim)


def parse_claim_block(bullet_line, edge_lines):
    from . import codec
    return codec.parse_claim(bullet_line, edge_lines)


def claim_edges(claim, etype):
    return [e["target"] for e in claim["edges"] if e["type"] == etype]


def is_inference(claim):
    return INFERENCE_SOURCE in claim_edges(claim, "derived_from")


# --- mini-YAML: emit/parse ONLY the controlled index.yaml shape ---------

_INDEX_ITEM_RE = re.compile(r"^  (\w+): (.*)$")


def yaml_quote(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, list):
        return "[" + ", ".join(yaml_quote(v) for v in value) + "]"
    s = str(value)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_scalar(raw):
    raw = raw.strip()
    if raw.startswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [yaml_scalar(p.strip()) for p in inner.split(", ")]
    if raw in ("true", "false"):
        return raw == "true"
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def dump_index(entries):
    from . import codec
    return codec.dump_index(entries)


def load_index(text):
    from . import codec
    return codec.load_index(text)
