# OpenClaims Strategy and Roadmap

OpenClaims is not an AI truth engine. It is an open interoperability standard and infrastructure layer for AI claim provenance, evidence lineage, verification state, semantic traceability, auditability, and replayable claim history.

The core operating question is:

> Why did the AI say this, what evidence supported it, and how did that claim change over time?

OpenTelemetry models operational observability. OpenLineage models data lineage. OpenClaims should model semantic claim lineage for AI systems.

## Strategic Position

OpenClaims is most likely to become one of these:

- A useful niche OSS spec if it stays schema-first without a painful workflow.
- A feature absorbed into observability, eval, or agent platforms if the category matters but OpenClaims does not own adoption.
- An important infrastructure layer if it becomes the easiest way to debug, verify, replay, and audit AI-generated claims across tools.
- A meaningful standalone company only if it owns a recurring operational workflow and the hosted infrastructure around it.

The spec itself is not the business. The business is the operational system around the spec.

Strong positioning:

- OpenClaims is semantic observability for AI systems.
- OpenClaims records what an AI claimed, what evidence supported it, and how that claim changed over time.
- OpenTelemetry tells you what happened operationally. OpenClaims tells you what was asserted semantically.
- OpenClaims turns AI answers into replayable claim-evidence histories.
- Not truth scoring. Claim provenance.

Avoid positioning OpenClaims as:

- A truth layer for AI.
- A universal verification engine.
- AI safety theater.
- A consumer trust badge.
- A chain-of-thought exposure mechanism.

## Strongest Wedge

The strongest wedge is RAG and agent provenance debugging.

The initial user problem:

> Show me every material claim in this AI answer, the source chunks used, the retrieval or tool path, the verification status, and whether a later source contradicts it.

This is more practical than starting with journalism, science, or broad AI governance. Those markets care about provenance, but engineers building RAG and agent systems already have the data, the integration surface, and the operational pain.

## First Target Segment

Target AI engineers building enterprise RAG or agent systems.

Specifically:

- Teams building internal copilots.
- Teams building document-grounded assistants.
- Teams in regulated or high-stakes workflows.
- Teams already using LangChain, LlamaIndex, OpenTelemetry, Braintrust, LangSmith, Arize, Weights & Biases, Humanloop, or custom eval stacks.

Why this segment first:

- They directly feel the "why did it say this?" problem.
- They can install SDKs and middleware.
- They understand traces, events, and evals.
- They need debugging before they need governance.
- They create the provenance records that analysts, compliance reviewers, journalists, and scientists can later consume.

## Differentiation

Differentiated:

- Claim-level event model.
- Additive claim lifecycle.
- Separation of claims, evidence, verification, and tools.
- JSON Schema, CloudEvents, and W3C PROV alignment.
- First-class evidence selectors.
- Replayable semantic history.

Inevitable:

- AI outputs will need provenance metadata.
- RAG systems will expose retrieval and source traces.
- Agent platforms will expose tool and evidence paths.
- Compliance teams will ask for audit trails.

Already commoditizing:

- Basic citations.
- Source links.
- Model and tool traces.
- RAG evals.
- Observability dashboards.
- Confidence labels.

Vulnerable to platform absorption:

- Collector.
- Hosted dashboard.
- Basic validation.
- CloudEvents wrappers.
- SDK middleware.
- Claim extraction from model outputs.

The defensible layer is not merely emitting events. It is becoming the interoperable record format and replay layer across AI tools.

## Competitive and Ecosystem Dynamics

If the category becomes important:

- OpenAI may expose richer response provenance, tool traces, citation metadata, and enterprise audit APIs.
- Anthropic may add citation, tool-use, and MCP-adjacent provenance features.
- Microsoft may fold similar capabilities into Purview, Copilot audit, SharePoint provenance, Fabric, and enterprise compliance.
- Datadog and observability vendors may add AI semantic spans and claim/evidence attributes.
- LangChain and LangSmith may add claim-level observability as a product feature.
- Braintrust may add claim provenance to eval datasets, traces, and human-review workflows.

