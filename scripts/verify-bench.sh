#!/usr/bin/env bash
# verify-bench.sh — reproduce the published benchmark numbers from a
# clean clone (ADR-0013 publish layer). Deterministic mem-eval arm runs
# anywhere with python3 >= 3.9 (stdlib only); the prune-gate arm needs
# macOS + swiftc (Vision framework) and is skipped elsewhere with a note.
#
# Usage: scripts/verify-bench.sh [--skip-vision] [--update]
#   --update  rewrite benchmarks/expected_results.json from the measured
#             outputs (regeneration flow) instead of gating on them
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY="${PYTHON:-python3}"
SKIP_VISION=""
UPDATE=0
for a in "$@"; do
  case "$a" in
    --skip-vision) SKIP_VISION=1 ;;
    --update) UPDATE=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done
UPDATE_ARG=""
[ "$UPDATE" = "1" ] && UPDATE_ARG="--update"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== arm 1: mem eval (demo home, committed queryset, seed 42)"
cp -R "$ROOT/demo/memory" "$WORK/home"
(
  cd "$ROOT/tools/mem"
  MEM_HOME="$WORK/home" PYTHONPATH="$ROOT/tools/mem" "$PY" -m mem eval --seed 42
) > "$WORK/eval.json"

if [ -n "$SKIP_VISION" ] || [ "$(uname)" != "Darwin" ] \
   || ! command -v swiftc >/dev/null 2>&1; then
  echo "== arm 2: prune-gate vision-reference — SKIPPED (macOS + swiftc required)"
  "$PY" "$ROOT/scripts/compare_expected.py" "$WORK/eval.json" \
      "$ROOT/benchmarks/expected_results.json" --skip-prune $UPDATE_ARG
  exit $?
fi

echo "== arm 2: prune-gate vision-reference (macOS Vision, synthetic suite)"
swiftc -O "$ROOT/benchmarks/prune-gate/vision_ocr.swift" -o "$WORK/vision_ocr"
mkdir -p "$WORK/images"
cp "$ROOT"/benchmarks/prune-gate/images/s*.png "$WORK/images/"
(
  cd "$ROOT/benchmarks/prune-gate"
  VISION_OCR="$WORK/vision_ocr" "$PY" run_bench.py --vision-only \
      --images "$WORK/images"
) > "$WORK/prune.json"

"$PY" "$ROOT/scripts/compare_expected.py" "$WORK/eval.json" "$WORK/prune.json" \
    "$ROOT/benchmarks/expected_results.json" $UPDATE_ARG
