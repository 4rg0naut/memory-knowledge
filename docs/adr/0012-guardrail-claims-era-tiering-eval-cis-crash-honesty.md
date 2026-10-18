# ADR-0012: Guardrail claims — contradiction promotion, retirement, and an
# era-aware, crash-honest read path

- Status: accepted
- Date: 2026-10-18
- Deciders: human (session), agent (builder)
- Refs: ADR-0011 (supersedes nothing; extends), tasks ce8d583c / 8f44b50e /
  9dcda2a1 / f20e61de, external review 2026-10-18

## Context

An external review of the ADR-0011 kernel identified four gaps:
(1) a `contradicted` status records that a claim was refuted but changes
nothing at retrieval — the agent keeps acting on the stale claim, and
nothing states the prohibition; (2) `evidence_status` guessed a claim's
capture era from token coverage instead of consulting the `quote_ok`
flag already recorded in the claim's `emit` event; (3) eval verdicts
(graph-vs-fused multihop) were declared on point estimates whose
bootstrap intervals overlap, i.e. on sampling noise; (4) the file-first
store documented no writer boundary and its JSONL readers crashed on a
torn trailing line from a crash mid-append.

## Decision

We extend the claim model with a **`guardrail` status** (and
`superseded`): a fresh contradiction additionally emits a guardrail
claim — a prohibition (`"do not assert X"`, pred `gotcha`) carrying
BOTH lineages (`contradicts::[[old]]` plus `derived_from` of the
refuting claim and its raw) and a new optional claim attribute
**`revalidate_at`** (TTL, env `MEM_GUARDRAIL_TTL_DAYS`, default 90).
The read path guarantees a guardrail outranks every claim it contradicts
(lineage-ordered, `readpath.honor_guardrail_order`, plus a
`GUARDRAIL_BOOST` among topic neighbors). Retirement is re-validation,
not deletion: when `revalidate_at` passes, the standing audit
(`reconcile`) re-checks whether the refutation is still active; if the
failure was fixed, the guardrail becomes `superseded` with `invalid_at`
stamped — history is never edited away. `evidence_status` now branches
on the emit event's `quote_ok` (`hygiene.quote_era`): quote-era and
pre-gate claims get explicitly attributed details, and the verdict logic
is unchanged (attribution, not silent rescoring). Eval comparisons
carry 95% bootstrap CIs per (mode, query_type); `graph.scorecard`
returns `inconclusive` when the multihop intervals overlap — noise may
not decide architecture; `eval --rotations N` grows measurement across
seed-rotated querysets and reports per-seed variance. All JSONL readers
go through `codec.read_jsonl`, which reports torn lines rather than
crashing or silently accepting them, and `reconcile` fails on them.
`store.write` keeps tmp+`os.replace` atomic-rename (now with process-
unique tmp names); `store.append_event` fsyncs per line.

## Consequences

Easier: prohibitions surface exactly when the stale claim matches; stale
prohibitions expire visibly; evidence verdicts state their era; eval
verdicts state their uncertainty; crash/append semantics are specified,
tested, and documented (docs/concurrency.md). Harder / owed: guardrail
status widens the byte-format vocabulary (old files unaffected; new
files with guardrail claims need mem-wiki@2 parsers aware of the two
added statuses and `revalidate_at`); a TTL policy must eventually be
host-tunable via rules layers, not only env; multi-machine shared-FS
writes remain unsupported by design (single hub writer, git for
cross-machine); retired-guardrail retrieval for the "stale direction"
is measured only when retired guardrails exist on the home.
