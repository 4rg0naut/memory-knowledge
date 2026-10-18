# AGENTS.md — Memory_Knowledge

Repository for claim-provenance infrastructure: a ledger (`claims/`), an
inbox of captured conversations (`knowledge/inbox/`), evidence snapshots
(`knowledge/evidence/`), the `ocl` tool (`tools/ocl/`), and benchmarks
(`benchmarks/`).

## Injection discipline (mandatory for every harness/agent)

1. **Cite or it didn't happen.** Any agent reading this knowledge base must
   attach `claim_ref` + verification status when using a stored claim.
   `ocl query --cite` emits ready-made tags:
   `[claim:clm_xxx|supported/source_attestation]`.
2. **Unverified = assertion.** A claim with no verification event is
   rendered as an *assertion*, with lineage (`source_uri`, producer,
   derivation) — never as established fact. Absence of verification is an
   honest floor, not a license to upgrade.
3. **Disputed is visible.** Disputed claims render with a flag and the
   refuting rationale (see `ocl check <ref>` history). Never present a
   disputed claim unflagged.
4. **No silent rewriting.** Corrections are new events (dispute/retract +
   re-emit), never edits of past lines. The ledger and inbox files are
   append-only history; fix forward.
5. **Inbox is raw, ledger is graded.** `knowledge/inbox/*` are captures
   (may contain errors); only claims in the ledger carry typed status
   (`factual`/`calculation`/`inference`/`recommendation`/`prediction`).
   When an agent repeats an inbox fact without a ledger ref, it inherits
   rule 2.
6. **Benchmark results are claims.** Harness metrics must be emitted and
   verified like any other claim (see `benchmarks/prune-gate/`).

## Layout

- `claims/claims.jsonl` — canonical ledger (hash-chained events)
- `claims/spool.jsonl` — offline write buffer (emptied by `ocl sync`)
- `tools/ocl/` — CLI + tests (`tools/ocl/ocl <cmd>`, run tests:
  `cd tools/ocl && ./.venv/bin/python -m unittest discover -s tests`)
- `tools/mem/` — file-first claim memory over `memory/` (`python -m mem`,
  tests: `cd tools/mem && ./.venv/bin/python -m unittest discover -s
  tests`); byte formats live in `mem/codec.py` (stamp `mem-wiki@2`,
  migrate with `mem migrate`), hygiene gates are declarative in
  `rules/base.yaml` + optional `host-*.yaml`/`patch.yml` layers
  (`mem rules list` shows effective set + provenance); kernel commands:
  `distill`/`daily`/`consolidate` (layers), `recall`/`asof` (read path,
  ADR-0011), `graph`, `eval` (metrics always with tokens/query,
  bootstrap CIs + `--rotations` seed-rotated querysets),
  `evidence`/`modelcheck`/`reconcile` (S5 hygiene — machines stamp
  `corroborated` only; `verified` stays human; guardrail claims —
  prohibitions emitted on contradiction with `revalidate_at` TTL,
  lineage-ranked at retrieval, superseded-not-deleted on retirement;
  era-aware evidence via emit-event `quote_ok`; JSONL readers report
  torn lines, ADR-0012, docs/concurrency.md)
- `memory/` — mem root: `raw/` (immutable sources), `wiki/` (claims as
  attributed lines), `index.yaml` (regenerable router), `events.jsonl`
  (append-only transitions). Hub copy runs on the mini — see `deploy/`.
- `deploy/` — launchd plists + hub runbook (`deploy/mini/README.md`)
- `vendor/openclaims/` — pinned spec/schema/fixtures (see PROVENANCE.md;
  never edit in place)
- `docs/roundtrip.md`, `docs/networking.md` — worked proofs
- `docs/concurrency.md` — writer/crash boundary (single machine; flock +
  atomic rename), evidence in `tools/mem/tests/test_concurrency.py`
- `docs/adr/` — decision log (README has the template + index; ADRs are
  immutable once accepted, corrections are superseding ADRs)
- `CHANGELOG.md` — Keep-a-Changelog history (required by repo lint for
  mem behavior changes)
- `FAILURES.md` — recurring-failure register (symptom→cause→rule);
  read before debugging `tools/mem/`; a bug is fixed only when it has
  a rule + a test here
- `ISSUES.md` — open unknowns register, referenced by id (ISSUES-a…)
- `scripts/` — ops-as-code: bootstrap-mini/studio, apply-policy,
  backup-memory, container-memhub (see infra/README.md); publication
  layer (ADR-0013): `check-pii.py` (+ `pii-excludes.txt`),
  `make-demo-home.py`, `publish-snapshot.sh`, `verify-bench.sh`,
  `compare_expected.py`
- `demo/` — sanitized Harbor Robotics memory home (generator output,
  committed), its sources, and the demo ledger roundtrip output;
  substitutes `memory/`, `knowledge/`, `claims/` in the published
  snapshot
- `benchmarks/expected_results.json` — committed expected metrics for
  `verify-bench.sh`
- `tests/repo_lint.py` — discipline lint, wired into the mem test run
  (`tools/mem/tests/test_repo_lint.py`) and CI: a commit touching
  `tools/mem/mem/*.py` must also touch CHANGELOG.md/docs/adr/ or cite
  `ADR-NNNN` in its message
- `.github/workflows/ci.yml` — fixture conformance + unit tests + wheel
  build on every push
- `infra/README.md` — fleet/network status (C1)
- `docs/container-policy.md` — containerization rules (C9)

## Conventions

- Single config knob per consumer: one `*_URL` env (`OCL_URL`,
  `SEARXNG_URL`). Never hardcode hosts in code.
- Python stdlib-first; only vendored/pinned deps in `.venv`
  (currently `jsonschema`); record new ones in PROVENANCE-style notes.
- New selectors/ids follow existing prefixes: `clm_ evt_`.