OpenClaims should integrate with these ecosystems early. It should not position itself as a replacement for eval or observability platforms.

## First 12-Month Integration Priorities

Highest priority:

1. LangChain middleware.
2. LlamaIndex middleware.
3. OpenTelemetry span correlation.
4. Braintrust export/import examples.
5. LangSmith export/import examples.
6. OpenAI and Anthropic SDK middleware.
7. Thin vector database examples for Pinecone, Weaviate, Qdrant, and Chroma.
8. Source-system examples for Google Drive, SharePoint, Notion, and Confluence.

Do not prioritize Kafka, a full dashboard UI, C2PA, DSSE, or standards-body work before real workflow adoption.

## OSS to Product Path

### Phase 1: OSS Developer Utility

Deliver:

- SDKs.
- Validator.
- Fixtures.
- RAG and agent middleware.
- Static demo.
- CLI that turns AI outputs and source chunks into OpenClaims events.
- Local viewer for claim histories.

Goal:

> Make developers say, "This would have helped me debug that bad answer."

### Phase 2: Hosted Trace and Event Store

Deliver:

- Hosted collector.
- Claim history.
- Evidence search.
- Digest verification.
- Source version tracking.
- JSON-LD and PROV export.
- Webhooks and API integrations.

Goal:

> Teams stop wanting to run their own collector.

### Phase 3: Enterprise Governance Layer

Deliver:

- Policy controls.
- Retention.
- Access control.
- Review workflows.
- Audit exports.
- Incident timelines.
- Compliance reports.
- SSO and SOC2 readiness.

Goal:

> Sell to regulated enterprises where AI outputs need review and auditability.

Do not jump straight to enterprise governance. Without engineering adoption, it becomes compliance shelfware.

## Recommended Business Model

Best path:

> OSS spec plus open-source SDKs plus open-core or hosted infrastructure.

Keep OSS:

- Spec.
- Schemas.
- SDKs.
- CLI.
- Fixtures.
- Basic collector.
- Local viewer.

Paid product candidates:

- Hosted event store.
- Team dashboards.
- Audit trails.
- Source version monitoring.
- Review workflows.
- Enterprise integrations.
- SSO and RBAC.
- Retention and export.
- Compliance reports.
- Managed conformance.

Do not start as a standards foundation. A foundation makes sense after usage exists.

## What to Cut From v0.1

Defer:

- Full DSSE signing.
- C2PA packaging.
- Standards-body process.
- Full governance dashboard.
- Rich graph query engine.
- Complex confidence scoring.
- Claims ontology beyond minimal relation types.
- Kafka and event-bus infrastructure.
- Multi-tenant SaaS architecture.
- Heavy JSON-LD ambitions beyond export/profile.
- Universal claim extraction promises.

Keep:

- JSON Schemas.
- Valid and invalid fixtures.
- SDK helpers.
- CLI validator.
- Basic collector.
- RAG and agent integration examples.
- Static and local demos.
- Claim lifecycle.
- Digest and canonicalization rules.
- Evidence selectors.

## Implementation Priorities

Highest priorities for proving market pull:

1. Real RAG demo against a PDF or policy corpus.
2. LangChain or LlamaIndex integration.
3. OpenTelemetry bridge.
4. Braintrust and LangSmith example integrations.
5. Claim extraction helper for material claims.
6. Local viewer for OpenClaims event histories.
7. Conformance suite.
8. Redaction and digest-only privacy model.

The weekly operating test:

> Did OpenClaims help someone find, explain, fix, or audit a bad AI answer faster?

## Roadmap

### Next 30 Days

- Polish the static Verified Analysis demo.
- Build a real RAG demo using one PDF corpus.
- Add LangChain or LlamaIndex integration.
- Add a local viewer for OpenClaims event histories.
- Add documentation centered on "Why did the AI say this?"

### Next 90 Days

- Add OpenTelemetry span correlation.
- Add Braintrust and LangSmith example integrations.
- Add a material-claim extraction helper.
- Add redaction and digest privacy guidance.
- Publish conformance fixtures.
- Recruit 3 to 5 design partners.

