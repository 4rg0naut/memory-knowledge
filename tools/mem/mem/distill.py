"""S1: distilled exchange layer (ADR-0011).

Port of structured distillation (arXiv 2603.13017) to the mem store:
an exchange is one user turn plus the substantive agent response; a
compound object is exchange_core + specific_context + room_assignments
+ regex-extracted files_touched, always back-referencing the verbatim
source span. The raw file is never mutated; distilled text is routing
index only — recall surfaces the original.

Surviving vocabulary is enforced mechanically (silicon-ledger's
extract/verify split): files_touched is regex, specific_context is
kept verbatim, and verify_distill() rejects any value that does not
literally appear in its source. The exchange_core may compress, but
every long token in it must still exist in the source.
Offline and deterministic by default; no LLM required.
"""

import datetime
import hashlib
import json
import re

from . import chunking

_FILE_RE = re.compile(
    r"(?:/[A-Za-z0-9._-]+){2,}"
    r"|[A-Za-z0-9_./-]+\.(?:md|py|json|jsonl|ya?ml|toml|sh|ts|tsx|js"
    r"|swift|[ch]|rs|csv|txt|plist|env|conf|log)\b")
_TURN_RE = re.compile(r"^turn\s+\d+\b", re.I)
_SPEAKER_RE = re.compile(r"^(user|human|assistant|agent)\b", re.I)
_TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]{2,}")
_ID_RE = re.compile(r"\b[a-z][a-z0-9]*[_-][a-z0-9_-]+\b|[A-Z]{2,}\w*")
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9]*(?:[ _-][A-Z][A-Za-z0-9]*)?\b")
_WORKFLOW_WORDS = ("build", "audit", "ingest", "migrate", "test", "deploy",
                   "query", "index", "fix", "verify", "reconcile", "sync",
                   "port", "benchmark", "distill", "recall")
MIN_EXCHANGE_CHARS = 100
# Below this, an exchange is not worth distilling: a 1-sentence core +
# one identifier line cannot undercut 1/8th of a short payload without
# inventing structure. Measured on the own corpus: floor 500 keeps
# compression at ~15x corpus-level (8-11x is the bar); short captures
# stay fully served by the verbatim FTS layer unchanged.
DISTILL_MIN_CHARS = 500
CORE_MAX = 100
CONTEXT_MAX = 140
FILES_MAX = 6


def estimate_tokens(text):
    return max(1, int(round(len(text) / 4.0)))


_STOP_ENTITIES = {"The", "This", "That", "These", "Those", "There",
                  "Then", "They", "What", "When", "Where", "Which"}


def segment_exchanges(text):
    """Session transcript -> [{'text','start_line','end_line'}].

    Boundaries: `turn N` markers (inbox session exports) or speaker
    prefixes at line start. No markers -> blank-line runs, runs longer
    than 15 lines subdivided at 15 so nothing is dropped. Exchanges
    shorter than 100 chars are trivial-skipped."""
    lines = text.split("\n")
    n = len(lines)
    starts = [i for i, l in enumerate(lines)
              if _TURN_RE.match(l) or _SPEAKER_RE.match(l)]
    segs = []
    if starts:
        for k, s in enumerate(starts):
            e = starts[k + 1] if k + 1 < len(starts) else n
            segs.append((s, e))
    else:
        i = 0
        while i < n:
            if not lines[i].strip():
                i += 1
                continue
            j = i
            while j < n and lines[j].strip():
                j += 1
            s = i
            while j - s > 15:
                segs.append((s, s + 15))
                s += 15
            segs.append((s, j))
            i = j
    out = []
    for a, b in segs:
        body = "\n".join(lines[a:b]).strip()
        if len(body) >= MIN_EXCHANGE_CHARS:
            out.append({"text": body, "start_line": a + 1, "end_line": b})
    return out


def extract_files(text):
    return sorted(set(m.group(0) for m in _FILE_RE.finditer(text)))


