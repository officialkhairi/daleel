#!/usr/bin/env bash
# Logs in as each seeded user (password grant on the dev-only smoke client) and checks
# /api/me roles and /api/admin/ping RBAC against the running stack.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

API=${API_URL:-http://localhost:5173}
TOKEN_URL="$OIDC_ISSUER/protocol/openid-connect/token"
fail=0

check() { # user expected_roles expected_admin_status
  local user=$1 want_roles=$2 want_admin=$3 token roles admin
  token=$(curl -fsS -d grant_type=password -d "client_id=$SMOKE_CLIENT_ID" \
    -d "client_secret=$SMOKE_CLIENT_SECRET" -d "username=$user" -d password=demo \
    "$TOKEN_URL" | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
  roles=$(curl -fsS -H "Authorization: Bearer $token" "$API/api/me" \
    | python3 -c 'import sys,json; print(",".join(json.load(sys.stdin)["roles"]))')
  admin=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $token" "$API/api/admin/ping")
  if [[ $roles == "$want_roles" && $admin == "$want_admin" ]]; then
    echo "ok   $user  roles=$roles  admin/ping=$admin"
  else
    echo "FAIL $user  roles=$roles (want $want_roles)  admin/ping=$admin (want $want_admin)"
    fail=1
  fi
}

check officer approver,editor 403
check viewer viewer 403
check admin admin 200

anon=$(curl -s -o /dev/null -w '%{http_code}' "$API/api/me")
[[ $anon == 401 ]] && echo "ok   anonymous  /api/me=401" || { echo "FAIL anonymous /api/me=$anon"; fail=1; }
exit $fail
