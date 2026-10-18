# Provenance: vendored OpenClaims v0.1 assets

## Source

- Repository: https://github.com/openclaims-ai/openclaims
- Pinned commit: `3bd7f0ba17f27a23e1652b39d6f65f2972b99d43`
- Retrieved: 2026-09-27 (via `git clone`, shallow)
- GitHub metadata observed at retrieval: created 2026-05-18, last push 2026-05-20

## What is vendored

- `schemas/` — JSON Schema (draft 2020-12) files for ClaimEvent and related types
- `fixtures/` — conformance fixtures (`valid/` and `invalid/`)
- `spec/` — human-readable v0.1 specification
- `conformance/` — conformance test material
- `docs/` — supporting documentation

These assets are **data and specification**, not executable code. They are
used unmodified by `tools/ocl` for schema validation and the conformance
suite (`ocl conform`).

## License status (important)

- The repository has **no LICENSE file** at the pinned commit.
- `python/pyproject.toml` declares `license = { mi = ... }`-style MIT in its
  metadata only (observed: MIT declared in package metadata).
- Absent an explicit repository license, default copyright applies to the
  code. Vendoring of spec/schema/fixtures here is done for
  interoperability testing (reproducing reference digests) within this
  project; upstream issue filed requesting a LICENSE file and maintenance
  status clarification (see linked issue in git history / GitHub).

## Clean-room boundary

`tools/ocl/jcs.py` and `tools/ocl/ocl_validate.py` were **re-implemented**
from the v0.1 specification and observable fixture behavior (digest
reproduction), not copied from the TypeScript reference implementation.
Reference sources consulted for behavior only:
`packages/typescript-sdk/src/canonicalize.js`, `validate.js`.

## Update policy

Re-vendor by re-cloning at a new commit, diffing `schemas/` and
`fixtures/`, and re-running `tools/ocl/ocl conform`. Do not edit vendored
files in place.
