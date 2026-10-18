# OpenClaims v0.1 Verification

Verification is a post-generation assessment of a claim at a point in time. It does not rewrite the emitted claim and does not imply permanent truth.

The v0.1 model deliberately separates three dimensions:

- `verification_result`: `supported`, `contradicted`, or `inconclusive`
- `verification_method`: `human_review`, `model_check`, `source_attestation`, `consensus`, or `formal_proof`
- `claim_status`: `active`, `disputed`, or `retracted`

`claim.verified` requires a `verification` object. `claim.disputed` should normally include `verification_result: "contradicted"` and `claim_status: "disputed"`, but the event-level requirement is only contradicting evidence or a dispute rationale so producers can record unresolved disputes.

Verification applies to `claim_ref` at `verified_at`. Later verification, dispute, or retraction events are appended rather than overwriting earlier events.
