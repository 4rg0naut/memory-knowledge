# Changelog

All notable changes to Memory_Knowledge follow
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Format dates are
real merge dates from `git log`.

## [Unreleased]

### Added
- **Publication layer (ADR-0013, 2026-10-18)**: `scripts/check-pii.py`
  PII gate (pattern classes for operator username, hostnames, tailnet,
  private volume, LAN/CGNAT IPs, personal e-mail domains, assistant
  name; approved-identity allowlist; `--strict` for the published
  tree, `scripts/pii-excludes.txt` for local runs);
  `scripts/make-demo-home.py` builds the sanitized Harbor Robotics demo
  home + demo roundtrip ledger through the real quote-gated pipeline
  (`demo/`); `scripts/publish-snapshot.sh` exports a single-commit
  fresh-history snapshot with demo substitution and enforces the strict
  gate pre-push; `scripts/verify-bench.sh` +
  `scripts/compare_expected.py` + `benchmarks/expected_results.json`
  reproduce every published number (mem-eval everywhere, prune-gate
  Vision arm on macOS; `run_bench.py --vision-only` added,
  `VISION_OCR` env honored); `benchmarks/README.md`, `docs/SOURCES.md`
  (all paper citations fetch-verified 2026-10-18), ADR-0013; CI gains
  `pii-gate` (hard, first) and `bench-verify` jobs; `tools/ocl/ocl`
  launcher resolves venv → repo-root venv → python3 instead of
  hard-coding a local venv.
- T8 review follow-ups (ADR-0012, 2026-10-18): **guardrail claims** —
  a fresh contradiction now additionally emits a prohibition claim
  (`status: guardrail`, pred `gotcha`, text "do not assert X") carrying
  both lineages (`contradicts` the retired claim, `derived_from` the
  refuter + its raw) and a `revalidate_at` expiry (env
  `MEM_GUARDRAIL_TTL_DAYS`, default 90); `readpath.honor_guardrail_order`
  guarantees a guardrail outranks every claim it contradicts, plus a
  GUARDRAIL_BOOST among topic neighbors; retirement is re-validation,
  not deletion — expired guardrails whose refutation is still active
  stay, fixed ones become `superseded` with `invalid_at` (event
  `guardrail_retire`), run inside `mem reconcile`
  (`guardrail_retirement` in the report); `evalkit.guardrail_eval`
  scores BOTH regression directions separately (active guardrail must
  outrank the contradicted claim; a retired guardrail must NOT outrank
  the newer claim), reported in every eval report as `adversarial`.
- **Era-aware evidence tiering**: `hygiene.quote_era` consults the
  claim's emit event `quote_ok` instead of guessing from coverage;
  `evidence_status` details are explicitly attributed ("quote-era:" /
  "pre-gate capture: verbatim not required"); verdict logic unchanged —
  measured over the real home: zero verdict flips (56 ok / 20
  unlocatable before and after; 19 of the 20 are quote-era paraphrases,
  1 pre-gate). `reconcile`/`evidence` output carries `quote_era` per
  row + era-separated counts.
- **Eval CIs + seed rotation**: 95% bootstrap CIs (stdlib percentile
  bootstrap, deterministic per seed) on every (mode, query_type) cell
  and `mrr_ci95` per mode; `graph.scorecard` returns `inconclusive`
  when graph-vs-reference multihop intervals overlap — the recorded
  E2 `drop-to-routed` verdict is re-declared `inconclusive` on the
  same data and the E2 experiment doc carries a correction note;
  `mem eval --rotations N` runs seed-rotated querysets (measured:
  3 seeds x 187 = 561 pooled queries, per-seed mrr variance ~0.012,
  multihop still inconclusive), writes `metadata/eval_rotation.json`.
- **Crash/append honesty** (docs/concurrency.md): all JSONL readers
  (`events.jsonl`, graph view, queryset) go through `codec.read_jsonl`
  which REPORTS torn trailing lines — `reconcile` fails on them
  (`torn_event_lines`), graph load records `graph_view_torn_lines`;
  `store.append_event` fsyncs per line; `store.write` tmp names are
  now process-unique (FAILURES F-10: cross-process thread-ident
  collisions); test-only crash hooks `MEM_CRASH_POINT=mid-tmp|
  pre-rename` drive SIGKILL tests; new `tests/test_concurrency.py`
  (10 tests: write-path audit, torn-line reporting, crash injection,
  git-backstop recovery, 4-proc x 3-ingest parallel writers with zero
  loss). Supported boundary: one machine, flock + atomic rename;
  multi-machine shared-FS writers remain unsupported (ISSUES-j).

