# ADR-0001: Vendored OpenClaims v0.1, clean-room implementation

- Status: accepted
- Date: 2026-09-27
- Deciders: operator
- Refs: commit 314b208, vendor/openclaims/PROVENANCE.md, upstream issue
  openclaims-ai/openclaims#1

## Context

OpenClaims v0.1 specifies a claim-event ledger we want to conform to, but
the upstream repo has no LICENSE file, no releases, and no published
artifacts (no PyPI/npm). Depending on their code is impossible and legally
gray.

## Decision

Vendor their spec/schemas/fixtures at pinned commit
`3bd7f0ba17f2` and implement `tools/ocl` clean-room from the spec
(own JCS canonicalization, own hash chain). Reference sources consulted
for behavior only; never copy their SDK.

## Consequences

Conformance is provable via `ocl conform` against fixtures on every push.
We carry the re-vendor burden ourselves. Upstream issue #1 requests a
LICENSE file; until resolved, our README must state the upstream license
situation honestly.
