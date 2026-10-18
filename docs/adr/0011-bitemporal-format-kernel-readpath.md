# ADR-0011: Bi-temporal claim format + kernel read path in mem

- Status: accepted
- Date: 2026-10-18
- Deciders: human (session), mem kernel build
- Refs: arXiv:2501.13956 (Zep/Graphiti bitemporal KG), arXiv:2603.13017
  (structured conversation distillation), arXiv:2502.14802 (HippoRAG 2),
  arXiv:2502.12110 (A-MEM), ReMe (ACL Findings 2026, arXiv:2608.03403),
  silicon-ledger CROSS-REPO-CONTRACT.md (evidence honesty), ADR-0005,
  ADR-0008, tests/test_temporal.py, tests/test_readpath.py,
  tests/test_evalkit.py

## Context

The mem hub captured and served claims, but the read path was flat:
one BM25 pass over whole pages, no time model, no compression, and no
harness measuring whether recall actually helps a small model. Every
"when was this true" question required reading prose; every token
injected into an agent context was paid at raw transcript price. The
field evidence (Mem0, Zep, HippoRAG, Infini-Memory) converges on a
kernel shape: distilled layers over verbatim ground truth, bi-temporal
stamping, hybrid retrieval with fusion, and eval that reports tokens
with quality — none of which the store had.

## Decision

We raise the wire format to `mem-wiki@2`: claims gain optional
`valid_at`/`invalid_at` (valid time; transaction time was already the
`date`), relative date phrases are resolved at EMIT time (an
unresolved relative date is unrecoverable later), and supersession is
modeled by stamping `invalid_at` on the old claim, never by editing or
deleting it. On top of the format we ship a seven-part kernel:
structured exchange distillation (`distill.py`: compound objects with
verbatim `specific_context`, literal-appearance verify gate, raw stays
untouched); a daily workbench layer (`daily.py`: ReMe lifecycle,
line-anchored cards, bounded quote-gated consolidation); a hybrid read
path (`readpath.py`: SQLite FTS5 BM25 over verbatim sections +
deterministic feature-hash vectors over distilled objects, RRF fusion,
recency+importance scoring, token-budget packing, citation tags on
every item); an entity graph (`graph.py`: typed bitemporal edges,
2-hop expansion always fused, never graph-only); an own-traffic eval
harness (`evalkit.py`: bootstrapped queryset, consensus graders,
MRR/P@1 WITH tokens-per-query, protocol stamp, headline emitted to the
ocl ledger per AGENTS.md rule 6); and silicon-ledger hygiene rules
(`hygiene.py`: computed `evidence_status` ok/stale/unlocatable,
machine `model_check` that can reach corroborated but never verified,
standing `reconcile` audit).

## Consequences

Recall becomes time-aware (`asof`) and price-aware (tokens in every
report); raw captures stay immutable ground truth while distilled and
daily layers are rebuildable. Cost: v2 stamps require `mem migrate`
on older homes, every packed item must carry its citation tag, and the
harness now makes retrieval regressions visible — scores without an
`eval_stamp.json` match are not comparable. The feature-hash embedder
is an explicit placeholder behind an injectable `embed` callable; a
neural provider can replace it without touching storage. `model_check`
creates a second machine-grade status, so consumers must read status
semantics (verified == human) before trusting a claim.