- T7 mem kernel (ADR-0011, review-hardened): format `mem-wiki@2` —
  claims gain optional `valid_at`/`invalid_at`, relative dates resolved
  at emit, supersede by invalidation (never edit/delete); `mem asof`
  answers "what did we believe on day X". New modules: `chunking.py`
  (heading-tree sections with `#Lx-Ly` line anchors + anchored reads),
  `distill.py` (session exchanges -> compound objects, verbatim
  `specific_context` literal-appearance gate, raw untouched; distill
  floor 500 chars — below it an exchange is not worth distilling and
  stays verbatim-only; own corpus: 15.1x compression, vocab retention
  1.0), `daily.py` (ReMe lifecycle: raw -> line-anchored daily cards
  -> bounded quote-gated consolidation), `readpath.py` (FTS5 BM25
  verbatim + feature-hash-512 vectors over distilled, CombMNZ
  consensus fusion with tiered full-lexical-match protection
  (FAILURES F-08), recency+importance, token-budget packer with
  citation tags on every item; `mem recall --mode
  baseline|distilled|fused|graph`), `graph.py` (typed bitemporal
  entity edges, 2-hop expansion always fused, never graph-only, and
  `scorecard()` decision rule referenced against the best non-graph
  mode), `evalkit.py` (bootstrap queryset ~200 queries across
  exact/phrase/conceptual/multihop with by-construction golds,
  3-grader consensus + gold-graded multihop, MRR/P@1 WITH
  tokens-per-query, protocol stamp, `graph_decision` in every report,
  headline emitted to the ocl ledger per AGENTS.md rule 6). Measured
  own corpus (187 queries, /tmp sandbox): fused mrr 0.807 >= baseline
  0.733, single-hop types 1.0; E2 graph verdict **drop-to-routed** —
  recorded in `docs/experiments/e2-graph-2026-10-18.md`, re-decided by
  scorecard on every eval. S5 hygiene port from silicon-ledger:
  computed `evidence_status` ok/stale/unlocatable, `model_check`
  machines reach corroborated never verified, standing `reconcile`
  audit (incl. duplicate-id detection) ->
  `metadata/audit_report.json`. New commands distill/daily/consolidate/
  graph/recall/asof/eval/evidence/modelcheck/reconcile. Harness
  artifact claim emitted to `claims/claims.jsonl`. Tests 71->153.

- T4 session-journal capture E2E: session prompts extract typed
  incidents (`incident|decision|gotcha` predicates) with verbatim-turn
  quotes; `mem ingest --kind session --producer/--session-id` records
  lineage (origin, retrieved_at, content_hash, producer, session_id);
  query results carry `quote_ref` to the capturing session capture.
  First real capture: `knowledge/inbox/openfox-session-2026-10-04.md`
  (this build session) ingested via one manual-provider command;
  acceptance query "why does launchd ignore edited plists" returns the
  gotcha claim with quote_ref; hallucinated quote rejected by gate.
  Tests 67→71.
- T3 provider seam + sources (M3/M4): `providers.py` with one
  extract-interface and ollama / openai-compatible (`MEM_OPENAI_BASE_URL`
  + `MEM_OPENAI_MODEL` + `MEM_OPENAI_API_KEY`) / manual providers
  selected by one config line (`MEM_PROVIDER` or `--provider`),
  `--dump-prompt` for review, quote gate enforced once in the shared
  candidate filter (manual path included); `sources.py` adapters url /
  file / dir / stdin / session with identical lineage
  (origin, retrieved_at, content_hash); `mem ingest` generic entry
  point (`scrape` kept as alias); per-kind prompts (web facts vs
  session transcript). Server accepts inline `text` + `claims` +
  `provider`; MCP scrape schema generalized. Tests 54→67.
- T2 mem core (ADR-0004/0005/0008): `codec.py` as single owner of all
  byte formats with `format: mem-wiki@1` stamp (pages, raw, events,
  index); `mem migrate` producing stamped successors with originals
  archived under `migrations/<ts>/`; rules-as-data gates in
  `rules/base.yaml` with layered host/patch composition and
  `mem rules list` provenance output. Tests 38→54.
