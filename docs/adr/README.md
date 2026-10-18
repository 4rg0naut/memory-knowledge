# ADR log

Architecture Decision Records for Memory_Knowledge. One decision per file,
named `NNNN-title.md`, immutable once accepted (corrections are new ADRs
that `Supersede:` the old one — same discipline as the claim ledger).

Template:

```
# ADR-NNNN: <title>

- Status: proposed | accepted | superseded by ADR-XXXX
- Date: YYYY-MM-DD
- Deciders: <who>
- Refs: <commit SHAs, claims clm_..., issues>

## Context
What pressure forced a decision.

## Decision
What we chose (active voice, one paragraph).

## Consequences
What gets easier, what gets harder, what is now owed.
```

Index:

| ADR | Title | Status |
|-----|-------|--------|
| [0001](0001-vendored-openclaims-clean-room.md) | Vendored OpenClaims v0.1, clean-room implementation | accepted |
| [0002](0002-no-docker-container-policy.md) | No Docker; launchd first, apple/container preferred | accepted |
| [0003](0003-memsvc-isolation.md) | memsvc service-user isolation for the memory root | accepted |
| [0004](0004-format-codec-first.md) | Format codec before feature work | superseded by 0005 (re-adopted, sequenced) |
| [0005](0005-port-split-before-codec.md) | Read/write port split ships before the codec | accepted |
| [0006](0006-grants-vs-acl-format.md) | Tailnet writes gated by ACL attribute + tag, not OAuth grants | accepted |
| [0007](0007-tailscale-in-container-goal.md) | tailscaled-in-container (userspace) as the goal state | proposed |
| [0008](0008-rules-as-data-layered-composition.md) | Rules as data with layered patch composition | accepted |
| [0009](0009-searxng-commit-pinning.md) | Pin SearXNG to an upstream commit (no release tags) | accepted |
| [0010](0010-containerization-phase-a.md) | Containerization Phase A proven on Studio; Phase B held | accepted / B blocked |
| [0011](0011-bitemporal-format-kernel-readpath.md) | Bi-temporal claim format (mem-wiki@2) + kernel read path in mem | accepted |
| [0012](0012-guardrail-claims-era-tiering-eval-cis-crash-honesty.md) | Guardrail claims, era-aware evidence, eval CIs, crash-honest JSONL | accepted |
| [0013](0013-public-snapshot-publication.md) | Public publication as sanitized fresh-history snapshot | accepted |
