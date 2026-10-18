# ADR-0006: Tailnet writes gated by ACL attribute + tag, not OAuth grants

- Status: accepted
- Date: 2026-09-29
- Deciders: operator
- Refs: deploy/mini/uk.4rg0naut.mem.serve.daemon.plist, infra/tailscale-policy.json (T5)

## Context

Two mechanisms could express "who may write to the hub": Tailscale
Access grants (identity-based, client-side checks) and ACL rules with
attributes/tags (network-layer). The vim-merge trap and an ACL outage
caused by a bad console paste both showed ad-hoc console edits are
fragile.

## Decision

Write access = ACL rule: `autogroup:member` + attribute `tag:mem-writer`
may reach `tag:mem-hub:8521`; everyone on the tailnet may GET `:8520`.
The whole policy lives in `infra/tailscale-policy.json` and is applied
via the API (`PUT /acl`), never by console clicking (policy-as-code, T5).
Grants stay reserved for admin/role tooling, not data-path auth.

## Consequences

Writes are enforced at the network edge plus OS layer (ADR-0003). The
policy file becomes the single reviewable artifact; drift requires an
API read-back (`tests[]`). Open: where the API key and auth keys live
(ISSUES-b).
