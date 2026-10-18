# OpenClaims v0.1 Signing And Auditability

v0.1 implements content-addressed event digests and hash-chain slots. Full DSSE/in-toto envelope signing is documented as a profile target and deferred until the core digest behavior is stable.

## Canonicalization

The event digest is computed over canonical JSON with the `digest` field removed. The reference implementation uses:

- RFC 8785-style key ordering and insignificant whitespace removal.
- SHA-256.
- base64url encoding.

## Digest Shape

```json
{
  "algorithm": "sha256",
  "encoding": "base64url",
  "value": "..."
}
```

## Auditable Trace

`auditable_trace` may include:

- `event_ids`
- `hash_chain`
- `signature_refs`

Future DSSE/in-toto support should sign a statement binding event IDs, event digests, and subjects. C2PA packaging remains a later export profile for durable assets such as PDFs and reports.
