"""codec: the single owner of every mem byte format (ADR-0004/0005).

Formats owned here:
  - page frontmatter (stamp lineage: mem-wiki@1 base; mem-wiki@2 adds
    optional bitemporal claim attrs valid_at/invalid_at, ADR-0011)
  - claim lines + edge bullets (schema vocabulary lives in schema.py)
  - raw source frontmatter
  - events.jsonl lines
  - index.yaml (mini-YAML subset)

Files are stamped with FMT on creation. Pre-v1 files (no stamp) parse
unchanged; `mem migrate` produces stamped successor files and archives
the pre-migration bytes under migrations/<ts>/ (no silent in-place
rewrites of history — AGENTS.md rule 4).
"""

import datetime
import json
import re

from . import schema

FMT = "mem-wiki@2"

_FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_CLAIM_RE = schema._CLAIM_RE
_EDGE_RE = schema._EDGE_RE
_INDEX_ITEM_RE = re.compile(r"^  (\w+): (.*)$")


# --- frontmatter ---------------------------------------------------------

def split_frontmatter(text):
    """-> (front_dict|None, body). Pre-v1 (no block) -> (None, text)."""
    m = _FM_RE.match(text)
    if not m:
        return None, text
    front = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            front[k.strip()] = schema.yaml_scalar(v.strip())
    return front, text[m.end():]


def _fm_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def build_frontmatter(front):
    lines = ["---"]
    for k, v in front.items():
        lines.append("%s: %s" % (k, _fm_scalar(v)))
    lines.append("---")
    return "\n".join(lines) + "\n"


def page_frontmatter(title, today=None):
    today = today or datetime.date.today().isoformat()
    return build_frontmatter({"title": title, "format": FMT, "type": "entity",
                              "tags": [], "created": today,
                              "updated": today})


def stamp_page(text, today=None):
    """Return stamped text for a pre-v1 page (frontmatter gains format)."""
    front, body = split_frontmatter(text)
    if front is None:
        front = {}
        leading = ""
    else:
        leading = body
    front.setdefault("title", "untitled")
    ordered = {"title": front.pop("title")}
    ordered["format"] = FMT
    for k, v in front.items():
        if k not in ordered:
            ordered[k] = v
    ordered.setdefault("type", "entity")
    ordered.setdefault("tags", [])
    today = today or datetime.date.today().isoformat()
    ordered.setdefault("created", today)
    ordered["updated"] = today
    head = build_frontmatter(ordered)
    if leading.startswith("\n"):
        return head + leading
    return head + "\n" + leading.lstrip("\n") if leading else head


def bump_updated(text, today=None):
    today = today or datetime.date.today().isoformat()
    return re.sub(r"^updated: .*$", "updated: %s" % today, text, count=1,
                  flags=re.MULTILINE)


# --- raw source frontmatter ----------------------------------------------

def raw_frontmatter(url, fetched_at, content_hash, origin=None,
                    kind=None, producer=None, session_id=None):
    origin = origin or url
    fm = {"origin": origin, "format": FMT}
    if url and (url.startswith("http://") or url.startswith("https://")):
        fm["url"] = url
    fm["retrieved_at"] = fetched_at
    fm["content_hash"] = content_hash
    if kind:
        fm["kind"] = kind
    if producer:
        fm["producer"] = producer
    if session_id:
        fm["session_id"] = session_id
    return build_frontmatter(fm)


# --- claim lines + edge bullets -------------------------------------------

def format_claim(claim):
    attrs = ["id: %s" % (claim.get("id") or schema.new_id(claim["text"])),
             "pred: %s" % claim.get("pred", "other"),
             "status: %s" % claim["status"],
             "confidence: %.2f" % claim["confidence"],
             "date: %s" % claim["date"]]
    for k in ("valid_at", "invalid_at", "revalidate_at"):
        if claim.get(k):
            attrs.append("%s: %s" % (k, claim[k]))
    text = "%s {%s}" % (claim["text"], ", ".join(attrs))
    lines = ["- %s" % text]
    for edge in claim["edges"]:
        lines.append("  %s::[[%s]]" % (edge["type"], edge["target"]))
    return "\n".join(lines)


