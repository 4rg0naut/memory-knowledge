# mem deploy status (2026-09-29)

## Live

- **Studio (captain)**: `mem serve` LaunchAgent on `127.0.0.1:8520`
  (`deploy/studio/uk.4rg0naut.mem.serve.plist`). Tests:
  `cd tools/mem && ./.venv/bin/python -m unittest discover -s tests` (32 green).
- **mini (oldmini)**: hub. `ollama serve` (Metal M4, localhost-only) +
  `qwen2.5:7b-instruct` pulled; `mem serve` LaunchAgent on
  `127.0.0.1:8520`; repo clone at `~/Memory_Knowledge`, hub remote
  `mini:~/git/Memory_Knowledge.git`.
- **E2E proven**: `POST /scrape https://unreallabs.ai/blog/unreal-agent/`
  on the mini extracted 5 verbatim-quoted claims onto
  `wiki/entities/unreal-agent.md`; the quote gate live-rejected 6
  hallucinated quotes in the first pass.
- **MCP**: 7 tools exposed via `/mcp`, connected from the OpenFox session.

## One-time user actions (blocking HTTPS + enforcement)

1. **Enable Serve on the tailnet** (browser):
   `https://login.tailscale.com/f/serve?node=nu6wn3GXso11CNTRL`
   Then on the mini: `/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg 8520`
   → `https://oldmini.<tailnet>.ts.net/healthz` becomes reachable from Studio;
   point consumers at `MEM_URL=https://oldmini.<tailnet>.ts.net`.
2. **memsvc lock-down** (run in your terminal on the mini, password stays local):
   ```sh
   sudo dscl . -create /Users/memsvc UniqueID 451
   sudo dscl . -create /Users/memsvc Shell /usr/bin/false
   sudo dscl . -create /Users/memsvc HomeDirectory /Users/operator/mem-home
   sudo mkdir -p /Users/operator/mem-home && sudo chown memsvc /Users/operator/mem-home
   cd ~/Memory_Knowledge && git push origin main   # sync before chown
   sudo chown -R memsvc:staff memory
   sudo chmod -R g-w,o-w memory   # operator keeps group READ, no WRITE
   ```
   Re-run agent after chown: `launchctl kickstart -k gui/$(id -u)/uk.4rg0naut.mem.serve`
   (the mem serve agent itself should later move to a memsvc-owned
   LaunchDaemon via `sudo launchctl bootstrap system`).
   Test: `echo x >> memory/index.yaml` → Permission denied = enforced.
3. **ACL (optional hardening)**: tag `oldmini` with `tag:mem-hub`; add ACL rule
   allowing `tag:mem-writer` devices POST paths, everyone tailnet-read.
   Console: Access controls → ACLs.

## Known quirks

- Both machines write claims → git branches diverge; both clones use
  `pull.rebase=false` (merge). A cron'd `git pull --no-edit && git push`
  per machine is the graduation step.
- Ollama 0.34 `/api/chat` streams NDJSON by default — requests must send
  `"stream": false` (pinned in code + test).
- Extraction quality is quote-gate-limited: 7B paraphrases quotes → claims
  get dropped (honest floor). Bigger model later if yield is too low.
- Raw immutability: same-day re-scrape of same URL with `--force`
  overwrites its raw file (name collision); same-hash dedupe is
  content-based and unaffected.
