# Container policy (C9) — Docker-free

## Rule

No Docker runtime, ever, on the fleet. Containers "earn their rent" only
when a service needs them; until then services are plain launchd jobs.

## Ladder

1. **launchd first.** Every new service starts as a LaunchAgent
   (user-facing) or LaunchDaemon (system) plist with `KeepAlive` +
   `StandardOutPath`/`StandardErrorPath` logs. `ocl serve` is the pattern:
   one binary/script, one port, one state directory.
2. **apple/container when needed.** When a service genuinely needs
   image-based isolation (portable deps, non-Python runtimes), use
   `container` (v1.4.x, rootless, Virtualization.framework) on the mini
   (and Studio). VM-per-container is fine — the fleet is Apple Silicon.
3. **Podman + quadlet as portable fallback.** Anything expected to migrate
   to Linux gets a quadlet unit kept alongside, so the move is a file copy,
   not a rewrite.

## Networking

- Tailscale is the network. Services join the tailnet via Tailscale's OCI
  image as a **per-service sidecar**; `tailscale serve` exposes the local
  port on a per-service tailnet name.
- On apple/container the sidecar reaches the app container by
  **container-network DNS name**, not shared `localhost` (each container is
  its own VM).
- Per-service tailnet names + ACLs; **ephemeral auth keys** for
  throwaway/CI containers.
- Consumers configure one env var pointing at the tailnet name
  (e.g. `OCL_URL=http://ocl-hub.tailnet.ts:8517`) — machine migration is
  one string.

## Graduations (documented, not active)

- Headscale on a VPS replaces Tailscale's hosted control plane if we ever
  want self-hosted coordination.
- Cloudflare Tunnel/Zero Trust only for services that must go public —
  never as a substitute for the tailnet.

## Why no Docker

- Apple Silicon: Virtualization.framework (apple/container) and OrbStack
  already provide the isolation without Docker Desktop's licensing or the
  Linux-VM-by-default overhead on macOS.
- Podman covers the "must match a Linux server someday" case with the same
  quadlet discipline.
- Small static fleet: launchd gives process supervision with zero extra
  runtime.
