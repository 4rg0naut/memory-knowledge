# FAILURES — do not repeat these

Every failure, wrong assumption and dead end encountered while building
the mem kernel, recorded so it is not rediscovered later. **Read this
before debugging anything in `tools/mem/`.** Ported habit from
silicon-ledger/FAILURES.md: a bug is not fixed until it becomes a rule
plus a test.

Format: **symptom → what was wrongly assumed → actual cause → fix → rule.**

---

## A. Bytes and formats

### F-01 · Fresh raw reports `evidence: stale` immediately after capture
- **Symptom:** `mem evidence` flags a claim's source stale seconds
  after `mem ingest`, with content_hash mismatch, on a byte-identical file.
- **Wrongly assumed:** that the pinned hash and the re-hash input were
  the same bytes.
- **Actual cause:** `write_raw` appends exactly one `\n` after the
  payload; `evidence_status` re-hashed `body.rstrip("\n")` — stripping
  newlines that belonged to the payload itself when the source text
  ended with one. Hash input ≠ captured bytes, so re-hash ≠ pin.
- **Fix:** strip the single delimiter newline only
  (`body[:-1] if body.endswith("\n")`), hygiene.py.
- **Rule:** a digest pin is re-verified against the **exact bytes**
  stored; normalization at check time must be the exact inverse of the
  write path. Test: `tests/test_s5_hygiene.py`
  `TestEvidenceStatus.test_ok` / `test_stale_on_content_drift`.

### F-02 · `mem migrate` leaves pre-v2 files on their old stamp
- **Symptom:** after migration the page header still reads
  `format: mem-wiki@1` (test asserted the new stamp and failed).
- **Wrongly assumed:** that `stamp_insert` overwrote an existing
  `format:` key.
- **Actual cause:** the rebuild loop copied every existing key and set
  `format` once from the first key encountered — an existing `format`
  key then re-copied the OLD value over the new one.
- **Fix:** replace in place when the key exists
  (`codec.stamp_insert`), keeping key position.
- **Rule:** stamp up/down migrations must be tested **from the previous
  stamp**, not only from unstamped input. Test:
  `tests/test_temporal.py::TestCodecV2::test_stamp_insert_v1_to_v2`.

## B. Time and language

### F-03 · "3 days ago" resolves to three months ago
- **Symptom:** `resolve_relative("deployed 3 days ago", "2026-10-18")`
  returns 2026-07-18.
- **Wrongly assumed:** the unit word is the last token of the match.
- **Actual cause:** `m.group(0).split()[-1]` is `"ago"` — the month
  fallback branch swallowed every days/weeks match.
- **Fix:** unit token is index 1, not -1 (temporal.py).
- **Rule:** when parsing an N-unit-ago phrase, pin every unit in the
  table with its own expected date; the fallback branch must be
  unreachable by table order. Test:
  `tests/test_temporal.py::TestResolve::test_phrases`.

### F-04 · A transcript paragraph splits in the middle of itself
- **Symptom:** one `turn 14` paragraph became two "exchanges" in
  distill output.
- **Wrongly assumed:** a segmentation bug.
- **Actual cause:** the fixture line "Agent note: …" starts with a
  speaker word — `segment_exchanges` legitimately breaks on speaker
  prefixes at line start.
- **Fix:** fixture wording, not product.
- **Rule:** fixtures must not accidentally exercise boundary regexes
  (turn markers, speaker prefixes) inside a paragraph; if they do,
  assert the split, don't "fix" it silently. Test:
  `tests/test_distill.py::TestSegment`.

## C. Mini-YAML and derived views

### F-05 · Daily card idempotency silently broken
- **Symptom:** a second `mem daily` recreates cards for raws that
  already have them.
- **Wrongly assumed:** that `_covered_raws` coerces the parsed
  `[[raw/x.md]]` source back to a string correctly.
- **Actual cause:** mini-YAML parses `[[x]]` as a **nested list**
  (`[['x']]`); `str()` of the inner list injected `['…']` quoting into
  the recovered path, so nothing matched.
