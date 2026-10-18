# Roundtrip: conversation capture → claims ledger → dispute

Demonstrates the full claim-provenance discipline. Published with the
sanitized Harbor Robotics demo data (ADR-0013): the walkthrough below is
byte-identical on any fresh clone — every artifact it references is in
this tree, and the claim ids are content-derived.

Store: `claims/claims.jsonl`. Capture:
`knowledge/inbox/harbor-devday-2026-10-16.md`. Evidence snapshot:
`knowledge/evidence/harbor-devday-post-2026-10-16.json` (sha256,
base64url `2edRYNPZOWg86Fbh9ufed87seJUj4u6ASj5nY3yY2mo`).

## Steps

1. **Capture** — a DevDay conversation summary is manually captured to
   `knowledge/inbox/harbor-devday-2026-10-16.md` (paraphrase; fidelity
   caveats noted in the file, per inbox-is-raw discipline).
2. **Evidence snapshot** — the primary post is re-fetched and pinned to
   `knowledge/evidence/harbor-devday-post-2026-10-16.json`; its sha256
   becomes the `source_digest` on every emitted event.
3. **Emit** — four atomic claims via `ocl emit`, each single-fact,
   typed, with `source_uri` + `source_digest` + selector:
   - R300 unveiled at DevDay 2026 (`factual`)
   - Nimbus-12 pairs two dies, 128 GB unified memory (`factual`)
   - up-to-22% fleet-cost cut vs R200 (`inference`: vendor
     self-report, not independently measured)
   - "no operator overtime in Q3" (`factual` as stated by the post)
4. **Verify** — claim 1 gets `supported` via `source_attestation`
   against the pinned evidence.
5. **Dispute** — claim 4 is disputed with rationale: the Q3 incident
   log lists two weekend runs, at odds with "no overtime".

## Why this exercises the discipline

- The shaky assertion ("no operator overtime") is *caught, attributed,
  disputed with citable evidence, and kept in the ledger* — never
  silently corrected. `ocl check <ref>` replays emitted → disputed with
  the refuting rationale visible (disputed-is-visible rule).
- Vendor self-reported savings are typed `inference`, not `factual`, so
  downstream readers see the epistemic grade in the citation tag.
- `ocl query --cite` emits `[claim:<id>|<result>/<method>]` tags for
  context injection (see AGENTS.md).

## Reproduce

```sh
cd tools/ocl
python ocl.py --store ../../claims/claims.jsonl chain --verify
python ocl.py --store ../../claims/claims.jsonl query --cite
python ocl.py --store ../../claims/claims.jsonl check \
    clm_065b52096c9442c2b3d5fb0310
```

Regenerate the whole demo layer (memory home + this ledger) from source:

```sh
tools/mem/.venv/bin/python scripts/make-demo-home.py
```
