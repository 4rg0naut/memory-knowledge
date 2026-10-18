# ADR-0013: Public publication as sanitized fresh-history snapshot

- Status: accepted
- Date: 2026-10-18
- Deciders: operator (user decisions 2026-10-18: private-first, demo
  home substitution, 4rg0naut handle kept)
- Refs: scripts/check-pii.py, scripts/pii-excludes.txt,
  scripts/publish-snapshot.sh, scripts/make-demo-home.py,
  scripts/verify-bench.sh, benchmarks/expected_results.json,
  demo/, docs/SOURCES.md, ADR-0003 (memsvc isolation), ADR-0012

## Context

The repo is a few weeks of private incident-born history: git authors
carry personal names and host machine names; commit history embeds every
past version of the real memory home (`memory/raw` captures, `knowledge/
inbox` conversation pastes, the production claims ledger), LAN/tailnet
addresses, and absolute paths on private volume mounts. Rewriting 100+
commits to scrub all of that is more error-prone than a snapshot, and
"trust the scrub" is exactly the kind of unverifiable assertion this
project exists to eliminate.

## Decision

Publish to GitHub as `4rg0naut/memory-knowledge`, **private first,
public after the automated gate is green**, as a fresh-history
snapshot: `scripts/publish-snapshot.sh` exports the working tree to a
temp dir, substitutes the production data directories (`memory/`,
`knowledge/inbox/`, `claims/`) with the sanitized demo artifacts under
`demo/`, drops the private real-screen benchmark captures and the local
`results.json` artifact, commits everything as a single initial commit,
runs `scripts/check-pii.py --strict` on the exported tree as a hard
pre-push gate, and force-pushes to `origin/main`. The full history and
the production memory home stay on the mini hub (`mini` remote);
`origin` receives snapshot pushes only — never branch history. CI
enforces the same PII scan plus the test suites and
`scripts/verify-bench.sh` (deterministic demo-home eval on every
platform; prune-gate Vision arm on macOS runners).

Redaction map (host-neutral, semantics-preserving): personal username →
`operator`, Studio hostname → `studio`, mini legacy hostname →
`oldmini`, tailnet → `net01`, private volume → `/Volumes/work`, LAN IPs
→ RFC5737 `192.0.2.x`, tailnet IPs → `198.51.100.x`, assistant name
references → generic. Approved public identity: the `4rg0naut` handle
and `4rg0naut.uk` domain (operator decision). The `oMLX` name is public
OSS (jundot/omlx), not personal data. ADR bodies were scrubbed with
this map too — an explicit, recorded exception to ADR immutability for
privacy redaction only (no semantic edits; the local hub history
remains the un-scrubbed canonical record).

## Consequences

Easier: a clean clone can be installed, tested, and benchmark-verified
by a stranger without touching private data (`verify-bench.sh`
falsifies every published number); the PII gate becomes a CI job, so
future leaks fail loudly instead of silently publishing; re-publishing
stays one command, keeping the discipline repeatable rather than a
one-time scrub.

Harder: the public repo carries no git archaeology — blame/ bisect
history lives on the mini hub only; demo filenames embed the generator's
checkout path, so regeneration from another machine produces a diff to
review; every future change to published paths must pass the strict
scan (new personal patterns must be added to `check-pii.py` patterns,
which is the intended failure mode). Owed: re-run
`scripts/make-demo-home.py` + refresh `expected_results.json` after any
read-path behavior change; add a publish cadence decision (per-release
vs on-demand) when the first post-public change lands.
