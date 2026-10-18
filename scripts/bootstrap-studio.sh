#!/bin/bash
# bootstrap-studio.sh — fresh macOS on the Studio (captain) -> fleet
# member in one run (T5). Idempotent. Usage: ./bootstrap-studio.sh [--dry-run]
set -euo pipefail
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY=echo
run() { $DRY "$@"; }
ts() { echo "[bootstrap-studio] $*"; }

WORKDIR="$HOME/Memory_Knowledge"
REPO_URL="mini:~/git/Memory_Knowledge.git"

# 1. SSH key for tailnet automation (no passphrase — tradeoff recorded
#    in infra/README.md C1: automation-usable, tailnet-scoped blast radius).
[ -f ~/.ssh/id_ed25519 ] || run ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

# 2. ~/.ssh/config hosts (tailnet names, NOT LAN IPs — LAN IP pins broke
#    once already; see infra/README LAN-IP note, ADR-0009).
if ! grep -q "Host mini" ~/.ssh/config 2>/dev/null; then
  run tee -a ~/.ssh/config <<'EOF'

Host mini
    HostName mini.net01.ts.net
    User operator

Host studio
    HostName captain.net01.ts.net
    User operator
EOF
fi

# 3. Repo + hub remote.
[ -d "$WORKDIR/.git" ] || run git clone "$REPO_URL" "$WORKDIR"
run git -C "$WORKDIR" remote add mini "$REPO_URL" 2>/dev/null || true
# Divergent writes between machines are expected (both emit claims);
# merge, don't rebase — the vim-merge trap (double-edit conflict mess of
# 2026-09-29) is why pull.rebase=false is pinned explicitly.
run git -C "$WORKDIR" config pull.rebase false

# 4. Local mem LaunchAgent (read+write loopback, 8520).
run launchctl bootstrap gui/$(id -u) "$WORKDIR/deploy/studio/uk.4rg0naut.mem.serve.plist" 2>/dev/null || \
  run launchctl kickstart -k gui/$(id -u)/uk.4rg0naut.mem.serve

ts "done. remind user: set SEARXNG_URL=https://mini.net01.ts.net/searx in OpenFox app env (one string, ISSUES-d)"
