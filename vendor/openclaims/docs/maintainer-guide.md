# OpenClaims Maintainer Guide

This guide is for people responsible for releases, compatibility, and project health.

## Maintainer Responsibilities

Maintainers are responsible for:

- keeping schemas, SDKs, fixtures, and docs aligned;
- preserving v0.1 compatibility unless a breaking release is intentional;
- reviewing changes to canonicalization, digest generation, and event semantics carefully;
- keeping conformance fixtures representative and executable;
- ensuring the project remains a provenance standard, not a truth adjudication system.

## Compatibility Policy

For the `0.1.x` line:

- Do not remove required fields.
- Do not change digest canonicalization.
- Do not change existing enum meanings.
- Additive optional fields are acceptable when schemas, SDKs, fixtures, and docs are updated together.
- New verification or support semantics should be added through facets first unless they are clearly core.

Breaking schema changes should move to a new versioned path, for example `schemas/openclaims/0.2`.

## Release Checklist

Before tagging a release:

```sh
pnpm install
pnpm build
pnpm test
node packages/validator-cli/src/index.js fixtures
node scripts/verify-collector.mjs
python3 -m venv .venv
.venv/bin/python -m pip install './python[test]'
.venv/bin/python -m pytest python/tests
```

Also verify:

- `pnpm-lock.yaml` is current.
- No cache directories or virtualenvs are included.
- Fixtures were regenerated after builder or digest changes.
- Docs mention any public behavior changes.
- The top-level README still points users to the right entry points.

## Canonicalization And Digests

Event digests are computed over canonical JSON with the `digest` field removed. The reference implementation uses SHA-256 encoded as base64url.

Treat any change here as high risk because it can invalidate existing fixtures and break cross-language compatibility.

## Schema Governance

Schemas are the normative contract. The recommended review order for schema changes is:

1. Core schema change.
2. Specialized event schema change.
3. TypeScript SDK type and builder alignment.
4. Python model alignment.
5. Fixture regeneration.
6. Conformance update.
7. Spec/user docs update.

## Collector Policy

The collector is a reference ingestion gateway. It must not become the authoritative platform model for the standard.

Maintain these constraints:

- Validate schema and digest before storage.
- Preserve additive history.
- Reject duplicate event IDs.
- Require prior `claim.emitted` before verification, dispute, or retraction.
- Treat `claim.retracted` as terminal in the reference collector.

## Security And Privacy Defaults

OpenClaims should default to privacy minimization:

- prefer digests over raw sensitive inputs;
- allow redacted parameter summaries;
- avoid storing raw prompts or retrieved content unless explicitly supplied by the producer;
- keep provenance and verification separate from truth claims.

## Dependency Notes

The Node collector uses Fastify and Node's `node:sqlite`. Current Node versions may print an experimental warning for `node:sqlite`; that is expected for this v0.1 reference implementation.

Python models use Pydantic when installed. The package declares Pydantic as a dependency, and tests should run with the package installed from `python[test]`.
