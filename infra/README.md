# Fleet status (C1) — honest ledger

Snapshot 2026-09-27 (rev 2) on the Studio (host `studio`, 192.0.2.76;
identifiers sanitized for publication per ADR-0013). C1 is
**partially complete**: repo-side + Studio-local groundwork done; the
cross-machine layer needs sign-in/sudo on the mini.

## Done

- Container/networking policy: `docs/container-policy.md` (C9).
- One-env config discipline: every consumer takes exactly one `*_URL`
  (`OCL_URL` proven working in `docs/networking.md`).
- `ocl serve` runs as a plain process today; launchd plist pattern is the
  next step and needs no network.
- **ed25519 keypair generated on Studio** (`~/.ssh/id_ed25519`, no
  passphrase — automation-usable on the tailnet; tradeoff noted).
- **`~/.ssh/config` populated** with `studio` / `mini` / `github.com`
  hosts (mini `HostName` is a placeholder until the tailnet name is known).
- **Tailscale verified live from this session** (2026-09-27, user had
  already installed it on all machines): network extension activated +
  connected; 4 peers — `captain` (this Studio, 198.51.100.87), `oldmini`
  (Mac mini M4, 198.51.100.73), `mba-m4`, `p11-pro`. `oldmini` pings and
  its SSH port is open. `~/.ssh/config` now uses tailnet names. (The
  earlier "`tailscale` not installed" reading was wrong: the app doesn't
  put a CLI on PATH; use `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.)

## Pending user actions (small)

| Item | Where | Why blocked |
|---|---|---|
| Authorize Studio pubkey on mini | mini | DONE 2026-09-27/29 (passwordless `ssh mini` verified from Studio session) |
| `pmset sleep 0` + `disablesleep 1` on mini | mini | DONE (`SleepDisabled 1` confirmed) |
| git bare hub on mini + `git remote add mini` | mini | DONE (`~/git/Memory_Knowledge.git`, push/pull both ways live) |
| SearXNG instance + `SEARXNG_URL` | mini | DONE 2026-10-04 (see below); only the OpenFox app-env string awaits user |

## SearXNG (installed + verified 2026-10-04)

- Engine: SearXNG 2026.10.4 built from commit `d48c4b555`
  (`pip install "git+https://github.com/searxng/searxng@d48c4b555"` —
  repo has no release tags; the commit is embedded in the version
  string; pre-install `msgspec pyyaml flask babel jinja2 httpx lxml
  typer uvicorn setproctitle fastapi` then use `--no-build-isolation`) in
  `~/searxng/venv` (python 3.12) on the mini; no Docker, per C9.
- Runs as LaunchAgent `uk.4rg0naut.searxng.serve` (KeepAlive), bound
  `0.0.0.0:8888`; survives `kickstart -k` restart (cold start ~30 s
  engine load). Artifacts: `deploy/mini/searxng.serve.plist`,
  `deploy/mini/searxng.settings.yml.example` (JSON format enabled,
  limiter off).
- Verified: `http://192.0.2.48:8888/search?q=openclaims+spec&format=json`
  → 10 results, all engines responsive; recorded as ledger claim
  `clm_1b8a26157d014be9a36df3677e` (supported/source_attestation).
- LAN-IP pin: `192.0.2.48` assumes the mini's DHCP reservation on the
  router (confirm there; not verifiable from the host). If the lease ever
  changes: update `SEARXNG_URL` in `searxng.serve.plist` + `server.url` in
  settings, `launchctl kickstart -k`, then re-point the app string. The
  tailnet HTTPS path below is IP-independent — prefer it once done.
- Wire-up for OpenFox (user, one string): set
  `SEARXNG_URL=https://mini.net01.ts.net/searx` (verified 2026-10-04;
  LAN interim was `http://192.0.2.48:8888`).
- Graduations: raw `tailnet:8888` dials time out (stateful direct-path
  quirk). DONE 2026-10-04 (T5, re-scoped): the tailnet ACL only opens
  tcp:443, so both services ride 443 as path mounts on the node's
  valid cert name `mini.net01.ts.net` (the `oldmini` name in older
  notes is stale; DNS works via the system resolver):
  `tailscale serve --https=443 --set-path=/searx 127.0.0.1:8888` and
  `--set-path=/mem 127.0.0.1:8520`. Verified from Studio:
  `https://mini.net01.ts.net/searx/search?q=...&format=json` →
  20 results; `/mem/healthz` → ok. App string becomes
  `SEARXNG_URL=https://mini.net01.ts.net/searx`. The `:8443`
  mapping also exists but stays dark until the ACL opens extra ports
  (apply `infra/tailscale-policy.json` via API when a key exists —
  ISSUES-b/g; `tcp:8521` writes are similarly blocked today, writes
  between machines still ride git sync).
  Tailnet key expiry still default (all peers ~2027-03/04) — disable in
  admin console if zero-touch is wanted.

## Runbook

Historical — all steps executed (2026-09-29 → 2026-10-04); kept for
rebuilds of a new node.

## Graduations (documented in container-policy, not required)

Headscale on VPS → self-hosted control plane; Cloudflare Tunnel → public
services only.

Cloudflare side is live and connected (verified 2026-09-27 via MCP):
account on **Free** plan, zone `4rg0naut.uk` active; Workers deployable,
secrets manageable (`cf-vault_*` tools). Ready for the public-layer
graduation when a service needs it.
