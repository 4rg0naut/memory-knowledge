#!/usr/bin/env python3
"""PII gate for the public snapshot (ADR-0013).

Scans the publishable tree for personal identifiers: operator username,
machine hostnames, tailnet name, private volume paths, LAN IPs, personal
e-mail domains, assistant name. Exit 1 on any hit, with file:line detail.

Modes:
  python3 scripts/check-pii.py                # git ls-files tree, minus
                                              # scripts/pii-excludes.txt
                                              # (the locally-tracked real
                                              # data replaced at publish)
  python3 scripts/check-pii.py --strict       # whole tree, no excludes
                                              # (what CI runs on the
                                              # published snapshot)
  python3 scripts/check-pii.py --root DIR     # scan an exported dir
                                              # (publish-snapshot.sh uses
                                              # this pre-push)

Text files only (extension allowlist); binaries (benchmark PNGs) are
reviewed by eye at scrub time and listed in the allowlist comment.
"""

import argparse
import os
import re
import subprocess
import sys

PATTERNS = [
    # NB: this file carries the pattern literals themselves and is
    # content-exempt (path scan still applies).
    ("operator-username", re.compile(r"\bchris\b|\bChris\b")),
    ("studio-host", re.compile(r"\bmsm5m\b")),
    ("mini-host", re.compile(r"\bmminim4\b|\bmmm4\b")),
    ("tailnet", re.compile(r"tailf7b38a")),
    ("private-volume", re.compile(r"/Volumes/DEV")),
    ("lan-ip", re.compile(r"\b192\.168\.\d+\.\d+\b")),
    ("cgnat-ip", re.compile(
        r"\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d+\.\d+\b")),
    ("personal-email", re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(home|local|lan)\b")),
    ("assistant-name", re.compile(r"\bLeo\b|leo-unreal")),
]

TEXT_EXT = {".py", ".md", ".json", ".jsonl", ".yaml", ".yml", ".txt",
            ".sh", ".plist", ".swift", ".toml", ".cfg", ".ini", ".license",
            ".gitignore", ".workflow.json"}
TEXT_NAMES = {"LICENSE", "Makefile", "NOTICE"}
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}

# Approved strings that would otherwise look personal (user decision
# 2026-10-18: public handle 4rg0naut + its domain are published identity).
ALLOWLIST = re.compile(r"4rg0naut(\.uk)?(/silicon-ledger)?")


def _excludes(root):
    path = os.path.join(root, "scripts", "pii-excludes.txt")
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return out


def _tracked(root):
    r = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return [f for f in r.stdout.split("\0") if f]


def _walk(root):
    files = []
    for dirpath, dirnames, names in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for n in names:
            rel = os.path.relpath(os.path.join(dirpath, n), root)
            files.append(rel)
    return files


def _is_text(rel):
    ext = os.path.splitext(rel)[1].lower()
    return ext in TEXT_EXT or os.path.basename(rel) in TEXT_NAMES


def _match_content(rel, path):
    hits = []
    try:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for name, rx in PATTERNS:
                    for m in rx.finditer(line):
                        span = line[max(0, m.start() - 30):m.end() + 30]
                        if ALLOWLIST.search(span):
                            continue
                        hits.append("%s:%d [%s] %s"
                                    % (rel, lineno, name, span.strip()))
    except UnicodeDecodeError:
        pass
    except OSError as exc:
        hits.append("%s:0 [unreadable] %s" % (rel, exc))
    return hits


def scan(root, strict=False):
    files = _tracked(root) if _tracked(root) is not None else _walk(root)
    if not strict:
        excl = _excludes(root)
        files = [f for f in files
                 if not any(f == e or f.startswith(e.rstrip("/") + "/")
                            for e in excl)]
    hits = []
    for rel in files:
        for name, rx in PATTERNS:
            if rx.search(rel):
                hits.append("%s (path) [%s]" % (rel, name))
        path = os.path.join(root, rel)
        if rel.endswith(os.path.join("scripts", "check-pii.py")):
            continue  # carries the pattern literals itself
        if os.path.exists(path) and _is_text(rel):
            hits.extend(_match_content(rel, path))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--strict", action="store_true",
                    help="ignore pii-excludes.txt (run on published tree)")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    hits = scan(root, strict=args.strict)
    if hits:
        for h in hits:
            print("PII-HIT %s" % h)
        print("check-pii FAIL: %d hit(s) in %s"
              % (len(hits), root), file=sys.stderr)
        return 1
    print("check-pii ok (%s%s)" % (root, ", strict" if args.strict else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