- Repo discipline (T1/ADR-0001..0009): `docs/adr/` log with 9 backfilled
  decisions, `ISSUES.md`, `tests/repo_lint.py` wired into the mem test
  run, root LICENSE/README/pyproject.toml, CI fixture-conformance job.

- T5 ops-as-code: `scripts/bootstrap-mini.sh` +
  `scripts/bootstrap-studio.sh` (every ad-hoc host action since Sep 27,
  incident-commented, idempotent, `--dry-run` verified),
  `scripts/apply-policy.sh` (PUT /acl + tests[] validate, no console
  pastes), `scripts/backup-memory.sh` (first snapshot
  memory-20261004T211212Z.tar.gz), `infra/tailscale-policy.json`
  (tag:mem-writer :8521, SearXNG :8443). SearXNG tailnet serve
  mapping `:8443 -> 8888` enabled on mini.

- T6 containerization Phase A (ADR-0010): `tools/mem/Containerfile`
  (python:3.12-slim + stdlib mem, zero pip deps), `container build` +
  `run --memory 256m --cpus 1` proven on Studio: /healthz + T4 query
  served via published port with memory root as sole mount,
  `container stats` real accounting (44.6/256 MiB), in-VM egress to
  mini SearXNG (21 results) via host gateway; boot persistence
  `scripts/container-memhub.sh` + LaunchAgent plist (idempotent).
  Phase B (tailscaled-in-container) held on ISSUES-a/b, documented.

