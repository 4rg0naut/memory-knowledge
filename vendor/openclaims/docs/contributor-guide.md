# OpenClaims Contributor Guide

This guide is for people changing code, schemas, fixtures, or documentation.

## Repository Layout

- `schemas/openclaims/0.1`: normative JSON Schemas and JSON-LD context.
- `spec`: human-readable specification docs.
- `fixtures`: valid, invalid, CloudEvents, JSON-LD, and signed fixture areas.
- `conformance`: replay and compatibility expectations.
- `packages/typescript-sdk`: builders, validation, canonicalization, IDs, and TypeScript types.
- `packages/validator-cli`: CLI commands.
- `packages/jsonld-exporter`: JSON-LD graph projection.
- `packages/collector`: Fastify collector and SQLite/reference stores.
- `python`: Python SDK and tests.
- `scripts`: repo-level checks and fixture generation.

## Setup

```sh
pnpm install
```

For Python work:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install './python[test]'
```

## Required Checks

Run these before submitting changes:

```sh
pnpm build
pnpm test
node packages/validator-cli/src/index.js fixtures
node scripts/verify-collector.mjs
```

For Python changes:

```sh
.venv/bin/python -m pytest python/tests
```

## Schema Changes

Schema changes must be reflected in:

- `schemas/openclaims/0.1/*.schema.json`
- `packages/typescript-sdk/src/index.d.ts`
- `packages/typescript-sdk/src/validate.js` if semantic validation changes
- `python/openclaims/models.py`
- valid and invalid fixtures
- spec docs when behavior changes

Do not change existing v0.1 field meaning casually. If a field must change, document the compatibility impact in the maintainer guide or release notes.

## Fixture Changes

Fixtures are normative examples. When changing builders or canonicalization:

```sh
node scripts/generate-fixtures.mjs
node packages/validator-cli/src/index.js fixtures
node scripts/verify-collector.mjs
```

Valid fixtures must pass schema validation and digest verification. Invalid fixtures should each fail for a clear reason.

## Coding Conventions

- Keep generated/cache files out of the repo.
- Keep public event fields snake_case.
- Keep event history additive; do not introduce overwrite semantics.
- Store sensitive inputs by digest or redacted summary by default.
- Prefer schema-backed validation plus small semantic checks over ad hoc validation alone.

## Adding A New Event Field

1. Add the field to the relevant schema.
2. Add TypeScript declarations.
3. Add Python model support.
4. Add at least one valid fixture.
5. Add one invalid fixture if the field has validation rules.
6. Update docs if users or implementers need to understand it.

## Adding A New Event Type

New event types require a specialized schema and an update to the `ClaimEvent` union. They also require SDK builder support, CLI validation coverage, Python model support, collector replay semantics, and conformance fixtures.
