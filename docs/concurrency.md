# Concurrency & crash-consistency boundary (G-G4)

Evidence base: `tools/mem/tests/test_concurrency.py` (10 tests, run in
the standard suite). Read this before wiring a new writer.

## Supported

**One machine, N processes, one mem home.** Writers coordinate through
two mechanisms, both in `mem/store.py`:

1. **Atomic replace for whole-file views.** Every `store.write()`
   (pages, index.yaml, graph.jsonl, audit/eval reports, querysets)
   writes a process-unique tmp file
   (`<path>.<pid>-<thread>-<rand>.tmp`), fsyncs, then
   `os.replace()`s. On the local filesystem rename is atomic: a
   reader sees the old bytes or the new bytes, never a mix. Crash
   hooks `MEM_CRASH_POINT=mid-tmp|pre-rename` + SIGKILL tests prove
   the final file survives intact; the only residue is an orphan
   `.tmp`. Since the F-10 fix those names are process-unique, so no
   later writer reuses them: `Store.write` sweeps stale sibling temps
   for the target file (same-name prefix, `.tmp`, older than
   `STALE_TMP_SECONDS` = 1 h) so crash residue cannot accumulate;
   younger temps may belong to a live writer and are left alone.
2. **flock + O_APPEND for the event log.** Mutations inside
   `with store:` serialize on `flock(.lock)`; `append_event()`
   writes exactly one line per call with fsync. Concurrent appends
   interleave whole lines on local filesystems.

Readers of append-only JSONL use `codec.read_jsonl()`, which RETURNS
torn lines instead of choking on them or silently accepting them:

- `hygiene._events` — torn tail skipped, valid records survive;
- `hygiene.reconcile` — every torn line becomes an audit finding
  (`evidence: torn_line`, counted in `torn_event_lines`, exit 1);
- `graph.load_graph` / `evalkit.load_queryset` — derived views drop
  torn lines and record it (`graph_view_torn_lines` event);
  `mem graph --build` / `mem eval --bootstrap` regenerate losslessly
  from the source files.

**Recovery order after a crash:** the final files are already intact
(atomic replace); if an external actor tore a file anyway (bad sync
tool, hand edit), the pinned `content_hash` in raw frontmatter makes
`evidence`/`reconcile` report it `stale`, and the git backstop
(`mem` commands auto-commit; `git checkout -- <file>`) restores.
Tests: `TestCrashInjection`.

## NOT supported

**Multi-machine writers on a shared filesystem (NFS/SMB/FUSE).**
flock is advisory and unreliable across NFS-family mounts
(concurrent-append interleave atomicity is also not guaranteed), and
`os.replace` atomicity depends on the server's export options. The
hub topology keeps one writer (the mini host) and serves reads over
HTTP (`mem serve`); cross-machine writes go through git, not through
a shared mount.

## Bug found while building this (FAILURES F-10)

Thread-ident-only tmp names collide ACROSS processes (two main threads
share an ident): writer A's `os.replace` deleted writer B's pending
tmp → FileNotFoundError. Fixed with pid+thread+random tmp names; the
parallel-writer test (`4 procs x 3 ingests = 12 claims, 0 torn lines,
zero loss`) now covers it.

## Known open items (ISSUES)

- Multi-machine shared-FS writes (ISSUES-j): unproven on the mini's
  NFS-family exports; forbidden until the 4-proc stress test is rerun
  against a Studio-mounted export.
- Guardrail TTL is an env knob outside the rules layer (ISSUES-k).

- A torn trailing line that happens to end after a complete JSON
  object parses as a complete record — honest boundary (truncation
  of whitespace only), documented in `TestTornAppends`.
- `git_commit` backstop is opportunistic (per-command, best effort);
  no scheduled fsck/reindex cron yet — see `deploy/mini/README.md`.
