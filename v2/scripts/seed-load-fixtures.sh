#!/usr/bin/env bash
# TIP-012 Task 5 (Builder 5) — idempotent fixtures the k6 load suite needs on the
# hardened stack, so the run is reproducible for the Contractor:
#   1) a staff-owned `source` upload target (the seeded reference stack ships no
#      upload folder), written to /tmp/upload_target_rid.txt for run-load.sh;
#   2) raised provider cost budgets so a grounded ask burst does not exhaust the
#      per-subject daily cap across repeated same-day runs (append-only version,
#      exactly as governance set_setting does).
# Fake provider only; no external spend. Requires the hardened stack up + the
# ingress reachable at https://$INGRESS_HOST (127.0.0.1).
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
INGRESS_HOST="${INGRESS_HOST:-rtr.local}"
PSQL=(docker compose exec -T postgres psql -At -U rtr_owner -d rtr_copilot -c)

# Resolve the dev-OIDC staff subject through the ingress (creates it if absent).
jar="$(mktemp)"
curl -fsSk --noproxy '*' -c "$jar" -b "$jar" -L -o /dev/null "https://$INGRESS_HOST/api/auth/login"
staff="$(curl -fsSk --noproxy '*' -b "$jar" "https://$INGRESS_HOST/api/auth/me" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["user_id"])')"
rm -f "$jar"
[[ -n "$staff" ]] || { echo "could not resolve staff user_id" >&2; exit 1; }
echo "staff user_id=$staff"

# 1) Upload target (idempotent: reuse an existing Builder5 source if present).
rid="$("${PSQL[@]}" "SELECT s.source_id FROM sources s JOIN resources r ON r.resource_id=s.source_id
       WHERE s.name='Builder5 Load Target' AND r.owner_subject_id='$staff' AND r.lifecycle_state='active'
       LIMIT 1;")"
if [[ -z "$rid" ]]; then
  rid="$("${PSQL[@]}" "WITH ins AS (
      INSERT INTO resources(resource_id,resource_type,owner_subject_id,classification,source_zone,lifecycle_state,legal_hold)
      VALUES (gen_random_uuid(),'source','$staff','internal','private_context','active',false)
      RETURNING resource_id) SELECT resource_id FROM ins;")"
  "${PSQL[@]}" "INSERT INTO sources(source_id,kind,name,metadata) VALUES ('$rid','internal','Builder5 Load Target','{}');" >/dev/null
  echo "seeded upload target $rid"
else
  echo "reusing upload target $rid"
fi
echo "$rid" > /tmp/upload_target_rid.txt

# 2) Budget headroom (append a new version only if the current value is low).
seed_budget() {
  local key="$1" want="$2"
  local cur
  cur="$("${PSQL[@]}" "SELECT value::text FROM governance_settings WHERE setting_key='$key' ORDER BY version DESC LIMIT 1;")"
  if [[ -z "$cur" || "$cur" -lt "$want" ]]; then
    "${PSQL[@]}" "INSERT INTO governance_settings(setting_id,setting_key,version,value_type,value,updated_by,reason)
      VALUES (gen_random_uuid(),'$key',
        (SELECT COALESCE(MAX(version),0)+1 FROM governance_settings WHERE setting_key='$key'),
        'integer','$want'::jsonb,'$staff','tip-012 builder5 load-run budget headroom');" >/dev/null
    echo "raised $key -> $want"
  else
    echo "$key already $cur (>= $want)"
  fi
}
seed_budget limits.budget.subject_daily_units 90000000
seed_budget limits.budget.global_daily_units 900000000
echo "load fixtures ready (upload target in /tmp/upload_target_rid.txt)"
