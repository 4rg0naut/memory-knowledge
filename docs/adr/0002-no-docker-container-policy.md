# ADR-0002: No Docker; launchd first, apple/container preferred

- Status: accepted
- Date: 2026-09-27
- Deciders: operator (user mandate)
- Refs: docs/container-policy.md (C9), ADR-0007

## Context

Fleet is Apple Silicon (Studio, mini). Docker adds a Linux VM layer the
fleet does not need and the user explicitly rejects. Containers must earn
their rent.

## Decision

No Docker runtime anywhere. Ladder: plain launchd job first; when image
isolation is genuinely needed, `apple/container` (rootless,
Virtualization.framework) with podman+quadlet files kept alongside as the
portable fallback to Linux.

## Consequences

Services deploy as plists today (see deploy/). Resource accounting goes
through `container stats` when containers arrive. The tailscale sidecar
pattern must use container-network DNS names, not shared localhost.
