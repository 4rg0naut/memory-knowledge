"""migrate: stamp files to the current format (DSH successor pattern, ADR-0004; v2 adds bitemporal attrs, ADR-0011).

Pre-migration bytes are never lost: each touched file is archived under
migrations/<ts>/<rel> before the stamped successor takes its path.
events.jsonl is append-only and never rewritten — old lines simply lack
the fmt field and parse fine (tolerance floor).
"""

import datetime
import os

from . import codec, index


def _candidates(store):
    rels = list(store.all_pages())
    for base in ("raw", "procedural"):
        d = store.path(base)
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.endswith(".md"):
                    rels.append("%s/%s" % (base, name))
    return rels


def plan(store):
    """Files lacking the current format stamp."""
    out = []
    for rel in _candidates(store):
        try:
            text = store.read(rel)
        except OSError:
            continue
        front, _ = codec.split_frontmatter(text)
        if (front or {}).get("format") != codec.FMT:
            out.append(rel)
    return out


def apply(store, dry=False):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")
    todo = plan(store)
    total = len(_candidates(store))
    migrated = []
    for rel in todo:
        text = store.read(rel)
        stamped = codec.stamp_insert(text)
        archive = "migrations/%s/%s" % (ts, rel)
        if not dry:
            store.write(archive, text)
            store.write(rel, stamped)
            store.append_event({"event": "migrate", "rel": rel,
                                "from": "pre-v1", "to": codec.FMT,
                                "archive": archive})
        migrated.append({"rel": rel, "archive": archive})
    if migrated and not dry:
        index.rebuild(store)
        store.git_commit("mem: migrate %d files to %s (%s)"
                         % (len(migrated), codec.FMT, ts))
    return {"dry_run": dry, "format": codec.FMT,
            "migrated": migrated, "already_stamped": total - len(todo)}
