# Verified Analysis Demo

The Verified Analysis demo is a deterministic, zero-network proof of the OpenClaims workflow:

```text
question -> document-grounded answer -> claims -> evidence -> tool run -> verification -> lifecycle events
```

It uses a bundled travel-policy corpus and emits schema-valid OpenClaims v0.1 events. There is no model call, live retrieval API, hosted collector, or external network dependency.

## Run the Demo

```sh
pnpm demo:verified-analysis
```

The runner writes:

- `examples/verified-analysis/output/event-history.json`
- `examples/verified-analysis/output/embedded-response.json`
- `examples/verified-analysis/output/jsonld.json`
- `examples/verified-analysis/output/cloudevents.json`
- `site/assets/verified-analysis-demo.json`

The landing page uses `site/assets/verified-analysis-demo.json`, so the browser demo reflects the same generated fixture shape.

Check that the committed outputs are still in sync with the deterministic generator:

```sh
pnpm demo:verified-analysis:check
```

`pnpm test` runs this check automatically.

## Validate the Output

The runner validates every generated event and verifies every event digest before writing output.

You can also inspect events manually by splitting or copying an individual event from `event-history.json` and running:

```sh
node packages/validator-cli/src/index.js validate <event-file>
node packages/validator-cli/src/index.js verify-digest <event-file>
node packages/validator-cli/src/index.js export-jsonld <event-file>
```

## What This Proves

- OpenClaims can represent material claims from an AI-style answer.
- Evidence is connected to concrete selectors and source digests.
- Tool runs are captured without raw prompts or external service dependency.
- Verification and dispute lifecycle events are additive.
- The same generated records can drive a user-facing evidence panel and machine-readable exports.
