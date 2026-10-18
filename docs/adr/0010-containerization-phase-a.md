# ADR-0010: Containerization Phase A proven on Studio; Phase B held

- Status: accepted (Phase A); Phase B proposed, blocked (ISSUES-a/b)
- Date: 2026-10-04
- Deciders: operator
- Refs: tools/mem/Containerfile, scripts/container-memhub.sh,
  deploy/studio/uk.4rg0naut.memhub.container.plist, ADR-0002, ISSUES-a

## Context

ADR-0002 said containers earn their rent when a service needs image
isolation, preferring apple/container (no Docker). T6 set out to prove
the pattern for `mem` and, in Phase B, to move tailscaled itself into
the container (userspace networking) so the service node owns its
tailnet identity.

## Decision

Run mem as a first-class apple/container workload:
`container build -f tools/mem/Containerfile` (python:3.12-slim + the
stdlib-only `mem` package — zero pip installs in the image),
`container run --memory 256m --cpus 1 --publish <host>:8520/tcp
--volume <repo>/memory:/memory`. The memory root is the only mounted
surface. Boot persistence via LaunchAgent →
scripts/container-memhub.sh (idempotent system-start + start-or-run).

## Consequences (measured 2026-10-04, Studio)

Proven: image builds in <10 s; container serves `/healthz` (home
inside = /memory) and the T4 acceptance query through the published
port; `container stats --no-stream` shows real accounting
(44.6 MiB/256 MiB, net + block counters); egress to the fleet works
from inside the VM (mini's SearXNG answered 21 JSON results via the
host NAT gateway — the host-gateway→Ollama probe on the mini itself
remains to be run there). Deviations recorded honestly: demo ran on
Studio because apple/container is not yet installed on mini (cask
install needs an interactive sudo password — ISSUES-b family); host
port was 18520 there to dodge the Studio agent's own :8520 (ADR-0005
split on mini uses 8520/8521 directly). Phase B (tailscaled in
container, ISSUES-a) stays blocked: no TS_AUTHKEY without an admin key,
and inbound-to-userspace-tailscaled on apple/container is still
unproven. Until then the host-side serve + path mounts (ISSUES-g)
remain the network face.