- **Fix:** flatten nested lists to the first scalar, then regex the
  `.md` path out of whatever remains (daily.py).
- **Rule:** anything re-reading mini-YAML values must assume the
  parser's shape, not the writer's intent. Test:
  `tests/test_daily_graph.py::TestDaily::test_idempotent`.

## D. Metrics honesty

### F-06 · A recall score with no token count is not a result
- **Symptom:** early harness draft printed MRR only; baseline looked
  perfect (mrr 1.0) until tokens appeared next to it.
- **Wrongly assumed:** ranking quality can be judged ranking-only.
- **Actual cause:** context cost per query is the budget a small model
  actually pays; two modes with equal MRR differ up to 28% in tok/q.
- **Fix:** `evalkit.run` reports `tokens_per_query` in every per-type
  and headline row, and `eval --emit` sends both to the ledger.
- **Rule:** never accept or ship a harness row without
  quality + tokens + `eval_stamp.json` match (env comparable). Test:
  `tests/test_evalkit.py::TestRun::test_metrics_and_report`.

### F-10 · Atomic-rename tmp names collided across processes
- **Symptom:** the 4-process concurrent-writer stress test failed with
  `FileNotFoundError: .../acme.md.<id>.tmp -> .../acme.md` inside
  `store.write` → `os.replace`; single-process runs never reproduced.
- **Wrongly assumed:** a tmp file name unique across *threads* is
  unique across *processes*.
- **Actual cause:** tmp names used `threading.get_ident()` only, and
  the main threads of different processes share the same ident. Two
  writers to the same page both built `<page>.<same-id>.tmp`; the
  first rename deleted the second one's pending tmp.
- **Fix:** tmp names embed pid + thread ident + random suffix
  (`store.write`); crash-hook tests prove the final file survives
  `SIGKILL` mid-tmp and pre-rename with old bytes intact.
- **Rule:** anything used as a scratch path in a multi-writer design
  must embed the process id, not just the thread id. Tests:
  `tests/test_concurrency.py::TestConcurrentWriters` and
  `TestCrashInjection`.

### F-11 · A crash-torn JSONL line killed every downstream reader
- **Symptom:** truncating one byte off `events.jsonl` made
  `hygiene._events`, `lint`, `audit`, and `graph.load_graph` raise
  `json.decoder.JSONDecodeError` — the audit tool could not run on
  exactly the file it audits.
- **Wrongly assumed:** appends are atomic everywhere, so logs are
  always parseable.
- **Actual cause:** O_APPEND + buffered writes can tear the trailing
  line under SIGKILL, and every reader used strict `json.loads` per
  line; the one honest signal (a torn tail) surfaced as a crash in an
  unrelated feature.
- **Fix:** `codec.read_jsonl` returns `(records, torn)`; events
  readers tolerate and report, derived views (graph/queryset) drop
  torn lines and record it, and `mem reconcile` fails with
  `torn_event_lines` counts — corruption is declared, never asserted
  away or fatal.
- **Rule:** readers of append-only logs must separate "torn tail"
  (report, keep the valid prefix) from "corrupt middle" (same, but
  flag loudly); a tool that audits a log must survive that log.
  Tests: `tests/test_concurrency.py::TestTornAppends`.

### F-12 · An exit condition built from counters drifts from the problems list
- **Symptom:** review round 2 found `mem reconcile` exits 0 for a
  self-stamped `verified` claim with intact evidence — the exact
  machine-verified integrity violation S5 exists to catch.
- **Wrongly assumed:** extending exit logic = extending the counter
  list; a row that gets a `note` is "already handled" because it is
  counted in `counts["self_verified"]`.
