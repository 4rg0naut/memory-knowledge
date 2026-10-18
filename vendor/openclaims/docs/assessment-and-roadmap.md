# Assessment And Roadmap

This document captures the current v0.1 assessment: whether the implementation matches the research direction, why the problem matters, what adjacent standards already cover, and what should come next.

## Fit Against The Research Report

OpenClaims substantially meets the intended v0.1 MVP scope.

Implemented:

- split event schemas for `claim.emitted`, `claim.verified`, `claim.disputed`, and `claim.retracted`;
- core ontology objects for `Claim`, `Evidence`, `Source`, `ToolRun`, `Verification`, `Agent`, `Selector`, `Digest`, `AuditableTrace`, and facets;
- OpenLineage-style facet extensibility with `_producer` and `_schemaURL`;
- JSON Schema Draft 2020-12 as the normative validation format;
- decomposed verification semantics: `verification_result`, `verification_method`, and `claim_status`;
- first-class selectors: `text_span`, `page_span`, `json_pointer`, `table_cell`, `uri_fragment`, and `byte_range`;
- support semantics such as `supports_directly`, `supports_partially`, `computed_from`, `contradicts`, `context_only`, and `provenance_only`;
- SHA-256 base64url digests across TypeScript and Python;
- TypeScript SDK, Python SDK, validator CLI, JSON-LD exporter, Fastify collector, SQLite reference storage, fixtures, and conformance replay cases.

Still intentionally deferred:

- DSSE/in-toto envelope signing;
- C2PA packaging for durable exported assets;
- OpenTelemetry bridge for runtime span correlation;
- Kafka CloudEvents binding;
- sample RAG/chat/document-grounded integrations;
- broader TCK-style conformance suite.

The current codebase covers the foundation: schemas, event lifecycle, validation, SDK ergonomics, collector ingestion, and graph export. The remaining work is mostly ecosystem hardening and integration.

## Why The Problem Matters

The problem is significant because AI systems increasingly emit material claims in settings where provenance, source review, and auditability matter.

OpenClaims addresses a gap between decorative citations and inspectable claim accountability:

- claim-level granularity instead of document-level links;
- evidence selectors that identify the exact passage, row, JSON fragment, URI fragment, or byte range;
- explicit support semantics, including contradiction and context-only evidence;
- additive verification, dispute, and retraction lifecycle;
- tool provenance for retrievers, models, APIs, and verifiers;
- time-bound event, observation, assertion, and retraction metadata.

External pressure is increasing. The EU AI Act Article 50 defines transparency obligations for certain AI systems, including disclosure around AI interaction and synthetic/generated content, with the official text published as Regulation (EU) 2024/1689. See the European Commission AI Act Service Desk page for [Article 50](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50).

The cultural heritage sector is also treating provenance as a trust requirement. The Library of Congress highlighted a 2026 call to action for libraries, archives, and museums to keep digital collection content authentic, transparent, and verifiable across its lifecycle. See the Library of Congress post, [Content Authenticity and Provenance in the Age of Artificial Intelligence](https://blogs.loc.gov/thesignal/2026/04/content-authenticity-and-provenance-in-the-age-of-artificial-intelligence-a-call-to-action-for-the-libraries-archives-and-museums-community/).

## Adjacent Standards

OpenClaims is not a replacement for existing standards. It is a claim-specific layer that reuses them where they are strong.

| Standard | Covers | Gap OpenClaims Addresses |
| --- | --- | --- |
| [C2PA](https://spec.c2pa.org/specifications/specifications/2.1/specs/C2PA_Specification.html) | Digital asset provenance, manifests, assertions, and signatures | Asset-centric; does not define claim/evidence/verification lifecycle semantics |
| [W3C PROV](https://www.w3.org/TR/prov-dm/) | General provenance model for entities, activities, and agents | Abstract provenance model; no claim-specific wire format or support vocabulary |
| [OpenLineage](https://openlineage.io/docs/spec/object-model/) | Data pipeline jobs, runs, datasets, and facets | Pipeline lineage; not claim-level evidence or contradiction handling |
| [OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) | Runtime tracing and semantic conventions for GenAI systems | Observability layer; not a claim/evidence graph or verification lifecycle |
| [schema.org Claim](https://schema.org/Claim) / [ClaimReview](https://schema.org/ClaimReview) | Public web markup for claims and fact-check reviews | Publication vocabulary; not an operational event standard |
| [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) | AI risk governance and management guidance | Governance framework; not an implementation schema |

The closest pairing is OpenClaims plus C2PA: OpenClaims can describe the live claim/evidence graph, while C2PA can package exported reports, PDFs, or images with durable asset provenance.

## Recommended Next Milestones

### 1. Conformance Suite

Turn the current fixtures into a clearer TCK-style runner:

- schema validation cases;
- digest canonicalization cases;
- cross-language TypeScript/Python digest parity;
- lifecycle replay cases;
- CloudEvents wrapping cases;
- JSON-LD snapshot cases.

### 2. OpenTelemetry Bridge

Add an adapter that maps OpenTelemetry trace/span IDs and GenAI/MCP span metadata into OpenClaims `ToolRun.trace_ref` and tool metadata.

Keep this adapter informative rather than making OTel a hard dependency of the core schema.

### 3. Sample Integrations

Build examples that prove usability:

- RAG service emitting document-grounded `claim.emitted` events;
- verifier producing `claim.verified` and `claim.disputed`;
- small UI showing claims, selectors, evidence cards, and lifecycle history;
- report exporter producing JSON-LD and later C2PA packaging.

### 4. Signing Profile

Implement DSSE/in-toto mapping after digest behavior is stable:

- define the ClaimLineage statement predicate;
- bind event IDs, event digests, subjects, and claim IDs;
- add CLI `sign` and `verify-signature` commands;
- keep key trust policy outside v0.1 core.

### 5. Standards And Adoption

Prepare a standards-facing package:

- short explainer;
- minimal interoperable examples;
- conformance fixtures;
- comparison with C2PA, PROV, OpenLineage, OTel, and schema.org;
- sample integrations showing implementation cost.

Potential venues to evaluate include W3C community groups, IETF-adjacent provenance/security discussions, Linux Foundation AI & Data, and observability/provenance communities.

## Current Verdict

OpenClaims is credible as an early v0.1 reference implementation. It is ready for early adopters who need claim-level provenance and are comfortable with a young standard.

It is not yet ready for broad standardization until the conformance suite, sample integrations, signing profile, and adoption materials are stronger.
