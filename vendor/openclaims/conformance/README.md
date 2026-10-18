# OpenClaims Conformance

OpenClaims v0.1 conformance is fixture-driven.

Core conformance requires an implementation to:

- validate `fixtures/valid/*.json`;
- reject `fixtures/invalid/*.json`;
- compute the same SHA-256 base64url event digests as the fixtures;
- preserve additive claim history for emitted, verified, disputed, and retracted events;
- map JSON events into the JSON-LD profile without changing OpenClaims IDs.

Recommended checks:

- reject duplicate `event_id` values in a replay set;
- require a prior `claim.emitted` before verification, dispute, or retraction;
- reject events after `claim.retracted`;
- require `claim.disputed` to include contradicting evidence or `dispute_rationale`;
- require `claim.retracted` to include `retracted_at`.

The reference implementation exercises these rules in `scripts/verify-collector.mjs`.
