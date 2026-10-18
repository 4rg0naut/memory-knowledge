# ADR-0003: memsvc service-user isolation for the memory root

- Status: accepted
- Date: 2026-09-29
- Deciders: operator
- Refs: commit 4a1f04f, deploy/mini/uk.4rg0naut.mem.serve.daemon.plist

## Context

`mem serve` initially ran as a user LaunchAgent under `operator`: any process
in that session could write the memory root, and a root-ownership mess
from an early `sudo` scrape broke `git` for the service user
(git refused the repo without `safe.directory`).

## Decision

Run the mini hub service as a dedicated local user `memsvc`
(UniqueID 451, `/usr/bin/false` shell) via a system LaunchDaemon; the
memory root is owned `memsvc:staff` with group read, no group write.
Interactive users get read access to the corpus, writes go through the
service (POST :8521) or deliberate re-ownership.

## Consequences

Writes require the daemon or the mem-writer port — enforced twice (OS
permissions + listener split). Cost: `git push/pull` by memsvc needs the
repo remote readable by that user, and every ad-hoc repair must be
re-expressed as a bootstrap script (T5/ADR-0006 follow-through).