def extract_entities(text):
    """Identifiers worth graph nodes: snake/dotted ids, acronyms,
    capitalized multi-word names, filenames."""
    out = set()
    for m in _ID_RE.finditer(text):
        out.add(m.group(0))
    for m in _ENTITY_RE.finditer(text):
        tok = m.group(0).strip(" .-")
        if len(tok) > 2 and tok not in _STOP_ENTITIES:
            out.add(tok)
    out.update(extract_files(text))
    return sorted(out)


def _cut_word(text, limit):
    """Truncate at a word boundary; a mid-word cut would invent a
    token that verify_distill cannot find in the source."""
    if len(text) <= limit:
        return text
    idx = text.rfind(" ", 0, limit + 1)
    if idx <= 0:
        idx = text.find(" ", limit)
    return text[:idx] if idx != -1 else text


def distill_exchange(exchange, source_rel, today=None):
    """One exchange -> compound object with back-reference.

    exchange_core: leading sentence(s) minus the turn marker (may
    compress, <= CORE_MAX); specific_context: the most identifier-dense
    line verbatim, trimmed to a verbatim identifier-dense substring
    when too long (<= CONTEXT_MAX); room_assignments: <=3
    (file/concept/workflow); files_touched: regex (<= FILES_MAX),
    never generated."""
    today = today or datetime.date.today().isoformat()
    text = exchange["text"]
    first = re.sub(_TURN_RE, "", text.split("\n")[0]).strip()
    sentences = re.split(r"(?<=[.!?])\s+", first)
    core = _cut_word(" ".join(sentences[:2]).strip(), CORE_MAX)
    best, best_score = "", -1
    for line in text.split("\n"):
        s = (3 * len(_ID_RE.findall(line))
             + 2 * len(_FILE_RE.findall(line))
             + len(re.findall(r"[`\"']|=\d|\d+\.\d", line)))
        if s > best_score and line.strip():
            best, best_score = line.strip(), s
    context = best or core
    if len(context) > CONTEXT_MAX:
        dense = ""
        for m in re.finditer(
                r"[A-Za-z0-9_.-]*(?:[_.-][A-Za-z0-9_.-]+)+"
                r"|\b[a-z][a-z0-9]+(?:ed|ing|s|er)\b", context):
            span = m.group(0)
            while len(span) > CONTEXT_MAX and " " in span:
                span = span[:span.rfind(" ")]
            if len(span) <= CONTEXT_MAX and len(span) > len(dense):
                dense = span
        context = dense or _cut_word(context, CONTEXT_MAX)
    rooms = []
    files = extract_files(text)[:FILES_MAX]
    if files:
        d = files[0].rsplit("/", 1)[0] or "/"
        rooms.append({"type": "file", "key": d.strip("/") or "/",
                      "label": d.strip("/") or "/"})
    entities = [e for e in extract_entities(text) if e not in files]
    if entities:
        rooms.append({"type": "concept", "key": entities[0].lower(),
                      "label": entities[0]})
    low = text.casefold()
    for w in _WORKFLOW_WORDS:
        if re.search(r"\b" + w, low):
            rooms.append({"type": "workflow", "key": w, "label": w})
            break
    idem = hashlib.sha256(
        ("%s#%d" % (source_rel, exchange["start_line"])).encode()).hexdigest()
    return {
        "id": "dst_" + idem[:12],
        "date": today,
        "source": {"file": source_rel, "start_line": exchange["start_line"],
                   "end_line": exchange["end_line"]},
        "exchange_core": core,
        "specific_context": context,
        "room_assignments": rooms[:3],
        "files_touched": files,
        "tokens_source": estimate_tokens(text),
        "tokens_distilled": estimate_tokens(core + " " + context),
    }


