# Open issues & unknowns

Register of open questions the board references by id (ISSUES-a etc.).
Resolve by appending the answer + closing note; never delete lines.

## ISSUES-a — tailscaled userspace inbound on apple/container (unproven)

Does inbound from a tailnet peer actually reach a `tailscaled` running
inside an apple/container VM with `--tun=userspace-networking` and
`tailscale serve`? Nothing in the fleet has tested this. Blocks T6
Phase B; host-side serve stays as fallback until proven. Planned test:
Phase-B container on mini, `tailscale ping` + HTTPS GET from Studio.
Owner: T6. Context: ADR-0007, docs/container-policy.md.

## ISSUES-b — auth-key / API-key storage location

Where do long-lived secrets live: Tailscale API key for ACL
policy-as-code (T5) and TS_AUTHKEY for in-container tailscaled (T6)?
Candidates: env of a root-owned launchd plist (current stopgap: keys
occasionally land in shell history), macOS Keychain via
`/usr/bin/security`, or a 0600 file outside the repo. Decision owed
before T5 ships `apply-policy` for real; until then keys must never be
committed. Owner: T5.

## ISSUES-c — mini grant policy vs supersedes-to-container path

The mini currently relies on host-side tailscale serve + the ACL
`tag:mem-writer` :8521 split. Two futures compete (ADR-0005 vs
ADR-0007): keep hardening the grant/ACL as policy-as-code (T5), or
supersede the split entirely by moving the hub into a container that
owns its own tailnet identity (T6 Phase B). Decide once ISSUES-a has an
answer; until then do both halves that are not in conflict (T5 scripts,
T6 Phase A). Owner: T5+T6.

## ISSUES-d — OpenFox SEARXNG_URL wire-up

SearXNG answers JSON on the LAN today; the tailnet HTTPS path
(:8443 + `tcp:8443` ACL attr) and flipping the one app-env string are
open. Owner: T5 acceptance.

## ISSUES-e — upstream license silence (openclaims#1)

openclaims-ai/openclaims still has no LICENSE file (issue opened
2026-09-27, no response). Our README states the situation; revisit
before publishing to PyPI. Owner: ADR-0001.

## ISSUES-f — fleet git sync vs memsvc isolation (found T5, 2026-10-04)

`git pull` in operator's mini clone fails on `memory/` (`Permission denied`)
because the root is memsvc-owned group-read-only (ADR-0003). Mitigation
shipped: group write for staff (bootstrap-mini.sh step 4) — isolation
kept against non-staff and the network. Proper fix still owed: split
service clone (memsvc) vs code clone (operator), likely folded into T6
container mount design. Also: sudo over ssh on mini requires a password
(no NOPASSWD); one-time user action to run chmod or add a
`Defaults!... NOPASSWD` line. Owner: T6.

## ISSUES-g — tailnet ACL surface for direct ports (found T5, refined)

The tailnet ACL (as of 2026-10-04) admits tcp:22 and tcp:443 only.
Workaround shipped: mem + SearXNG ride `:443` via `tailscale serve
--set-path=/mem` / `--set-path=/searx` on the valid cert name
`mini.net01.ts.net` — verified from Studio. Still owed when an
API key exists (ISSUES-b): apply `infra/tailscale-policy.json` to open
`tcp:8520` (plain hub), `tcp:8521` (tagged writes — currently blocked,
machine-to-machine writes ride git sync), and `tcp:8443`. DNS itself
works via the system resolver; old probe failures used the wrong
resolver address. Owner: T5 residual.

## ISSUES-h — inbound tailnet TCP beyond 22/443 blocked at ACL, not pf (confirmed 2026-10-18)

