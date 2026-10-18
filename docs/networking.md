# Ledger networking (C6): serve / sync / spool

`ocl serve` is a stdlib-HTTP ledger API; `OCL_URL` turns any `ocl` client
into a remote writer with offline spool fallback. Design assumption:
many machines (Studio, Mac mini hub) write, one canonical ledger.

## Endpoints

| Method | Path            | Purpose                                  |
|--------|-----------------|------------------------------------------|
| POST   | `/events`       | append event; server re-validates + digests, rejects invalid |
| GET    | `/claims/<ref>` | replay current claim state               |
| GET    | `/chain/verify` | verify digests + hash chain of server store |

Client behavior (`OCL_URL` env):

- emit/verify/dispute/retract POST to `$OCL_URL/events`
- server down / unreachable → event appended to `claims/spool.jsonl`,
  exit stays success with `"stored": "spooled"` + stderr warning
- `ocl sync` replays the spool in order and empties it

## Demo run (2026-09-27, single machine)

Two "writers" through the same endpoint (cross-host split awaits the Mac
mini hub; the protocol is host-agnostic):

```
$ tools/ocl/ocl serve --port 8517 &
$ OCL_URL=http://127.0.0.1:8517 ocl emit --text "SearXNG will run..." --type prediction ...
  A: clm_fcbbb1fa1f9e4b0eb4e4ba12a6
$ OCL_URL=http://127.0.0.1:8517 ocl emit --text "Fleet hub is the Mac mini M4..." ...
  B: clm_d38b39721864451895a7bb6f50
$ curl -s localhost:8517/chain/verify
  {"ok": true, "events": 12}
```

Offline path (server killed):

```
$ OCL_URL=http://127.0.0.1:8517 ocl emit --text "written while down..."
  {"ok": true, ..., "stored": "spooled"}          # warning on stderr
$ wc -l claims/spool.jsonl
  1
# server restarted:
$ ocl sync
  {"ok": true, "flushed": 1, "remaining": 0}
$ ocl chain --verify
  {"ok": true, "events": 13}
```

## Notes

- Server rejects events failing schema or digest checks (`valid: false`);
  client does **not** spool a rejection (it is a bug, not an outage).
- Single-node demo appends to the same physical store the client would use
  as its local fallback; on the real fleet each host keeps its own spool
  only, and the hub owns the canonical file.
- Tailscale fit: bind serve to the tailscale interface, clients use
  `OCL_URL=http://<mini-tailscale-name>:8517` — no port forwarding, no
  public exposure (`tailscale serve` adds HTTPS if ever needed).
