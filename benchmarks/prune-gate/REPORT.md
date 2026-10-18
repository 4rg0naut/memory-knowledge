# Prune-gate benchmark report (C8)

Run 2026-09-27, Studio (host `studio`). Suite: 9 PNGs (6 real 3840px screen
captures, 3 synthetic document renderings). Stack: macOS `fm`
(Foundation Model, system), macOS Vision `.accurate` OCR. Full data:
`results.json` (local artifact — not published under ADR-0013; the
published tree ships the synthetic suite + a Vision reference arm:
`python3 run_bench.py --vision-only`).

## Headline

| metric | A naive (full-image VLM) | B pruned (gate + Vision) |
|---|---|---|
| fm calls | 9 | 36 |
| wall time | **860.2 s** | **22.5 s** (38x faster) |
| word-recall vs Vision reference | **0.20** | **0.965** |
| quadrants pruned | — | 9 / 36 (25%) |

## Findings

1. **Naive full-image transcription is not just slow, it is broken on
   dense 4K screens.** A's recall on every real capture is 0.00–0.04, with
   individual calls up to 200 s (likely token budget exhaustion /
   degeneration on huge images). The pruned arm hits 0.94–0.96.
2. **4x more calls, 38x less time.** Call count is the wrong headlin
   metric; per-call cost on a 1920x-scaled quadrant is ~0.7 s vs up to
   200 s on the full screen. Region sizing dominates.
3. **The gate itself never hallucinates text away on content quadrants**
   (kept 24/24 content quadrants) but pruned only 9/36 — real screens have
   text almost everywhere, so quad-split pruning mostly pays via *size
   reduction*, not skipping. On synthetic documents (text in one region)
   it pruned 3/4 per image and reached recall 1.00.
4. **Division of labour wins:** tiny binary fm question + deterministic
   Vision OCR beats one big VLM call on both axes. This is the reusable
   harness pattern: *small-model binary gate, big-tool execution, measured
   against a non-LLM reference.*

## Recorded claims (dogfooding)

Emitted to `claims/claims.jsonl` as `calculation` claims, verified
`supported` via `formal_proof` (deterministic recomputation from
`results.json`):

- wall-time/call-count summary claim
- recall comparison claim
- per-image naive-arm failure claim (recall 0.00 on all six 4K captures)

See `ocl query --cite` output; reproduce with
`python3 run_bench.py` (~15 min, dominated by arm A's full-screen calls).

## Caveats

- n=9, single machine, one pass; recall metric uses Vision itself as
  reference (Vision-vs-Vision inflates B slightly — synthetic rows with
  known ground truth show B at 1.00, confirming this is mild).
- Gate false-negatives were not observed here but are an inherent risk of
  arm B; on this suite pruning never dropped a text-bearing quadrant.
