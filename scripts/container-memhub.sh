#!/bin/bash
# container-memhub.sh — boot/keep artifact for the containerized hub
# (T6 Phase A). Idempotent: safe at login and re-run. apple/container
# has no restart policy in this CLI version, so a LaunchAgent calls this
# at login: start the system service, recreate memhub if missing.
set -euo pipefail
REPO="${MEM_REPO:-/Volumes/work/OpenFox/Memory_Knowledge}"
IMAGE="${MEM_IMAGE:-local/mem:0.1}"
HOST_PORT="${MEM_HOST_PORT:-18520}"   # 8520 free it on the mini

container system start >/dev/null 2>&1 || true
if container list -q 2>/dev/null | grep -q memhub; then
  container start memhub 2>/dev/null || true
else
  container stop memhub >/dev/null 2>&1 || true
  container delete memhub >/dev/null 2>&1 || true
  container run --memory 256m --cpus 1 --detach \
    --publish "${HOST_PORT}:8520/tcp" \
    --volume "$REPO/memory:/memory" \
    --name memhub "$IMAGE" >/dev/null
fi
echo "memhub: $(container list 2>/dev/null | awk '$1=="memhub"{print $6, $7}')"
