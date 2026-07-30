#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
set -a
. "$project_root/.env"
set +a

docker compose --profile tools run --rm migrate alembic current
docker compose --profile tools run --rm migrate python -m rtr_copilot.commands.migration_check

runtime_sql() {
  docker compose exec -T \
    -e PGPASSWORD="$POSTGRES_RUNTIME_PASSWORD" postgres \
    psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_RUNTIME_USER" -d "$POSTGRES_DB" \
    -c "$1" >/dev/null 2>&1
}

for statement in \
  "CREATE TABLE runtime_must_not_create(id integer)" \
  "ALTER TABLE subjects ADD COLUMN runtime_must_not_alter integer" \
  "DROP TABLE subjects" \
  "INSERT INTO audit_events(event_id,actor_kind,action,result,reason_code,request_id,event_hash)
   VALUES(gen_random_uuid(),'service','bypass','success','bypass','bypass',repeat('0',64))" \
  "UPDATE audit_events SET reason_code='tamper'" \
  "DELETE FROM audit_events" \
  "TRUNCATE audit_events"
do
  if runtime_sql "$statement"; then
    echo "LEAST PRIVILEGE FAIL: $statement" >&2
    exit 1
  fi
done

echo "DB VERIFY PASS · revision=head · 7 forbidden runtime operations denied"