def verify_distill(obj, source_text):
    """Literal-appearance gate (S5). [] = clean.

    files_touched and specific_context must appear verbatim; every
    long token (>5 chars) of exchange_core must exist in the source
    (surviving vocabulary — compression allowed, invention not)."""
    violations = []
    if obj["specific_context"] and obj["specific_context"] not in source_text:
        violations.append("specific_context not verbatim in source")
    for f in obj["files_touched"]:
        if f not in source_text:
            violations.append("file not in source: %s" % f)
    src_tokens = set(t.casefold() for t in _TOKEN_RE.findall(source_text))
    for tok in _TOKEN_RE.findall(obj["exchange_core"]):
        if len(tok) > 5 and tok.casefold() not in src_tokens:
            violations.append("core token invented: %s" % tok)
    return violations


def vocab_retention(obj, source_text):
    """Fraction of query-like tokens (len>5 or identifiers) in the
    distilled text that survive in the source."""
    src = set(t.casefold() for t in _TOKEN_RE.findall(source_text))
    wanted = [t for t in _TOKEN_RE.findall(
        obj["exchange_core"] + " " + " ".join(
            r["key"] for r in obj["room_assignments"]) + " "
        + " ".join(obj["files_touched"]))
        if len(t) > 5 or _ID_RE.fullmatch(t)]
    if not wanted:
        return 1.0
    kept = sum(1 for t in wanted if t.casefold() in src)
    return kept / len(wanted)


def load_distilled(store):
    """Derived view (ADR-0012 torn-line policy): torn/damaged lines are
    dropped and recorded via an event, never fatal — `mem distill`
    regenerates from raw, which stays the source of truth."""
    from . import codec
    rel = "distill/exchanges.jsonl"
    if not store.exists(rel):
        return []
    objects, torn = codec.read_jsonl(store.read(rel))
    if torn:
        store.append_event({"event": "exchanges_view_torn_lines",
                            "dropped": len(torn),
                            "lines": [t["line"] for t in torn]})
    return objects


def distill_raw(store, rel, today=None):
    """Segment + distill + verify one raw file; appends clean objects
    to distill/exchanges.jsonl. Raw bytes untouched (S1). Returns
    stats dict."""
    text = store.read(rel)
    _, body = _split_raw_body(text)
    existing = {o["id"] for o in load_distilled(store)}
    objects, rejected, too_short = [], [], 0
    ts_before = hashlib.sha256(text.encode()).hexdigest()
    for exch in segment_exchanges(body):
        if len(exch["text"]) < DISTILL_MIN_CHARS:
            too_short += 1
            continue
        obj = distill_exchange(exch, rel, today)
        violations = verify_distill(obj, body)
        if violations:
            rejected.append({"id": obj["id"], "violations": violations})
            continue
        if obj["id"] in existing:
            continue
        objects.append(obj)
    if objects:
        lines = [store.read("distill/exchanges.jsonl")
                 if store.exists("distill/exchanges.jsonl") else ""]
        lines += [json.dumps(o, sort_keys=True) + "\n" for o in objects]
        store.write("distill/exchanges.jsonl", "".join(lines))
        store.append_event({"event": "distill", "raw": rel,
                            "objects": len(objects),
                            "rejected": len(rejected)})
    assert hashlib.sha256(store.read(rel).encode()).hexdigest() == ts_before
    src_total = sum(o["tokens_source"] for o in objects)
    dis_total = sum(o["tokens_distilled"] for o in objects)
    ret = ([vocab_retention(o, body) for o in objects] or [1.0])
    ratios = sorted(o["tokens_source"] / o["tokens_distilled"]
                    for o in objects) if objects else []
    return {"raw": rel, "objects": len(objects),
            "rejected": len(rejected),
            "rejected_detail": rejected,
            "skipped_short": too_short,
            "source_tokens": src_total, "distilled_tokens": dis_total,
            "compression": (round(src_total / dis_total, 2)
                            if dis_total else None),
            "median_object_ratio": (round(ratios[len(ratios) // 2], 2)
                                    if ratios else None),
            "min_object_ratio": round(ratios[0], 2) if ratios else None,
            "vocab_retention": round(sum(ret) / len(ret), 4)}


def _split_raw_body(text):
    from . import codec
    front, body = codec.split_frontmatter(text)
    return front or {}, body
