# OpenClaims v0.1 Facets

Facets are optional metadata objects attached to core entities. They allow vendors and domains to extend OpenClaims without changing the core schema.

Every facet must include:

- `_producer`: the SDK, service, or organization that produced the facet.
- `_schemaURL`: an immutable schema URL for that facet version.

Facet containers are available on agents, claims, sources, evidence, tool runs, verification records, and selected events. Same-name facets should be treated as replacement objects rather than partial merges.

Selectors are not facets in v0.1. Evidence location is first-class through `Selector` so RAG, document-grounded, table, API, and byte-range evidence can interoperate without vendor-specific extensions.