### Next 6 Months

- Build hosted collector alpha.
- Add evidence and source version tracking.
- Add claim lifecycle dashboard.
- Add audit export.
- Package enterprise self-host option.
- Publish case studies from design partners.

### Next 12 Months

- Launch OpenClaims Cloud beta if hosted pull exists.
- Expand integrations with major RAG and agent stacks.
- Start SOC2 planning if enterprise pull exists.
- Begin standards conversations only after usage exists.

## Adoption Signals

Weak signals:

- GitHub stars.
- Positive comments.
- Generic standards interest.
- People saying the idea should exist.

Real adoption signals:

- External projects emit OpenClaims events.
- AI engineering teams add OpenClaims to RAG pipelines.
- Users open integration issues.
- Vendors ask about compatibility.
- Users contribute fixtures from real workflows.
- Someone builds a viewer, exporter, or integration independently.
- Companies ask about self-hosting, retention, SSO, or audit exports.
- Braintrust, LangSmith, or OpenTelemetry users request OpenClaims support.
- Compliance or security teams ask whether records can be retained as audit evidence.

Category legitimacy signals:

- "Claim provenance" becomes a term vendors use.
- Eval and observability tools add claim-level evidence views.
- OpenClaims is cited in AI engineering or governance discussions.
- Customers ask platforms whether they support OpenClaims export.

## Failure Modes

Highest-probability failure modes:

- The project remains too abstract.
- The spec grows faster than the workflow.
- Developers must manually emit too much metadata.
- Platforms absorb the useful parts before OpenClaims has adoption.
- Verification is misread as truth scoring.
- Analysts and journalists like the idea but do not create enough paid pull.
- Enterprises refuse to send sensitive claim/evidence records to hosted infrastructure.
- Demos look good but do not expose real debugging value.

Mitigations:

- Lead with RAG and agent debugging.
- Make integration trivial.
- Keep sensitive inputs digest-first and redaction-friendly.
- Build executable examples before expanding the spec.
- Integrate with observability and eval systems instead of competing with them.

## Trajectories

### 1 Year

Best case:

- Strong OSS repo.
- Working real RAG demos.
- LangChain and LlamaIndex integrations.
- Early users.
- 3 to 5 design partners.
- Clear hosted product prototype.

Base case:

- Good spec and landing page.
- Some interest.
- Limited production use.
- Wedge still being refined.

Bad case:

- Overbuilt schemas.
- No painful workflow.
- People like the concept but do not integrate it.

### 3 Years

Best case:

- OpenClaims becomes a known event format for AI provenance.
- Hosted product is used by AI engineering and compliance teams.
- Observability and eval vendors support import/export.
- Company has credible revenue from regulated or enterprise AI teams.

Base case:

- Useful OSS library.
- Some integrations.
- Concept absorbed by bigger tools.
- Small support or consulting business possible.

Bad case:

- Platform vendors implement proprietary equivalents.
- OpenClaims remains a clean spec with little adoption.

### 5 Years

Best case:

- OpenClaims is to semantic AI lineage what OpenLineage is to data lineage.
- The company owns hosted governance and audit infrastructure.
- The standard survives because it became operationally useful first.

Base case:

- The ideas survive, but the project does not dominate.
- Parts are folded into OpenTelemetry, LangSmith, Braintrust, or Microsoft ecosystems.

Bad case:

- Claim provenance becomes table stakes inside platforms.
- Standalone infrastructure has no budget owner.

## Founder Operating Principles

The smartest infrastructure path:

1. Pick one painful workflow: debugging bad RAG and agent answers.
2. Build the best demo in that workflow.
3. Make integration trivial.
4. Capture real traces from real systems.
5. Show before/after debugging value.
6. Publish the schema as the portable artifact.
7. Get design partners.
8. Build hosted storage and replay once users generate events.
9. Sell auditability after developers already use it.
10. Keep the standard open enough that vendors can adopt it.

The strategic mandate:

> Own the question: "Why did the AI say this, and what evidence proves where it came from?"
