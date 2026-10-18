# ADR-0009: Pin SearXNG to an upstream commit (no release tags)

- Status: accepted
- Date: 2026-10-04
- Deciders: operator
- Refs: commit afebe26, deploy/mini/searxng.serve.plist, ledger claim
  clm_1b8a26157d014be9a36df3677e

## Context

SearXNG publishes no git release tags; `pip install git+https://...@<anything>`
silently floats to whatever the default branch is, and the running mini
instance was installed ad hoc before pinning discipline applied.

## Decision

Install from an explicit commit: SearXNG 2026.10.4 built from
`d48c4b555` (commit embedded in the version string), python 3.12 venv at
`~/searxng/venv`, dependencies pre-installed with
`--no-build-isolation`. The command line and pin are recorded in
infra/README.md and the plist; upgrades are deliberate re-pins.

## Consequences

Rebuilds are reproducible; upstream float is opt-in. The LAN-IP URL in
the plist assumes the mini's DHCP reservation (documented recovery in
infra/README.md); the tailnet HTTPS path (:8443) is the durable
graduation, tracked in T5.