def parse_claim(line, edge_lines):
    m = _CLAIM_RE.match(line)
    if not m:
        raise ValueError("malformed claim line: %r" % line)
    text, raw_attrs = m.group(1), m.group(2)
    claim = {"text": text, "edges": []}
    for part in raw_attrs.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k, v = k.strip(), v.strip()
        if k == "confidence":
            claim["confidence"] = float(v)
        elif k == "pred":
            if v not in schema.PREDICATES:
                raise ValueError("unknown predicate: %s" % v)
            claim["pred"] = v
        elif k == "id":
            claim["id"] = v
        elif k == "status":
            if v not in schema.STATUSES:
                raise ValueError("unknown status: %s" % v)
            claim["status"] = v
        elif k == "date":
            claim["date"] = v
        elif k in ("valid_at", "invalid_at", "revalidate_at"):
            try:
                datetime.date.fromisoformat(v)
            except ValueError:
                raise ValueError("claim %s not ISO: %r" % (k, line))
            claim[k] = v
    for req in ("id", "status", "confidence", "date"):
        if req not in claim:
            raise ValueError("claim missing attr %s: %r" % (req, line))
    for eline in edge_lines:
        em = _EDGE_RE.match(eline)
        if not em:
            raise ValueError("malformed edge line: %r" % eline)
        etype, target = em.group(1), em.group(2)
        if etype not in schema.EDGES:
            raise ValueError("unknown edge type: %s" % etype)
        claim["edges"].append({"type": etype, "target": target})
    return claim


def is_claim_line(line):
    return line.startswith("- ") and "{id:" in line


def is_edge_line(line):
    return bool(_EDGE_RE.match(line))


_ATTR_BLOCK_RE = re.compile(r"\{([^{}]*)\}\s*$")


def set_claim_attr(line, key, value):
    """Set `key: value` inside the attribute block of a claim bullet
    line (replace if present, append otherwise). Used by
    supersede-by-invalidation to stamp invalid_at in place."""
    m = _ATTR_BLOCK_RE.search(line)
    if not m:
        raise ValueError("no attribute block: %r" % line)
    attrs = m.group(1)
    rx = re.compile(r"(?<![a-z_])%s: [^,}]*" % key)
    if rx.search(attrs):
        attrs = rx.sub("%s: %s" % (key, value), attrs)
    else:
        attrs = (attrs + ", %s: %s" % (key, value)).lstrip(", ")
    return line[:m.start()] + "{%s}" % attrs


def stamp_insert(text, fmt=None):
    """Insert the format stamp into an existing frontmatter block (or
    create a minimal one for pages). Idempotent. Rebuilds the block via
    build_frontmatter; body bytes are preserved untouched."""
    fmt = fmt or FMT
    front, body = split_frontmatter(text)
    if front is None:
        title = "untitled"
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return page_frontmatter(title) + body.lstrip("\n")
    if front.get("format") == fmt:
        return text
    ordered, inserted = {}, False
    for k, v in front.items():
        if k == "format":
            ordered[k] = fmt
            inserted = True
        else:
            ordered[k] = v
    if not inserted:
        ordered["format"] = fmt
    return build_frontmatter(ordered) + body


# --- events.jsonl ---------------------------------------------------------

def encode_event(event):
    event.setdefault("fmt", FMT)
    event.setdefault("ts", datetime.datetime.now(
        datetime.timezone.utc).isoformat(timespec="seconds"))
    return json.dumps(event, sort_keys=True)


def decode_event(line):
    if not line.strip():
        return None
    return json.loads(line)


def read_jsonl(text):
    """Parse JSONL the way an append-only log must be read after a
    possible crash mid-append: well-formed lines are returned; a torn
    trailing line is REPORTED (returned in `torn`), never silently
    accepted or fatal. Callers surface the count — corruption is
    declared, not asserted away (AGENTS.md rule 2 in the filesystem)."""
    records, torn = [], []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            torn.append({"line": n, "text": line[:120]})
    return records, torn


# --- index.yaml (mini-YAML subset) ----------------------------------------

def dump_index(entries):
    out = []
    for e in entries:
        out.append("- file: %s" % e["file"])
        out.append("  summary: %s" % schema.yaml_quote(e["summary"]))
        out.append("  tags: %s" % schema.yaml_quote(e["tags"]))
        out.append("  updated: %s" % schema.yaml_quote(e["updated"]))
        out.append("  claim_count: %d" % e["claim_count"])
        out.append("  unverified_count: %d" % e["unverified_count"])
    return "\n".join(out) + "\n"


def load_index(text):
    entries, cur = [], None
    for line in text.splitlines():
        if line.startswith("- "):
            cur = {}
            entries.append(cur)
            m = re.match(r"- (\w+): (.*)$", line)
            if m:
                cur[m.group(1)] = schema.yaml_scalar(m.group(2))
        elif line.startswith("  ") and cur is not None:
            m = _INDEX_ITEM_RE.match(line)
            if m:
                cur[m.group(1)] = schema.yaml_scalar(m.group(2))
    return entries
