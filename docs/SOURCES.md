# Sources — where the ideas came from

Every external idea this repo stands on, with its citation and a
verification status. Following the repo's own discipline (AGENTS.md):
verified means the identifier was fetch-checked against arxiv.org/the
publisher on the stated date; anything else is an assertion and is
labelled as such.

## Papers (verified 2026-10-18 unless noted)

| idea used here | source |
|---|---|
| Long-term interactive memory abilities as a benchmark axis (recall/update/abstention thinking behind `mem eval` query types) | **LongMemEval** — Wu et al., [arXiv:2410.10813](https://arxiv.org/abs/2410.10813) |
| Production memory layer framing: extraction vs storage vs retrieval separation; latency/token cost as first-class metrics (`tokens_per_query` in every eval report) | **Mem0** — Chhikara et al., [arXiv:2504.19413](https://arxiv.org/abs/2504.19413) |
| Temporally-aware knowledge graph with validity intervals; edges that are retired, not deleted (`valid_at`/`invalid_at` bitemporal edges, `asof`) | **Zep / Graphiti** — Rasmussen et al., [arXiv:2501.13956](https://arxiv.org/abs/2501.13956) |
| Hippocampal-indexing view: entity-link graph over passages for multi-hop recall (`graph` eval mode, entity pages + `derived_from` edges) | **HipporAG** — Gutiérrez et al., [arXiv:2405.14831](https://arxiv.org/abs/2405.14831) |
| Agentic memory with structured linked notes and agent-driven organisation (wiki pages with typed edges as the storage substrate) | **A-MEM** — Xu et al., [arXiv:2502.12110](https://arxiv.org/abs/2502.12110) |
| Experience reuse with refinement and confidence tracking (distill/daily/consolidate layer, status weights) | **ReMe** — [arXiv:2512.10696](https://arxiv.org/abs/2512.10696) |
| Evaluation must probe the memory system itself, not only downstream QA; provenance-section reporting direction (T9-C) | **Beyond Downstream QA** — Toma et al., [arXiv:2610.22209](https://arxiv.org/abs/2610.22209) (verified 2026-10-18, see session log) |
| Taxonomy + empirical analysis of agentic-memory evaluation and system limitations (framing for `docs/concurrency.md`, hygiene gates) | **Anatomy of Agentic Memory** — [arXiv:2602.19320](https://arxiv.org/abs/2602.19320) (verified 2026-10-18) |

## Classical IR

- **CombMNZ** fusion (score consensus bonus used by the `fused` read
  path): multiple-search-engine fusion literature, Hearst & Fox 1994
  ("An Alternative Technique for Multiple Search Engine") and the
  fusion-robustness study Cormack, Clarke, Lysy & Buettcher SIGIR 2009.
  *Status: classical, textbook-cited, no single arXiv id;
  assertion-grade reference.*

## Specs and infrastructure

- **OpenClaims 0.1 event model** — the hash-chained claim ledger
  (`claims/claims.jsonl`, `ocl`). Pinned upstream commit and provenance
  in [`vendor/openclaims/PROVENANCE.md`](../vendor/openclaims/PROVENANCE.md);
  clean-room implementation (ADR-0001).
- **SQLite FTS5** — BM25 sparse retrieval behind `mem recall`
  (stdlib `sqlite3`; no external service).
- **macOS Vision framework** — `.accurate` tier OCR in the prune-gate
  benchmark (`benchmarks/prune-gate/vision_ocr.swift`).
- **SearXNG** — self-hosted web search for capture-side tooling
  (`SEARXNG_URL` single-env wiring; commit-pinned per ADR-0009).

## Style and method references

- **silicon-ledger** (`4rg0naut/silicon-ledger`, private sibling repo) —
  benchmark publishing style adopted here: harness + committed expected
  outputs + one-command verifier, environment stamped on every run
  (`benchmarks/`, `scripts/verify-bench.sh`). *Status: own prior work;
  self-citation, verify by running it.*

## What is deliberately NOT borrowed

- Model-based extraction scoring, LLM graders, embedding services at
  eval time: `mem eval` is deterministic by construction
  (feature-hash vectors + FTS5 + seeded bootstrap) so published numbers
  are reproducible byte-for-byte without GPU or account access.
