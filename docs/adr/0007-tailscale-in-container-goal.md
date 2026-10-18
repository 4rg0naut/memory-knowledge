# ADR-0007: tailscaled-in-container (userspace) as the goal state

- Status: proposed
- Date: 2026-09-29
- Deciders: operator
- Refs: docs/container-policy.md, ISSUES-a, T6 Phase B

## Context

Today tailscale runs natively on the mini host and `tailscale serve`
proxies to mem ports. If the hub moves into an apple/container VM
(ADR-0002 ladder step 2), it needs tailnet membership of its own.
Docker sidecars are out of policy.

## Decision

Goal state: run `tailscaled` inside the service container in
`--tun=userspace-networking` mode (no /dev/net/tun in the VM),
TS_AUTHKEY persisted in the data volume, `tailscale serve --bg 8520`
from inside. The container node then owns `tag:mem-hub` and the
mem.tailnet HTTPS name, retiring the host-side serve + :8521 split.

## Consequences

One deployable unit (image + volume + plist). Blocked on an unproven
assumption: inbound reachability to a userspace-networking tailscaled on
apple/container has never been smoke-tested (ISSUES-a); keep host-side
fallback until proven.
