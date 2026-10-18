#!/usr/bin/env python3
"""Prune-gate benchmark: naive full-image VLM transcription vs a
dichotomous text-presence gate that prunes empty quadrants before OCR.

Arms (per image):
  A naive   : fm respond --image full --text "transcribe verbatim"   (1 fm call)
  B pruned  : quadcrop -> per-quadrant fm binary gate YES/NO (4 fm calls)
              -> YES quadrants only through macOS Vision OCR (0 fm calls)

Reference text: Vision OCR of the full image (accurate tier).
Metrics: fm call count, wall time, word-recall vs reference.

Run: python3 run_bench.py [--images dir] [--out results.json]
"""

import argparse
import json
import os
import re
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIBE = "Transcribe all visible text verbatim. Output only the text."
GATE = "Does this image contain any legible text or characters? Answer with exactly one word: YES or NO."


def fm_respond(image, prompt):
    start = time.monotonic()
    proc = subprocess.run(
        ["fm", "respond", "--no-stream", "--image", image, "--text", prompt],
        capture_output=True, text=True,
    )
    return proc.stdout.strip(), time.monotonic() - start


def vision_ocr(image):
    bin_path = os.environ.get("VISION_OCR",
                              os.path.join(HERE, "vision_ocr"))
    proc = subprocess.run(
        [bin_path, image], capture_output=True, text=True
    )
    return proc.stdout.strip()


def quadcrop(image, outdir):
    proc = subprocess.run(
        [os.path.join(HERE, "quadcrop"), image, outdir], capture_output=True, text=True
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def words(text):
    return set(re.findall(r"[A-Za-z0-9$%.]{3,}", text.lower()))


def recall(reference, candidate):
    ref = words(reference)
    if not ref:
        return 1.0
    return len(ref & words(candidate)) / len(ref)


def run_image(path, workdir):
    reference = vision_ocr(path)

    out_a, t_a = fm_respond(path, TRANSCRIBE)
    arm_a = {
        "fm_calls": 1,
        "seconds": round(t_a, 2),
        "recall": round(recall(reference, out_a), 3),
        "output": out_a,
    }

    quads = quadcrop(path, workdir)
    t_b = 0.0
    calls = 0
    texts = []
    for q in quads:
        answer, dt = fm_respond(q, GATE)
        calls += 1
        t_b += dt
        if "YES" in answer.upper():
            ocr_start = time.monotonic()
            texts.append(vision_ocr(q))
            t_b += time.monotonic() - ocr_start
    arm_b = {
        "fm_calls": calls,
        "vision_calls": len(texts),
        "kept": len(texts),
        "of": len(quads),
        "seconds": round(t_b, 2),
        "recall": round(recall(reference, "\n".join(texts)), 3),
    }
    return {"image": os.path.basename(path), "reference": reference, "A_naive": arm_a, "B_pruned": arm_b}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", default=os.path.join(HERE, "images"))
    ap.add_argument("--out", default=os.path.join(HERE, "results.json"))
    ap.add_argument("--vision-only", action="store_true",
                    help="no fm: OCR every image with macOS Vision and "
                    "score against ground-truth text files (synth suite); "
                    "reproducible on any macOS host from a clean clone")
    args = ap.parse_args()
    work = os.path.join(HERE, "work")
    os.makedirs(work, exist_ok=True)
    images = sorted(
        os.path.join(args.images, f)
        for f in os.listdir(args.images)
        if f.lower().endswith(".png")
    )
    if args.vision_only:
        rows, recalls = [], []
        for p in images:
            ocr = vision_ocr(p)
            stem = os.path.splitext(os.path.basename(p))[0]
            gt_file = os.path.join(HERE, "synth%s.txt" % stem.lstrip("s")) \
                if stem.startswith("s") else None
            gt = open(gt_file, encoding="utf-8").read() if gt_file and \
                os.path.exists(gt_file) else None
            row = {"image": os.path.basename(p), "ocr_words":
                   len(words(ocr))}
            if gt is not None:
                r = round(recall(gt, ocr), 3)
                row["gt"], row["recall"] = os.path.basename(gt_file), r
                recalls.append(r)
            rows.append(row)
        summary = {"arm": "vision-reference", "images": len(rows),
                   "scored": len(recalls),
                   "recall_mean": round(sum(recalls) / len(recalls), 3)
                   if recalls else None}
        print(json.dumps({"summary": summary, "results": rows}, indent=2))
        return
    results = [run_image(p, work) for p in images]
    summary = {
        "images": len(results),
        "A_fm_calls": sum(r["A_naive"]["fm_calls"] for r in results),
        "B_fm_calls": sum(r["B_pruned"]["fm_calls"] for r in results),
        "A_seconds": round(sum(r["A_naive"]["seconds"] for r in results), 1),
        "B_seconds": round(sum(r["B_pruned"]["seconds"] for r in results), 1),
        "A_recall_mean": round(sum(r["A_naive"]["recall"] for r in results) / len(results), 3),
        "B_recall_mean": round(sum(r["B_pruned"]["recall"] for r in results) / len(results), 3),
        "B_quads_kept": sum(r["B_pruned"]["kept"] for r in results),
        "B_quads_total": sum(r["B_pruned"]["of"] for r in results),
    }
    json.dump({"summary": summary, "results": results}, open(args.out, "w"), indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
