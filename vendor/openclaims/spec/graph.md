# OpenClaims v0.1 Graph Profile

OpenClaims has two first-class semantic representations:

- OpenClaims JSON Profile for operational event exchange.
- OpenClaims JSON-LD Profile for graph interchange.

The JSON-LD context is published at `schemas/openclaims/0.1/context/openclaims.jsonld`.

## PROV Mapping

- `Claim`, `Evidence`, and `Source` map to `prov:Entity`.
- `ToolRun`, `Inference`, and `Verification` map to `prov:Activity`.
- `Agent` maps to `prov:Agent`.
- Evidence-to-claim support uses OpenClaims terms such as `oc:supports` and `oc:contradicts`.

The reference exporter preserves OpenClaims IDs as stable `urn:openclaims:*` identifiers. JSON-LD consumers should treat graph export as semantic projection, not as a replacement for validating the original signed JSON event.
