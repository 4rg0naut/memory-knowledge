# OpenClaims v0.1 Transport

OpenClaims defines transport-neutral JSON events plus two v0.1 profiles: embedded response metadata and CloudEvents.

## JSON Profile

The JSON profile is the normative operational representation. Each event validates against `ClaimEvent.schema.json`, carries `spec_version: "0.1.0"`, and includes a `digest` computed over the event with the `digest` field removed.

## Embedded Response Profile

Applications may include provenance next to their native response payload:

```json
{
  "payload": {},
  "openclaims": {
    "spec_version": "0.1.0",
    "events": []
  }
}
```

## CloudEvents Profile

CloudEvents wrapping maps:

- `id` to `event_id`
- `type` to `event_type`
- `source` to producer URI or ID
- `time` to `event_time`
- `datacontenttype` to `application/json`
- `data` to the full OpenClaims event

The collector accepts this shape at `POST /v0/cloudevents`.

## Ordering

OpenClaims event history is additive. Consumers reconstruct claim state by claim ID and event time, preserving all prior verification, dispute, and retraction events.