### Changed
- Review round 3 (fixes #11-#14): directory walks consolidated into
  `Store.list_rel` (single implementation replacing six hand-rolled
  `os.path.join(root, n)[len(store.root)+1:]` copies in readpath,
  daily, graph, evalkit.stamp, cli.cmd_distill — FAILURES F-10 class;
  missing subdir now yields `[]` instead of raising); `ci_overlap`
  single-sourced in `graph`, `evalkit` aliases it; eval-emitted ledger
  claims now carry the spec-shaped digest (`encoding: base64url`,
  value bare base64url — was double-prefixed `sha256:` hex mislabeled
  as base64url); demo home gained
  `harbor-standup-2026-10-15.md` + `mem distill` in the generator so
  all four advertised recall modes are live on the published demo
  (distilled mrr ~0.08 against saturated atomic retrieval — honest
  low, not empty); `verify-bench.sh --update` implemented (rewrites
  `benchmarks/expected_results.json` from measured outputs), the
  previously dead documented flag now works and was used to
  regenerate this round's numbers.
- Review round 2 (fixes #7-#10): `reconcile` now flags a self-stamped
  `verified` claim (verified without verify event) as a problem row so
  cron's exit code catches it (FAILURES F-12); `distill.load_distilled`
  routed through the torn-line policy (`exchanges_view_torn_lines`
  event, non-fatal); all date CLI args (`asof`/`--asof`/`--date`)
  validated as ISO dates at the door; `mem graph <query>` on an
  un-built view emits a `run mem graph --build` hint; `reconcile.checked`
  now counts claims scanned once (was ~2x via parallel era counters).
- `hygiene.contradictions()` now skips guardrail/superseded claims (a
  guardrail is a record of a contradiction, not an independent
  contradictor); `hygiene.ingest` excludes guardrail/superseded claims
  from contradiction matching; `graph.scorecard` verdict vocabulary
  extended with `inconclusive` (only when CI data is present — legacy
  point-estimate reports keep their old verdicts).

### Fixed
- Review round 3 (#11): crash-orphan `.tmp` files are now swept —
  process-unique tmp names (F-10) meant no later writer ever reused a
  crashed writer's name, so orphans accumulated indefinitely;
  `Store.write` deletes stale sibling temps (same-target prefix,
  `.tmp`, older than 1 h), young ones may belong to a live writer and
  stay (gate: `TestStaleTmpSweep`; `docs/concurrency.md` corrected —
  it still described the pre-F-10 name-reuse sweep;
  `publish-snapshot.sh` additionally excludes `*.tmp`).
- Review pass (code review, 2026-10-18): `mem reconcile` exit code
  now fails on any reported problem (was ignoring `unlocatable` /
  `duplicate_id` rows, useless to cron); `mem distill --source`
  hard-errors (exit 2) on a nonexistent source instead of silently
  printing a fabricated `compression: 1.0` (empty input now reports
  `compression: null`); `mem eval --modes` validates names (a typo'd
  mode returned 2 with the valid set instead of reporting a phantom
  mode); every write-side kernel command (distill/graph/eval/
  reconcile joined daily/consolidate/modelcheck) commits its output
  — the git backstop no longer depends on which command ran last;
  help text updated for the RRF->CombMNZ switch and milestone tags
  removed from user-facing strings (FAILURES F-09).
- `evidence_status` passage check is two-tier: literal first, then a
  deterministic token-coverage fallback (>=0.6 of the passage's
  long tokens present in the source) for legacy claims captured
  before the quote gate — paraphrases no longer blanket-`unlocatable`
  (34 -> 20 on the real home; survivors show honest coverage
  0.00-0.50 in the audit), and `model_check` is usable again.
- Claim-id dedup in `readpath.corpus()`: a pre-lint duplicate capture
  (`clm_705bff068594` twice in `wiki/entities/unreal-agent.md`)
  crashed every FTS-backed command with sqlite UNIQUE constraint;
  derived views now absorb history mess and `reconcile` flags
  duplicates (FAILURES F-07).
- Fused-recall mrr regression (fused 0.587 < baseline 1.0): flat-RRF
  rank gaps let additive scores reorder; replaced with CombMNZ +
  tiered lexical backbone (FAILURES F-08).
- `codec.stamp_insert` no longer keeps a stale `format:` stamp when
  migrating v1 files; `temporal.resolve_relative` unit-token parsing
  ("3 days ago" no longer shifts months); `daily` card idempotency
  across mini-YAML nested lists; `evidence_status` exact-bytes digest
  recheck (single delimiter newline, not rstrip-all); distill core/
  context truncation now cuts at word boundaries so the literal gate
  cannot reject its own output.

### Known gaps (registered)
- ISSUES-f: operator-clone pull vs memsvc-owned memory/ (mitigated group
  write; service-clone split owed to T6); ssh-sudo on mini needs
  password.
- ISSUES-g: ACL `tcp:8443` + MagicDNS block Studio->mini HTTPS
  dial-back; policy staged pending TS_API_KEY (ISSUES-b).

## [2026-10-04]

### Added
- SearXNG live on mini: LaunchAgent `uk.4rg0naut.searxng.serve`
  (0.0.0.0:8888), JSON format enabled, limiter off
  (deploy/mini/searxng.serve.plist, searxng.settings.yml.example);
  verified 10 JSON results; ledger claim clm_1b8a26157d014be9a36df3677e.
- Install pinned to upstream commit d48c4b555 — no release tags exist
  (ADR-0009).

## [2026-09-29]

### Added
- `mem` v0.1: file-first claim memory (CLI + HTTP server + MCP shim):
  scrape/query/show/lint/stale/contradictions/orphans/verify/retract/
  index/audit/serve; quote-gated extraction via local Ollama; 29→38
  tests (fe932f4).
- Read/write listener split: GET-only `:8520` public, writes on
  `:8521` behind `tag:mem-writer` (ADR-0005, 7c303e0).
- mini LaunchDaemon plist for `memsvc` lock-down (ADR-0003, 4a1f04f).
- `mem scrape --force` to re-extract stored raw (908bf6a).
- events.jsonl union-merge repair for diverged append-only logs
  (14c3444).

### Fixed
- Ollama 0.34 streams NDJSON by default — requests pin `stream: false`
  (0ff11da); tolerate trailing prose after JSON (ed1b581).
- Rejected claims no longer leave orphan pages; readable default titles
  (e59323d).
- Duplicate same-source claims ignored instead of appended (54bf38f).
- HTML stripped on server scrape path; entities unescaped (bd3d2db).

## [2026-09-27]

### Added
- Claim-provenance foundation (C1–C9): `ocl` clean-room CLI (JCS + hash
  chain + fixture conformance), hash-chained ledger `claims/`, vendored
  openclaims snapshot at 3bd7f0ba with PROVENANCE.md, roundtrip doc,
  prune-gate benchmark, container policy (ADR-0002), fleet networking
  (314b208).
- Upstream issue filed: openclaims-ai/openclaims#1 (LICENSE file).