- **Actual cause:** the row was only appended to `problems` when
  `status != "ok"`, and the CLI keys on `problems`; counters and
  problem rows silently diverged — the earlier exit-code fix (review
  r1 #1) kept counting but stopped surfacing.
- **Fix:** the exit signal is the problems list; any row annotated
  (`note`, era flag, torn line) gets appended:
  `if status != "ok" or "note" in row`.
- **Rule:** audit exit codes must key on ONE derived list, and every
  counter needs a matching row-append path — counters summarize, they
  never gate. Test:
  `tests/test_s5_hygiene.py::TestRoundTwoGates::
  test_self_verified_ok_evidence_fails_exit`.

### F-09 · An evidence heuristic can be stricter than the corpus's history
- **Symptom:** live `mem reconcile` flagged 34/62 (55%) of existing
  claims `unlocatable`; `mem modelcheck` became near-unusable on
  real data, and reconcile's real signals (stale, duplicate_id,
  verified-without-event) drowned in one heuristic's noise.
- **Wrongly assumed:** every claim's passage should appear verbatim
  in its source — the quote gate's rule applied retroactively.
- **Actual cause:** most legacy claims were captured before the
  quote gate existed; they are honest paraphrases of their source.
  A verbatim-only check grades history by today's discipline and
  reports a data-quality disaster that never happened.
- **Fix:** two-tier passage check — literal appearance first, then a
  deterministic token-coverage fallback (>=0.6 of the passage's
  long tokens present in the source), with the measured coverage in
  the audit detail so the leniency is visible, not hidden.
- **Rule:** verification gates must match the discipline *of the era
  the data was captured in*; when loosening, expose the measured
  slack in the output, and keep invented content failing. Test:
  `tests/test_s5_hygiene.py::TestEvidenceStatus::
  test_legacy_paraphrase_survives_coverage` (and the invented-token
  counterpart).

### F-07 · A duplicate claim id crashes every derived index
- **Symptom:** `mem recall` and `mem eval` die with
  `sqlite3.IntegrityError: UNIQUE constraint failed: docs.id` on the
  checked-in memory home; a fresh sandbox worked.
- **Wrongly assumed:** a crash in derived layers means the code is
  broken for the general case.
- **Actual cause:** `wiki/entities/unreal-agent.md` carries the same
  claim id twice (pre-lint double capture, commit 7420812). Append-only
  history allows the mess; `readpath.corpus()` fed both copies into a
  UNIQUE-keyed FTS table.
- **Fix:** `corpus()` dedups claim ids (first occurrence wins);
  `hygiene.reconcile()` now flags `duplicate_id` rows so the standing
  audit surfaces the source instead of the crash recurring elsewhere.
- **Rule:** derived views must absorb history mess, never crash on it;
  the audit is where data debt gets reported. Tests:
  `tests/test_readpath.py::TestCorpus` (dedup) and
  `tests/test_s5_hygiene.py::TestReconcile::test_duplicate_claim_id_flagged`.

### F-08 · Fused recall scored *worse* than baseline (mrr 0.587 < 1.0)
- **Symptom:** after adding vector recall + rank fusion, every
  metric-based acceptance test regressed below the BM25 baseline.
- **Wrongly assumed:** RRF fusion is score-monotone enough to protect
  a perfect lexical hit.
- **Actual cause:** two stacking errors. (1) RRF with k=60 flattens
  rank gaps to ~0.0005, so the additive `recency + importance` terms
  (range ~0.35) silently dominated ordering — fusion became a date
  sort. (2) The partial-match vector list inserted dense docs above
  the gold verbatim chunk, pushing MRR down despite perfect lexical
  evidence.
- **Fix:** CombMNZ consensus (sharper rank decay × consensus count)
  plus a tiered backbone: a doc containing **every** query token gets
  `STRONG_MATCH_BONUS=10.0`, above the 3-list combmnz ceiling (9.0) —
  the hierarchy is arithmetic, not vibes. Measured: fused now
  0.807 ≥ baseline 0.733 on the own corpus, single-hop types 1.0.
- **Rule:** any additive score term must be bounded *below* the
  minimum gap it is allowed to reorder; state the ceiling arithmetic
  in the constant's comment. Tests:
  `tests/test_evalkit.py::TestMultihopAndDecision::test_fused_not_below_baseline`,
  `tests/test_readpath.py::TestRanking::test_combmnz_prefers_consensus`.
