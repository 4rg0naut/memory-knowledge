#!/bin/bash
# apply-policy.sh — push infra/tailscale-policy.json to the tailnet ACL
# and validate with tests[] (T5, ADR-0006). No console clicking: the
# 2026-09-29 ACL outage came from a bad console paste; this script PUTs
# the whole reviewed file and refuses to finish if the API tests fail.
# Requires: TS_API_KEY (admin API key; storage location = ISSUES-b),
#           TS_TAILNET (e.g. yourtailnet@...).
set -euo pipefail
POLICY="$(cd "$(dirname "$0")/.." && pwd)/infra/tailscale-policy.json"
API="https://api.tailscale.com/api/v2/tailnet"
: "${TS_API_KEY:?set TS_API_KEY (admin key; see ISSUES-b for storage)}"
: "${TS_TAILNET:?set TS_TAILNET (tailnet login name)}"
TNET=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$TS_TAILNET")

python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$POLICY"
echo "[apply-policy] json ok"

if [ "${1:-}" = "--validate-only" ]; then
  RESP=$(curl -sf -X POST "$API/$TNET/acls/validate" \
    -H "Content-Type: application/json" \
    -u "$TS_API_KEY:" --data @"$POLICY")
  echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); ok=d.get('ok',True); print('validate ok' if ok else 'validate FAILED: %s' % d); sys.exit(0 if ok else 1)"
  exit $?
fi

ETAG=$(curl -sf -D - -o /dev/null "$API/$TNET/acl" -u "$TS_API_KEY:" \
  | tr -d '\r' | awk -F': ' '/^etag/{print $2}' || true)
echo "[apply-policy] current acl etag: ${ETAG:-none}"

curl -sf -X PUT "$API/$TNET/acl" -H "Content-Type: application/json" \
  -u "$TS_API_KEY:" --data @"$POLICY" >/dev/null
echo "[apply-policy] PUT ok — verifying with tests[]..."

RESP=$(curl -sf -X POST "$API/$TNET/acls/validate" \
  -H "Content-Type: application/json" \
  -u "$TS_API_KEY:" --data @"$POLICY")
echo "$RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); ok=d.get('ok',True); print('tests[] pass' if ok else 'tests[] FAILED: %s' % d); sys.exit(0 if ok else 1)"