Confirmed root cause for oMLX mini direct-port unreachability: tailnet ACL
admits tcp:22 and tcp:443 only (see ISSUES-g). Evidence: mini oMLX bound
*:8100 (lsof), macOS firewall disabled, ICMP ping from Studio OK, TCP 8100
from Studio timeout, while `tailscale serve --https=443 --set-path=/omlx
http://localhost:8100` answers 401/200 from Studio instantly
(https://mini.net01.ts.net/omlx/v1/models). Residual: apply
infra/tailscale-policy.json (ISSUES-b key pending) to open tcp:8100/8520/
8521/8443 directly, or standardize /omlx serve-path as the fleet pattern.
Until then treat :443 serve paths as the only tailnet-ingress for mini.
Owner: T5 residual.

## ISSUES-i — hub numeric-conflict detector collapses unknown predicates (found 2026-10-18)

mem hub contradiction detection flags every same-page pair of numeric claims
as contradictory when their predicate is not in the known set: all campaign
claims landed as `other:` and produced 6 false-positive contradiction pairs
(8 pairs total vs baseline 2) plus stale flags on 6 fresh claims
(effective 0.06). Different metrics (embed p50 vs decisions p50) are not
conflict candidates. Fix direction: only compare conflicts for identical
predicate+subject triples, or register latency/economics predicates.
Owner: mem-hub. Context: /Volumes/work/OpenFox/oMLX/CAMPAIGN.md
verification-queue section.
UPDATE 03:29 (same day): after the addendum claim batch the live numbers are
13 contradiction pairs (11 false-positive + 2 baseline) and 11 stale-flagged
campaign claims; counts are perishable — recount after any claim post.
Boundary snapshots: /Volumes/work/OpenFox/oMLX/p0/hygiene/*_boundary3.*

UPDATE (campaign-2, 16:10 same day): the same detector failure mode fired
again on fresh pages — 17 manual-provider claims posted to
wiki/entities/omlx-campaign2-20261018.md (predicate other/gotcha) produced a
cascading contradicted chain (each new claim flagged against every earlier
same-page numeric claim). Distinct metrics are not conflict candidates; the
fix direction above stands. Hygiene snapshots now at
/Volumes/work/OpenFox/oMLX/p2/hygiene/boundary_final_studio.*.
Owner: mem-hub. Context: /Volumes/work/OpenFox/oMLX/CAMPAIGN-2.md

## ISSUES-j — multi-machine shared-FS writers remain unproven, thus forbidden (2026-10-18, G-G4)

`docs/concurrency.md` states the supported boundary (one machine, flock +
atomic rename, proven by `tests/test_concurrency.py`). Nobody has measured
what flock + O_APPEND + os.replace actually do on the mini's NFS-family
exports under two hub writers: lock loss, rename atomicity, and append
interleave are all mount-option dependent. Until measured, cross-machine
writes go through git or the hub HTTP write port, never a shared mount.
Candidate experiment: mount the mini export read-write on Studio, run the
4-proc stress against it, compare torn-line counts. Owner: mem-hub.

## ISSUES-k — guardrail TTL is an env knob, not a rules-layer policy (2026-10-18, G-G1)

`MEM_GUARDRAIL_TTL_DAYS` (default 90) decides how long a prohibition may
outrank retrieval before mandatory re-validation, but ADR-0008 made every
other hygiene knob declarative (`rules/base.yaml` + host/patch layers).
One policy knob living outside the rules engine means per-host or
per-source TTLs need a code change. Move `guardrail_ttl` into the rules
set (with a `mem rules list` visible provenance) at next rules touch.
Owner: mem-hub.

## ISSUES-l — unreproduced cold-start failure in full-suite first run on a fresh clone (2026-10-18, P4 proof)

The first `python3 -m unittest discover -s tests` run in a just-cloned
tree (right after venv+pip, under residual clone I/O load) reported
`FAILED (failures=1)`; the failing test name was not captured, and six
subsequent full runs plus targeted `test_concurrency` /
`test_temporal` / `test_eval_ci` re-runs on the same clone were all OK,
as was CI (macos-14, python 3.12). Prime suspect: a timing-sensitive
subprocess-kill assertion in the concurrency suite under cold-start
load. Next occurrence must capture the test name and wall time; if it
names a concurrency test, tighten its wait bounds and attach a FAILURES
rule. Not papered over: publish proceeded because CI + repeat local runs
are green and the gate is deterministic (`verify-bench.sh`). Owner:
mem-hub.
