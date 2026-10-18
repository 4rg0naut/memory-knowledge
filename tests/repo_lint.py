#!/usr/bin/env python3
"""Repo-discipline lint: mem behavior changes need a CHANGELOG entry or ADR ref.

Rule (task T1 / ADR-0001 discipline): a commit that touches tools/mem/mem/*.py
(behavior code) must either touch CHANGELOG.md / docs/adr/ in the same commit,
or cite an ADR (``ADR-NNNN``) in its message. Wired into the mem test run via
tools/mem/tests/test_repo_lint.py and CI (.github/workflows/ci.yml).

Usage: python tests/repo_lint.py [ref]   (default: HEAD; env REPO_LINT_REF)
Exit 0 = clean, 1 = violation, 2 = git unavailable/not a repo (skip).
"""

import os
import re
import subprocess
import sys

BEHAVIOR_RE = re.compile(r"^tools/mem/mem/.*\.py$")
ADR_REF_RE = re.compile(r"ADR-\d{4}|docs/adr/")


def _git(root, *args):
    r = subprocess.run(["git", "-C", root] + list(args),
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return r.stdout


def lint_commit(root, ref):
    """Return a violation message for one commit, or None if clean."""
    message = _git(root, "log", "-1", "--format=%B", ref)
    files_blob = _git(root, "show", "--name-only", "--format=", ref)
    if message is None or files_blob is None:
        return None
    files = [f for f in files_blob.splitlines() if f.strip()]
    touched = [f for f in files if BEHAVIOR_RE.match(f)]
    if not touched:
        return None
    documented = any(f == "CHANGELOG.md" or f.startswith("docs/adr/")
                     for f in files)
    if documented or ADR_REF_RE.search(message):
        return None
    return ("commit %s touches mem behavior (%s) with no CHANGELOG.md/"
            "docs/adr entry and no ADR-NNNN ref in the message"
            % (ref, ", ".join(touched[:4])))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    ref = argv[0] if argv else os.environ.get("REPO_LINT_REF", "HEAD")
    if _git(root, "rev-parse", "--git-dir") is None:
        print("repo-lint: skip (not a git repo)")
        return 2
    violation = lint_commit(root, ref)
    if violation:
        print("repo-lint FAIL: %s" % violation)
        return 1
    print("repo-lint ok (%s)" % ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())
