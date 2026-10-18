# OpenClaims v0.1 Core Model

OpenClaims records claim provenance as append-only events. It does not determine truth; it records claim text, source material, evidence selectors, tool runs, verification outcomes, lifecycle status, and audit digests.

## Event Envelope

Every event uses `BaseEvent.schema.json` and requires:

- `event_id`
- `event_type`
- `event_time`
- `spec_version`
- `schema_url`
- `producer`
- `claim` or `claim_ref`
- `digest`

The canonical entrypoint is `schemas/openclaims/0.1/ClaimEvent.schema.json`, a `oneOf` union over:

- `ClaimEmittedEvent.schema.json`
- `ClaimVerifiedEvent.schema.json`
- `ClaimDisputedEvent.schema.json`
- `ClaimRetractedEvent.schema.json`

## Core Objects

The shared model is defined in `Core.schema.json`:

- `Agent`: human, organization, service, model, or pipeline actor.
- `Claim`: material proposition with `claim_type`, `asserted_at`, optional `valid_at`, and claim-to-claim relations.
- `Source`: origin object such as a document, URI, API response, or dataset item.
- `Evidence`: concrete unit from a source, linked by selector and `support_type`.
- `Selector`: first-class location descriptor such as `text_span`, `page_span`, `json_pointer`, `table_cell`, `uri_fragment`, or `byte_range`.
- `ToolRun`: reproducibility metadata for retrievers, models, tools, APIs, and verifiers.
- `Verification`: decomposed result, method, lifecycle status, validator, and timestamp.
- `Digest`: SHA-256 over canonical JSON, encoded as base64url.
- `AuditableTrace`: event IDs, hash chain entries, and signature references.

## Event Types

- `claim.emitted`: introduces a claim and any initial sources, evidence, tool runs, or trace data.
- `claim.verified`: records a verification activity for an existing claim.
- `claim.disputed`: records contradiction or unresolved dispute; requires contradicting evidence or a rationale.
- `claim.retracted`: records additive withdrawal; requires `retracted_at`.
