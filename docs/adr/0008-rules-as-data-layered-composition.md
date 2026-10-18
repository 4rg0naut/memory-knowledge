# ADR-0008: Rules as data with layered patch composition

- Status: accepted
- Date: 2026-09-29
- Deciders: operator
- Refs: task board M2/T2, DSH composition model

## Context

Hygiene gates (quote-match, inference cap 0.8, no-agent-verified,
derived_from required) are hardcoded in hygiene.py. Per-source rule sets
(web vs chat/session logs) are coming (T3/T4), and hosts legitimately
disagree (mini enforces, laptop experiments).

## Decision

Move gates into a declarative `rules/base.yaml`; the engine is a small
dispatcher keyed by rule name + params. Configuration composes in
layers, later wins: base -> host profile -> one personal `patch.yml`.
`mem rules list` prints the effective set with the provenance of every
override.

## Consequences

Gate changes become reviewable diffs, not code edits; per-source rule
sets are a YAML fork, not a branch. Cost: rules drift becomes possible
between host profiles — `rules list` output is the debugging entry
point, and lint must show which file set each value.
