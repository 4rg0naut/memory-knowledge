"""sources: pluggable ingest adapters — the URL is no longer special.

Every adapter returns (kind, text, lineage) with identical lineage
keys: origin, retrieved_at, content_hash. Adapters:

  url      http(s) fetch (html stripped when detected)
  file     local file path
  dir      every .md/.txt under a directory
  stdin    '-' reads stdin
  session  chat/session transcript (kind hint from extension, a
           knowledge/inbox/* capture, or --kind session)

`mem ingest` is the generic entry point; `mem scrape <url>` stays as a
compat alias.
"""

import datetime
import hashlib
import os
import sys
import urllib.request

SESSION_HINTS = (".md", ".txt", ".jsonl")


def _now():
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def classify(source, kind=None):
    if kind:
        return kind
    if source == "-":
        return "stdin"
    if source.startswith("http://") or source.startswith("https://"):
        return "url"
    if os.path.isdir(source):
        return "dir"
    base = os.path.basename(source)
    if "inbox" in source or base.lower().startswith(
            ("ask-brave", "chat", "session")):
        return "session"
    return "file"


def strip_html(text):
    import html
    import re
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text)


def _fetch_url(url, opener=None):
    req = urllib.request.Request(
        url, headers={"User-Agent": "mem-scraper/0.1"})
    if opener:
        return opener(req)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def lineage(text, origin, producer=None, session_id=None):
    lin = {"origin": origin, "retrieved_at": _now(),
           "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if producer:
        lin["producer"] = producer
    if session_id:
        lin["session_id"] = session_id
    return lin


def resolve(source, kind=None, opener=None, stdin=None, producer=None,
            session_id=None):
    """-> (kind, text, lineage). One interface for every capture path."""
    kind = classify(source, kind)
    if kind == "url":
        text = _fetch_url(source, opener=opener)
        if "<html" in text[:2000].casefold() or "<!doctype" in \
                text[:200].casefold():
            text = strip_html(text)
    elif kind == "stdin":
        text = (sys.stdin if stdin is None else stdin).read()
    elif kind == "dir":
        parts = []
        for name in sorted(os.listdir(source)):
            if name.endswith((".md", ".txt")):
                with open(os.path.join(source, name),
                          encoding="utf-8") as f:
                    parts.append("## %s\n\n%s" % (name, f.read()))
        text = "\n".join(parts)
    else:  # file | session share the byte-read path
        with open(source, encoding="utf-8") as f:
            text = f.read()
    return kind, text, lineage(text, source, producer=producer,
                               session_id=session_id)


def prompt_kind(kind):
    """Which extraction prompt family a source kind gets (T4 adds the
    incident prompt; web facts is the base family)."""
    return "session" if kind == "session" else "web"
