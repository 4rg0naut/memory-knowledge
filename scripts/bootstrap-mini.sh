#!/bin/bash
# bootstrap-mini.sh — fresh macOS on the mini -> fleet hub in one run (T5).
# Every step below was performed ad-hoc between 2026-09-27 and 2026-10-04;
# incident-born lines cite their ADR/claim. Idempotent: re-run is safe.
# Usage: sudo ./bootstrap-mini.sh [--dry-run]
set -euo pipefail
DRY=""
[ "${1:-}" = "--dry-run" ] && DRY=echo

run() { $DRY "$@"; }
ts() { echo "[bootstrap-mini] $*"; }

REPO_URL="mini:~/git/Memory_Knowledge.git"   # on a rebuild use the hub copy
WORKDIR="$HOME/Memory_Knowledge"

# 1. Never sleep (C1: hub must answer on the tailnet at any hour).
run sudo pmset -a sleep 0
run sudo pmset -a disablesleep 1

# 2. Service user (ADR-0003 memsvc isolation). 451 = the uid chosen
#    2026-09-29; keep it stable so file ownership survives rebuilds.
if ! dscl . -read /Users/memsvc &>/dev/null; then
  run sudo dscl . -create /Users/memsvc UniqueID 451
  run sudo dscl . -create /Users/memsvc PrimaryGroupID 20
  run sudo dscl . -create /Users/memsvc NFSHomeDirectory /Users/operator/mem-home
  run sudo dscl . -create /Users/memsvc UserShell /usr/bin/false
  run sudo mkdir -p /Users/operator/mem-home
  run sudo chown memsvc /Users/operator/mem-home
fi

# 3. Repo + hub remote.
if [ ! -d "$WORKDIR/.git" ]; then
  run git clone "$REPO_URL" "$WORKDIR"
fi
run git -C "$WORKDIR" remote add mini "$REPO_URL" 2>/dev/null || true
# git refuses repos owned by another user; the chown below made memsvc a
# second owner of the working tree (root-ownership mess, ADR-0003).
run git config --global --add safe.directory "$WORKDIR"

# 4. Memory root: memsvc owns; staff group gets WRITE — T5 lesson
#    (ISSUES-f): with group read-only, `git pull` in operator's clone fails
#    on memory/ files. Isolation that matters stays: non-staff users and
#    every network client cannot write (service + tag:mem-writer port
#    remain the gates, ADR-0003/0006).
run sudo chown -R memsvc:staff "$WORKDIR/memory"
run sudo chmod -R g+w,o-w "$WORKDIR/memory"

# 5. LaunchDaemon (system, runs as memsvc). Note for all future edits:
#    launchd caches the definition at load — editing the plist alone does
#    nothing; bootout/bootstrap or kickstart -k to reload (ISSUES ledger,
#    openfox-session-2026-10-04 turn 44).
PLIST=/Library/LaunchDaemons/uk.4rg0naut.mem.serve.plist
run sudo cp "$WORKDIR/deploy/mini/uk.4rg0naut.mem.serve.daemon.plist" "$PLIST"
run sudo chown root:wheel "$PLIST"
if launchctl print system/uk.4rg0naut.mem.serve &>/dev/null; then
  run sudo launchctl kickstart -k system/uk.4rg0naut.mem.serve
else
  run sudo launchctl bootstrap system "$PLIST"
fi

# 6. Hub bare repo for git sync from other machines.
[ -d "$HOME/git/Memory_Knowledge.git" ] || run git init --bare "$HOME/git/Memory_Knowledge.git"

ts "done. verify: launchctl print system/uk.4rg0naut.mem.serve | head"
