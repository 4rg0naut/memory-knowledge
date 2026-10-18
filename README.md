# Memory_Knowledge

Claim-provenance infrastructure for agent memory: capture conversations
and scrapes as raw sources, extract claims through a verbatim-quote
gate, store them as attributed lines in a file-first wiki, and make
every downstream reader **cite a claim or admit it is an assertion**.

## Why this exists

LLM agents inject "memories" into prompts and present them as fact.
Most memory stacks cannot answer: *where did this come from, is it
verified, is it disputed, and what happened to the version I said last
week?* Memory_Knowledge treats a memory as a **claim ledger event**, not
a text blob:

1. **Cite or it didn't happen.** Every injected claim carries
   `claim_ref` + verification status (`ocl query --cite` emits the tags).
2. **Unverified = assertion.** No verification event means the reader
   sees lineage, not authority. Honest floor, no silent upgrades.
3. **Disputed is visible.** Refuted claims render with the refuting
   rationale; contradictions spawn *guardrail* claims ("do not assert
   X, stale since D, re-validate after T") instead of silent edits.
4. **No silent rewriting.** Corrections are new events
   (dispute/retract + re-emit) over an append-only, hash-chained
   history. Fix forward, never overwrite.
5. **Numbers are claims too.** Harness metrics go through the same
   emit/verify discipline, and every benchmark ships with a
   one-command falsifier (`scripts/verify-bench.sh`).

Everything is stdlib-Python + files + SQLite FTS5: deterministic,
inspectable, no services required, works offline on Apple Silicon.
Full idea provenance with citations: [docs/SOURCES.md](docs/SOURCES.md).

## What's here

- **`ocl`** (`tools/ocl/`) — clean-room CLI for the
  [OpenClaims v0.1](https://github.com/openclaims-ai/openclaims) event
  model: emit/verify/dispute/retract/check/chain/conform over a
  hash-chained JSONL ledger (`claims/claims.jsonl`).
- **`mem`** (`tools/mem/`) — file-first claim memory over a memory home
  (`raw/` immutable sources → quote-gated extraction → `wiki/` claims
  as markdown bullets with typed edges → `index.yaml` router +
  `events.jsonl` transitions; hybrid recall with FTS5 + feature-hash
  vectors + CombMNZ; bitemporal validity; eval harness with bootstrap
  CIs). Serves HTTP + a minimal MCP shim.
- **`demo/`** — sanitized Harbor Robotics memory home built through the
  real pipeline; doubles as the benchmark fixture (`scripts/
  make-demo-home.py` regenerates it).
- **`benchmarks/`** — publish-style measurable claims + verifier.

## Quick start (fresh clone)

```sh
python3 -m venv .venv && ./.venv/bin/pip install jsonschema   # ocl only

# test suites (mem is stdlib; run with the venv or any python3 >= 3.9)
cd tools/ocl && ../../.venv/bin/python ocl.py conform ../../vendor/openclaims/fixtures
cd tools/ocl && ../../.venv/bin/python -m unittest discover -s tests
cd tools/mem && python3 -m unittest discover -s tests

# talk to the demo memory home
cd tools/mem
MEM_HOME=../../demo/memory python3 -m mem recall "R200 unified memory"
MEM_HOME=../../demo/memory python3 -m mem eval --seed 42

# reproduce every published benchmark number
scripts/verify-bench.sh
```

Worked provenance walkthrough on the demo data:
[docs/roundtrip.md](docs/roundtrip.md).

## Upstream & provenance

`vendor/openclaims/` pins the upstream spec/schemas/fixtures at commit
`3bd7f0ba17f27a23e1652b39d6f65f2972b99d43` (see
`vendor/openclaims/PROVENANCE.md`). All implementation is clean-room;
nothing imports upstream packages (they publish no PyPI/npm artifacts).

**License situation upstream:** the upstream repo declares MIT in
`python/pyproject.toml` metadata but ships **no LICENSE file**; we filed
[openclaims#1](https://github.com/openclaims-ai/openclaims/issues/1)
asking them to add one. Vendored assets here are used as
interoperability data pending that resolution (ADR-0001). Our own code
is MIT (`LICENSE`).

## Publication model

This repo is published as a **sanitized snapshot** (ADR-0013): a clean
single-commit tree, demo data in place of the private production memory
home, and an automated PII gate (`scripts/check-pii.py`, CI-enforced).
Deployment runbooks (`deploy/`, `infra/`) reference sanitized host
names. Decisions: `docs/adr/`. Open unknowns: `ISSUES.md`. Recurring
failure register: `FAILURES.md`. History: `CHANGELOG.md`. Injection
rules every reading agent must follow: `AGENTS.md`.

## Layout

- `claims/` — published OCL ledger (demo roundtrip; see docs/roundtrip.md)
- `knowledge/` — demo inbox capture + evidence snapshot
- `demo/` — sanitized demo memory home + its sources + generator inputs
- `memory/` — production memory home (private; this tree ships the demo)
- `tools/ocl/`, `tools/mem/` — CLI implementations + tests
- `benchmarks/` — measurable claims, expected results, verifier
- `scripts/` — ops-as-code: bootstrap, backup, PII gate, demo
  generator, benchmark verifier, publish snapshot
- `docs/` — adr/ (decision log), sources, roundtrip, concurrency,
  networking, container policy
- `vendor/openclaims/` — pinned spec assets, never edited in place
- `tests/repo_lint.py` — repo-discipline lint (ADR/CHANGELOG gate)
