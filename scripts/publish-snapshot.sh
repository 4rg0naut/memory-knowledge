#!/usr/bin/env bash
# publish-snapshot.sh — export a sanitized public snapshot and push it
# to origin (ADR-0013). Never pushes local git history: the exported
# tree becomes a single initial commit on origin/main. The mini hub
# keeps the full history and the production memory home.
#
# Usage: scripts/publish-snapshot.sh [--dry-run] [--no-push]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DRY=""
PUSH=1
[ "${1:-}" = "--dry-run" ] && DRY=1
[ "${1:-}" = "--no-push" ] && PUSH=0

OUT=$(mktemp -d)/memory-knowledge-public
ts() { echo "[publish-snapshot] $*"; }

ts "exporting working tree -> $OUT"
rsync -a \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude '.DS_Store' --exclude '.pytest_cache' \
  --exclude 'tmp-export-test' --exclude '*.tmp' \
  --exclude 'demo/.build' \
  --exclude 'benchmarks/prune-gate/work' \
  --exclude 'benchmarks/prune-gate/quadcrop' \
  --exclude 'benchmarks/prune-gate/vision_ocr' \
  "$ROOT/" "$OUT/"

ts "substituting demo data for production captures"
rm -rf "$OUT/memory"
rm -rf "$OUT/knowledge"
cp -R "$OUT/demo/knowledge" "$OUT/knowledge"
rm -f "$OUT/claims/claims.jsonl"
cp "$OUT/demo/claims/claims.jsonl" "$OUT/claims/claims.jsonl"
: > "$OUT/claims/spool.jsonl"
rm -f "$OUT/benchmarks/prune-gate/results.json"
rm -f "$OUT"/benchmarks/prune-gate/images/real*.png
rm -f "$OUT"/demo/claims/claims.jsonl && rmdir "$OUT/demo/claims"

ts "PII gate on the exported tree (strict)"
python3 "$ROOT/scripts/check-pii.py" --strict --root "$OUT"

# demo/sources stay (raw inputs behind demo/memory); demo/memory too.
if [ -n "$DRY" ]; then
  ts "dry-run: leaving tree at $OUT for inspection"
  exit 0
fi

ts "single-commit history"
(
  cd "$OUT"
  git init -q -b main
  git add -A
  git -c user.name="4rg0naut" -c user.email="4rg0naut@users.noreply.github.com" \
    commit -q -m "Memory_Knowledge: sanitized public snapshot ($(date -u +%Y-%m-%d))

Fresh-history publication per ADR-0013: demo data replaces production
captures; PII gate (scripts/check-pii.py --strict) green on this tree.
Full history and production memory home remain on the private hub."
)

if [ "$PUSH" = "1" ]; then
  ORIGIN_URL="${PUBLISH_ORIGIN:-https://github.com/4rg0naut/memory-knowledge.git}"
  git -C "$OUT" remote add origin "$ORIGIN_URL"
  ts "pushing snapshot to origin/main (forced; history never published)"
  git -C "$OUT" push -f origin main
  ts "done: https://github.com/4rg0naut/memory-knowledge"
else
  ts "--no-push: snapshot committed locally at $OUT"
fi
