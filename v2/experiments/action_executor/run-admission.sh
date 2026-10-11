#!/usr/bin/env bash
# Exact serving-pin DBOS proof. Retain owned fixtures until Contractor verifies.
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
v2_root=$(cd "$experiment_dir/../.." && pwd)
run_id=${TIP054_ADMISSION_RUN_ID:-tip054-4b-admission-20261006-r1}
[[ "$run_id" =~ ^tip054-4b-[a-z0-9-]{1,40}$ ]] || exit 2
runner="$run_id-runner"
database="$run_id-postgres"
network="$run_id-offline"
evidence="$experiment_dir/raw/$run_id"
mkdir -p "$evidence"
[[ ! -f "$evidence/fixture-started.json" ]] || { echo 'Choose fresh run id'; exit 2; }
for target in "$runner" "$database"; do
  if docker inspect "$target" >/dev/null 2>&1; then echo "Refusing occupied target $target"; exit 2; fi
done
docker image inspect --format '{{json .Id}} {{json .Architecture}} {{json .RepoDigests}}' rtr-tip054-local-qa:20261006 postgres:18-alpine > "$evidence/images.txt"
docker network create --internal --label "tip054.admission=$run_id" "$network" > "$evidence/network-id.txt"
docker run --pull=never -d --name "$database" --label "tip054.admission=$run_id" --network "$network" --network-alias tip054-pg \
  --tmpfs /var/lib/postgresql:rw,size=768m --tmpfs /tmp:rw,size=64m --memory=1g --cpus=2 --pids-limit=256 \
  -e POSTGRES_USER=admission -e POSTGRES_PASSWORD=synthetic-only -e POSTGRES_DB=admission \
  postgres:18-alpine > "$evidence/database-id.txt"
docker run --pull=never -d --name "$runner" --label "tip054.admission=$run_id" --read-only \
  --tmpfs /qa:rw,exec,mode=1777,size=2g --tmpfs /tmp:rw,exec,mode=1777,size=256m --memory=4g --cpus=4 --pids-limit=512 \
  --mount "type=bind,source=$experiment_dir,target=/work,readonly" --mount "type=bind,source=$evidence,target=/evidence" \
  --mount "type=bind,source=$v2_root/apps/backend/src,target=/workspace/v2/apps/backend/src,readonly" \
  --mount "type=bind,source=$v2_root/apps/backend/tests,target=/workspace/v2/apps/backend/tests,readonly" \
  --mount "type=bind,source=$v2_root/apps/backend/migrations,target=/workspace/v2/apps/backend/migrations,readonly" \
  --mount "type=bind,source=$v2_root/apps/backend/pyproject.toml,target=/workspace/v2/apps/backend/pyproject.toml,readonly" \
  --mount "type=bind,source=$v2_root/apps/backend/alembic.ini,target=/workspace/v2/apps/backend/alembic.ini,readonly" \
  -e OPENAI_API_KEY= -e ANTHROPIC_API_KEY= -e POSTGRES_DSN= -e MIGRATION_DSN= -e INTEGRATION_DATABASE_DSN= -e S3_SECRET_KEY= \
  -e PYTHONPATH= -e EXPECTED_SCHEMA_REVISION=0018_action_contracts --entrypoint /bin/sh rtr-tip054-local-qa:20261006 \
  -c 'exec env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin /bin/sh -c "sleep infinity"' > "$evidence/runner-id.txt"
printf '{"run_id":"%s","retained":true,"public_setup_separate":true,"published_ports":false,"product_source_read_only":true,"tmpfs_packages":true}\n' "$run_id" > "$evidence/fixture-started.json"
docker exec "$runner" env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin HOME=/tmp TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 /app/.venv/bin/python /work/setup_admission.py > "$evidence/setup.stdout.txt" 2> "$evidence/setup.stderr.txt"
docker network disconnect bridge "$runner"
docker network connect "$network" "$runner"
docker inspect "$runner" "$database" > "$evidence/fixtures-offline.json"
for attempt in $(seq 1 30); do docker exec "$database" pg_isready -U admission -d admission >/dev/null && break; sleep 1; done
docker exec "$database" pg_isready -U admission -d admission > "$evidence/database-ready.txt"
docker exec "$runner" env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin HOME=/tmp TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src DBOS_SYSTEM_DATABASE_URL=postgresql+psycopg://admission:synthetic-only@tip054-pg:5432/admission \
  /app/.venv/bin/python /work/admission_proof.py > "$evidence/proof.stdout.txt" 2> "$evidence/proof.stderr.txt"
echo "Retained runner=$runner postgres=$database internal_network=$network evidence=$evidence"
