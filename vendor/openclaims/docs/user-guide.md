# OpenClaims User Guide

This guide is for people using OpenClaims events, the CLI, SDKs, or collector.

## What OpenClaims Does

OpenClaims records provenance for material claims:

- what claim was emitted;
- which source and evidence units bear on it;
- which tool runs produced or retrieved evidence;
- how the claim was verified, disputed, or retracted;
- which digest identifies the exact event payload.

OpenClaims does not decide whether a claim is universally true. It records evidence, support type, verification state, and audit metadata.

## Install

From the repo root:

```sh
pnpm install
```

The Python SDK can be installed from the local package:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install './python[test]'
```

## CLI

Validate all bundled fixtures:

```sh
node packages/validator-cli/src/index.js fixtures
```

Validate one event:

```sh
node packages/validator-cli/src/index.js validate fixtures/valid/claim-emitted.json
```

Inspect one event:

```sh
node packages/validator-cli/src/index.js inspect fixtures/valid/claim-emitted.json
```

Compute or verify a digest:

```sh
node packages/validator-cli/src/index.js digest fixtures/valid/claim-emitted.json
node packages/validator-cli/src/index.js verify-digest fixtures/valid/claim-emitted.json
```

Export JSON-LD:

```sh
node packages/validator-cli/src/index.js export-jsonld fixtures/valid/claim-emitted.json
```

## Collector

Start the reference collector:

```sh
node packages/collector/src/index.js
```

Default storage is SQLite at `data/openclaims-events.sqlite`. For in-memory development:

```sh
OPENCLAIMS_MEMORY=1 node packages/collector/src/index.js
```

Useful endpoints:

- `GET /health`
- `POST /v0/events`
- `POST /v0/cloudevents`
- `GET /v0/events/:event_id`
- `GET /v0/claims/:claim_id`
- `GET /v0/claims/:claim_id/events`

Example ingest:

```sh
curl -sS -X POST http://127.0.0.1:8787/v0/events \
  -H 'content-type: application/json' \
  --data-binary @fixtures/valid/claim-emitted.json
```

## TypeScript SDK

```js
import {
  agent,
  createClaim,
  createClaimEmittedEvent,
  validateEvent
} from "@openclaims/typescript-sdk";

const producer = agent({
  id: "urn:service:assistant-api",
  type: "service",
  name: "Assistant API"
});

const claim = createClaim({
  text: "The policy requires manager approval.",
  claim_type: "factual",
  asserted_at: "2026-05-17T00:00:00Z"
});

const event = createClaimEmittedEvent({ producer, claim });
const result = validateEvent(event);
```

## Python SDK

```python
from openclaims import create_claim, create_claim_emitted_event, validate_event

producer = {
    "agent_id": "urn:service:assistant-api",
    "agent_type": "service",
    "name": "Assistant API",
}

claim = create_claim(
    text="The policy requires manager approval.",
    claim_type="factual",
    asserted_at="2026-05-17T00:00:00Z",
)

event = create_claim_emitted_event(producer=producer, claim=claim)
validate_event(event)
```

## Event Lifecycle

A typical claim history is:

1. `claim.emitted`
2. `claim.verified`
3. `claim.disputed`
4. `claim.retracted`

Events are additive. A retraction does not delete earlier evidence or verification; it appends a new lifecycle event.
