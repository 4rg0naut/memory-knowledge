# ADR-0004: Format codec before feature work

- Status: superseded by ADR-0005 (sequencing re-adopted in T2)
- Date: 2026-09-29
- Deciders: operator
- Refs: task board M1/T2, DSH session-log pattern

## Context

`mem` grew its page, raw, index, and events byte formats inline across
store.py/schema.py. Any future format change would need migrations over a
corpus that is still small.

## Decision

Extract all byte formats into one codec module stamped `mem-wiki@1`,
with a `mem migrate` command, before further feature work; committed
files are never rewritten in place (versioned successor files).

## Consequences

Later decisions (port split first, ADR-0005) reordered this: the codec
remains first *among code refactors* (T2), but no longer blocks network
hardening. The no-in-place-rewrite rule survives as standing policy.
