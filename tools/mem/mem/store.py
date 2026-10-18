"""File I/O: pages, raw sources, events, locking, git auto-commit."""

import datetime
import fcntl
import hashlib
import os
import re
import signal
import subprocess
import threading
import time
import uuid

from . import codec, schema


class Store:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        for d in ("raw", "wiki/entities", "wiki/topics", "procedural"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self._local = threading.local()

    # --- locking (single writer) ---

    def acquire(self):
        path = os.path.join(self.root, ".lock")
        f = open(path, "a+")
        fcntl.flock(f, fcntl.LOCK_EX)
        self._local.f = f

    def release(self):
        f = getattr(self._local, "f", None)
        if f:
            fcntl.flock(f, fcntl.LOCK_UN)
            f.close()
            self._local.f = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()

    # --- paths ---

    def path(self, rel):
        p = os.path.normpath(os.path.join(self.root, rel))
        if not p.startswith(self.root + os.sep) and p != self.root:
            raise ValueError("path escape: %s" % rel)
        return p

    def exists(self, rel):
        return os.path.exists(self.path(rel))

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as f:
            return f.read()

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        self._sweep_stale_tmp(p)
        # tmp name must be unique per PROCESS too: two processes' main
        # threads share a thread ident, and a colliding tmp name means
        # one writer's os.replace deletes the other's pending tmp
        # (found by tests/test_concurrency.py, FAILURES F-10).
        tmp = "%s.%d-%d-%s.tmp" % (p, os.getpid(),
                                   threading.get_ident(),
                                   uuid.uuid4().hex[:8])
        # Crash hooks (test-only, see tests/test_concurrency.py): kill -9
        # between tmp write and rename to prove the atomic-rename contract
        # — the final file is either the old bytes or the new bytes, never
        # a torn mix, because os.replace is atomic on local filesystems.
        crash = os.environ.get("MEM_CRASH_POINT")
        with open(tmp, "w", encoding="utf-8") as f:
            if crash == "mid-tmp":
                f.write(text[: max(1, len(text) // 2)])
                f.flush()
                os.kill(os.getpid(), signal.SIGKILL)
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            if crash == "pre-rename":
                os.kill(os.getpid(), signal.SIGKILL)
        os.replace(tmp, p)

    STALE_TMP_SECONDS = 3600

    def _sweep_stale_tmp(self, p):
        """Crash orphans from the F-10 process-unique tmp naming carry
        pid+thread+random suffixes, so no later writer ever reuses one
        name — without a sweep they accumulate forever (review #11).
        Delete *stale* orphan temps for this target file: same basename
        prefix, .tmp suffix, older than STALE_TMP_SECONDS. Young ones
        may belong to a live concurrent writer, so they are left alone."""
        d, base = os.path.split(p)
        prefix = base + "."
        try:
            names = os.listdir(d)
        except OSError:
            return
        now = time.time()
        for name in names:
            if not (name.startswith(prefix) and name.endswith(".tmp")):
                continue
            fp = os.path.join(d, name)
            try:
                if now - os.path.getmtime(fp) > self.STALE_TMP_SECONDS:
                    os.remove(fp)
            except OSError:
                pass

    def list_rel(self, subdir, exts=(".md",)):
        """Store-relative POSIX paths under subdir, recursive, sorted
        (dirs and names): the single directory-walk implementation
        (review #14, FAILURES F-10 lesson — five callers had hand-rolled
        `os.path.join(root, n)[len(store.root)+1:]` copies). Missing
        subdir returns [] instead of raising."""
        base = self.path(subdir)
        out = []
        if not os.path.isdir(base):
            return out
        for root, dirs, names in os.walk(base):
            dirs.sort()
            for n in sorted(names):
                if n.endswith(exts):
                    rel = os.path.relpath(os.path.join(root, n),
                                          self.root)
                    out.append(rel.replace(os.sep, "/"))
        return out

    # --- raw sources ---

    def raw_hash_exists(self, content_hash):
        rawdir = os.path.join(self.root, "raw")
        for name in sorted(os.listdir(rawdir)):
            if not name.endswith(".md"):
                continue
            text = self.read("raw/" + name)
            m = re.search(r"content_hash: (\w+)", text[:2000])
            if m and m.group(1) == content_hash:
                return "raw/" + name
        return None

    def write_raw(self, url, text, fetched_at, kind=None, producer=None,
                  session_id=None):
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        dup = self.raw_hash_exists(content_hash)
        if dup:
            return dup, True
        origin = url
        host = re.sub(r"[^a-z0-9.-]+", "-",
                      re.sub(r"^https?://", "", origin).split("/")[0]
                      if origin.startswith("http") else
                      os.path.basename(origin.rstrip("/")) or "stdin")\
            .strip("-")
        slug = schema.slugify(origin.split("//")[-1].split("/", 1)[-1]
                             if "//" in origin else origin)[:60] or "doc"
        rel = "raw/%s_%s_%s.md" % (fetched_at, host or "local", slug)
        fm = codec.raw_frontmatter(url if origin.startswith("http")
                                   else "", fetched_at, content_hash,
                                   origin=origin, kind=kind,
                                   producer=producer,
                                   session_id=session_id)
        self.write(rel, fm + text + "\n")
        return rel, False

    # --- pages ---

    def page_for_subject(self, subject):
        rel = "wiki/entities/%s.md" % schema.slugify(subject)
        self.ensure_page(rel, title=subject)
        return rel

    def ensure_page(self, rel, title=None):
        if not self.exists(rel):
            if not title:
                title = os.path.splitext(os.path.basename(rel))[0]
            self.write(rel, codec.page_frontmatter(title) + "\n# %s\n"
                       % title)
        return rel

    def remove_if_empty(self, rel):
        if not self.exists(rel):
            return
        _, _, claims = self.parse_page(rel)
        if not claims:
            os.remove(self.path(rel))

    def parse_page(self, rel):
        text = self.read(rel)
        front, body = codec.split_frontmatter(text)
        front = front or {}
        claims, bullets = [], []
        current = None
        for line in body.splitlines():
            if codec.is_claim_line(line):
                bullets.append(("claim", line))
                current = len(bullets) - 1
            elif current is not None and codec.is_edge_line(line):
                bullets.append(("edge", line))
            elif line.startswith("- "):
                bullets.append(("other", line))
                current = None
        i = 0
        while i < len(bullets):
            kind, line = bullets[i]
            if kind == "claim":
                edges = []
                j = i + 1
                while j < len(bullets) and bullets[j][0] == "edge":
                    edges.append(bullets[j][1])
                    j += 1
                claims.append(schema.parse_claim_block(line, edges))
                i = j
            else:
                i += 1
        return front, body, claims

    def append_claim(self, rel, claim):
        text = self.read(rel)
        block = "\n" + schema.format_claim(claim) + "\n"
        if not text.endswith("\n"):
            text += "\n"
        text = text + block
        text = _bump_updated(text)
        self.write(rel, text)

    def mutate_claim(self, rel, claim_id, *, add_status=None, add_edge=None,
                     set_attrs=None):
        text = self.read(rel)
        lines = text.splitlines()
        out, i, found = [], 0, False
        while i < len(lines):
            line = lines[i]
            if line.startswith("- ") and ("id: %s" % claim_id) in line:
                block = [line]
                j = i + 1
                while j < len(lines) and _edge_line(lines[j]):
                    block.append(lines[j])
                    j += 1
                if add_status:
                    block[0] = re.sub(r"status: \w+", "status: " + add_status,
                                      block[0])
                for k, v in (set_attrs or {}).items():
                    block[0] = codec.set_claim_attr(block[0], k, v)
                if add_edge:
                    edge = "  %s::[[%s]]" % (add_edge["type"],
                                             add_edge["target"])
                    if edge not in block:
                        block.append(edge)
                out.extend(block)
                found = True
                i = j
            else:
                out.append(line)
                i += 1
        if not found:
            raise KeyError("claim not found: %s" % claim_id)
        text = "\n".join(out) + ("\n" if text.endswith("\n") else "")
        text = _bump_updated(text)
        self.write(rel, text)

    def all_pages(self):
        pages = []
        for base in ("wiki/entities", "wiki/topics"):
            d = os.path.join(self.root, base)
            for name in sorted(os.listdir(d)):
                if name.endswith(".md"):
                    pages.append("%s/%s" % (base, name))
        return pages

    # --- events (append-only log of every state transition) ---

    def append_event(self, event):
        # One buffered line + fsync per append (G-G4): O_APPEND makes
        # concurrent appends interleave-safe on a local filesystem, and
        # the single write keeps a SIGKILL tear to at most the trailing
        # line. Readers (codec.read_jsonl) REPORT torn lines and
        # reconcile turns them into audit findings — torn tails are
        # declared, never silently accepted.
        line = codec.encode_event(event) + "\n"
        with open(self.path("events.jsonl"), "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    # --- git backstop ---

    def git_commit(self, message):
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           cwd=self.root, capture_output=True, text=True)
        if r.returncode != 0:
            return False
        subprocess.run(["git", "add", "-A", "."], cwd=self.root,
                       capture_output=True)
        r = subprocess.run(["git", "commit", "-m", message], cwd=self.root,
                           capture_output=True, text=True)
        return r.returncode == 0


def _edge_line(line):
    return codec.is_edge_line(line)


def _bump_updated(text):
    return codec.bump_updated(text)
