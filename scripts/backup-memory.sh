#!/bin/bash
# backup-memory.sh — timestamped snapshot of the memory root (T5).
# Git history is the primary timeline; this guards against a bad
# bulk operation between pushes (a force-mirror could otherwise pin a
# mistake everywhere — append-only discipline, AGENTS.md rule 4).
# Usage: ./backup-memory.sh [path...]   (default: memory/ + claims/)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGETS=("${@:-$REPO/memory $REPO/claims}")
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${MEM_BACKUP_DIR:-$HOME/backups/memory}"
mkdir -p "$DEST"
TARBALL="$DEST/memory-$STAMP.tar.gz"
tar -czf "$TARBALL" -C "$REPO" "${TARGETS[@]// $REPO\//}" \
  2>/dev/null || tar -czf "$TARBALL" -C "$REPO" memory claims
HASH=$(shasum -a 256 "$TARBALL" | cut -d' ' -f1)
echo "backup: $TARBALL"
echo "sha256: $HASH"
# keep last 30
ls -1t "$DEST"/memory-*.tar.gz 2>/dev/null | tail -n +31 | \
  xargs -r rm -f
