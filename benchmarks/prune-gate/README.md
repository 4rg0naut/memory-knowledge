# Prune-gate benchmark (C8)

Question: on the local stack (macOS `fm` Foundation Model + oMLX host +
Vision framework), does a cheap dichotomous text-presence gate that prunes
empty image regions before transcription beat naive full-image VLM
transcription on calls/wall-time/quality?

Pattern intentionally generalizes: a small LLM answers a *binary* question
per region; an OCR-accurate non-LLM tool handles only surviving regions.

## Arms

- **A naive** — 1 `fm respond --image full` transcription per image.
- **B pruned** — `quadcrop` (4 quadrants) → `fm` binary gate per quadrant
  (YES/NO) → macOS Vision `.accurate` OCR only on YES quadrants.

Ground truth: Vision `.accurate` on the full image. Quality metric:
word-recall vs that reference.

## Suite

9 PNGs on the Studio (3840px): 6 real screen captures (window text,
IDE/browser chrome), 3 synthetic document renderings with known text.

## Usage

```sh
swiftc -O vision_ocr.swift -o vision_ocr
swiftc -O quadcrop.swift -o quadcrop
python3 run_bench.py            # writes results.json, prints summary
```

## Results

See `results.json` (summary block) and `REPORT.md` (analysis + claims
recorded into the ledger).
