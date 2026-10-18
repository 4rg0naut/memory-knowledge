# Benchmarks

Measurable claims, published the silicon-ledger way: harness + committed
expected outputs + a one-command verifier, so anyone with a clean clone
can falsify the numbers rather than trust them.

```sh
scripts/verify-bench.sh          # arm 1 everywhere; arm 2 needs macOS + swiftc
```

Exit 0 means every metric reproduced within tolerance; drift is printed
as a diff table. The script stamps the environment (python version,
platform) on every run.

| benchmark | what it measures | where |
|---|---|---|
| mem-eval (demo home) | recall quality of the four read-path modes (baseline / distilled / fused / graph) with tokens-per-query and bootstrap CIs; guardrail adversarial section | `tools/mem/mem/evalkit.py`, fixture `demo/memory/` |
| prune-gate (vision-reference arm) | macOS Vision OCR word-recall vs synthetic ground truth; full A/B arm additionally measures a quadrants-gate that prunes empty crops before OCR | `benchmarks/prune-gate/` |

## Honesty notes

- The demo home is small and saturated (baseline MRR 1.0 on its
  auto-derived queryset). It exists to prove the *pipeline*
  reproducibly end-to-end, not to advertise difficulty. The internal
  corpus (not published, same code) is what drives roadmap decisions.
- `distilled` mode on the demo surfaces the two compound objects
  distilled from the standup transcript; its MRR (~0.08) is honestly
  low against saturated atomic retrieval — that gap is the mode doing
  something different, not being broken.
- The published prune-gate suite is the 3 synthetic images only; the 6
  real screen captures stay private (desktop screenshots, ADR-0013).
  The full A/B arm additionally needs the local `fm` CLI.
- Regenerating the demo fixture:
  `tools/mem/.venv/bin/python scripts/make-demo-home.py`, then refresh
  `expected_results.json` from a passing `verify-bench.sh` run.
