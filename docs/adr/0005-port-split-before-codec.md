# ADR-0005: Read/write port split ships before the codec

- Status: accepted
- Date: 2026-09-29
- Deciders: operator
- Refs: commit 7c303e0, supersedes the sequencing of ADR-0004

## Context

The hub is reachable on the tailnet. The original plan was
format-codec-first, but the live exposure needed a safety boundary now,
and the codec work is easier once the write path is a single, named door.

## Decision

Ship the two-listener split immediately: public `:8520` serves GET only;
writes require `:8521`, bound 0.0.0.0 but restricted to devices holding
ACL attribute `tag:mem-writer`. Codec work is re-sequenced after it
(T2), so format-codec-first survives as a queue order, not a blocker.

## Consequences

Network misconfiguration can no longer corrupt the corpus via GET.
Tailscale grants/ACL must now express the attribute (ADR-0006, T5).
The port split is fleet policy — retire only when containerization
supersedes it (ADR-0007, T6 Phase B).
