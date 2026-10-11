#!/usr/bin/env bash
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_BKO_RUN_ID:-tip054-bko-20261006}
[[ "$run_id" =~ ^[a-z0-9][a-z0-9-]{0,48}$ ]] || { echo 'invalid run id'; exit 2; }
runner="$run_id-runner"
database="$run_id-postgres"
network="$run_id-offline"
qa_image=rtr-tip054-local-qa:20261006
pg_image=postgres:18-alpine
evidence="$experiment_dir/raw/$run_id"
mkdir -p "$evidence"
[[ ! -f "$evidence/fixture-started.json" ]] || { echo 'Evidence run exists; choose a fresh run ID'; exit 2; }
for target in "$runner" "$database"; do
  if docker inspect "$target" >/dev/null 2>&1; then
    echo "Fixture name already exists; refusing to reuse or remove $target"
    exit 2
  fi
done
docker image inspect --format '{{json .Id}} {{json .Architecture}} {{json .RepoDigests}} {{json .Created}}' "$qa_image" "$pg_image" > "$evidence/images.txt"
docker ps -a --format '{{.ID}} {{.Names}} {{.Status}}' > "$evidence/existing-containers.txt"
cleanup() {
  [[ "${TIP054_BKO_KEEP_FIXTURES:-0}" != 1 ]] || return 0
  for target in "$runner" "$database"; do
    owner=$(docker inspect --format '{{index .Config.Labels "tip054.bakeoff"}}' "$target" 2>/dev/null || true)
    [[ "$owner" != "$run_id" ]] || docker rm -f "$target" >/dev/null
  done
  owner=$(docker network inspect --format '{{index .Labels "tip054.bakeoff"}}' "$network" 2>/dev/null || true)
  [[ "$owner" != "$run_id" ]] || docker network rm "$network" >/dev/null
}
trap cleanup EXIT
docker network create --internal --label "tip054.bakeoff=$run_id" "$network" > "$evidence/network-id.txt"
docker run --pull=never -d --name "$database" --label "tip054.bakeoff=$run_id" --network "$network" \
  --tmpfs /var/lib/postgresql:rw,size=768m --tmpfs /tmp:rw,size=64m --memory=1g --cpus=2 \
  -e POSTGRES_USER=bakeoff -e POSTGRES_PASSWORD=synthetic-only -e POSTGRES_DB=bakeoff \
  "$pg_image" > "$evidence/database-id.txt"
docker run --pull=never -d --name "$runner" --label "tip054.bakeoff=$run_id" \
  --tmpfs /bakeoff:rw,exec,size=3g --tmpfs /tmp:rw,exec,size=128m --memory=4g --cpus=4 \
  --mount "type=bind,source=$experiment_dir,target=/work,readonly" \
  --mount "type=bind,source=$evidence,target=/evidence" \
  -e PYTHONPATH=/work:/bakeoff/packages -e PIP_CACHE_DIR=/bakeoff/pip-cache -e TMPDIR=/tmp \
  -e "DBOS_SYSTEM_DATABASE_URL=postgresql://bakeoff:synthetic-only@$database:5432/bakeoff" \
  --entrypoint sh "$qa_image" -c 'sleep infinity' > "$evidence/runner-id.txt"
printf '{"run_id":"%s","public_setup_separate":true,"database_tmpfs":true,"published_ports":false}\n' "$run_id" > "$evidence/fixture-started.json"
docker exec "$runner" python /work/setup_runtime.py > "$evidence/setup.stdout.txt" 2> "$evidence/setup.stderr.txt"
docker exec "$runner" python -c 'import shutil; shutil.copyfile("/bakeoff/setup-provenance.json","/evidence/setup-provenance.json")'
docker network disconnect bridge "$runner"
docker network connect "$network" "$runner"
for attempt in $(seq 1 30); do
  docker exec "$database" pg_isready -U bakeoff -d bakeoff >/dev/null && break
  sleep 1
done
docker exec "$database" pg_isready -U bakeoff -d bakeoff > "$evidence/database-ready.txt"
docker exec "$runner" /bakeoff/bin/temporal --version > "$evidence/temporal-version.txt"
docker exec "$runner" /bakeoff/bin/temporal server start-dev --help > "$evidence/temporal-server-help.txt"
docker exec -d "$runner" sh -c '/bakeoff/bin/temporal server start-dev --ip 127.0.0.1 --port 7233 --headless --db-filename /bakeoff/temporal.sqlite > /bakeoff/temporal-server.log 2>&1'
for attempt in $(seq 1 40); do
  docker exec "$runner" /bakeoff/bin/temporal operator cluster health >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$runner" /bakeoff/bin/temporal operator cluster health > "$evidence/temporal-ready.txt"
docker inspect "$runner" "$database" > "$evidence/fixtures-offline.json"
set +e
docker exec "$runner" python /work/dbos_adapter.py --mode native-proofs --state-dir /bakeoff/native/dbos-native --requests /dev/null --output /evidence/dbos-native/summary.json --evidence-dir /evidence/dbos-native > "$evidence/dbos-native.stdout.txt" 2> "$evidence/dbos-native.stderr.txt"
dbos_native_code=$?
docker exec "$runner" python /work/temporal_adapter.py --mode native-proofs --state-dir /evidence/temporal-native --native-runtime-root /bakeoff/native --requests /dev/null --output /evidence/temporal-native-summary.json > "$evidence/temporal-native.stdout.txt" 2> "$evidence/temporal-native.stderr.txt"
temporal_native_code=$?
docker exec "$runner" python -m unittest discover -s /work -p 'test_*.py' -v > "$evidence/unit.stdout.txt" 2> "$evidence/unit.stderr.txt"
unit_code=$?
docker exec "$runner" python /work/driver.py run --out /evidence/results > "$evidence/driver.stdout.txt" 2> "$evidence/driver.stderr.txt"
driver_code=$?
docker exec "$runner" python /work/driver.py validate --out /evidence/results > "$evidence/validation.json" 2> "$evidence/validation.stderr.txt"
validation_code=$?
set -e
docker exec "$runner" python -c 'import shutil; shutil.copyfile("/bakeoff/temporal-server.log","/evidence/temporal-server.log")'
docker exec "$database" psql -U bakeoff -d bakeoff -c 'SELECT datname,pg_database_size(datname),tup_inserted,tup_updated,tup_deleted FROM pg_stat_database WHERE datname=current_database();' > "$evidence/engine-database-observation.txt"
docker stats --no-stream "$runner" "$database" > "$evidence/container-footprint.txt"
printf '{"unit_returncode":%d,"driver_returncode":%d,"validation_returncode":%d,"dbos_native_returncode":%d,"temporal_native_returncode":%d}\n' "$unit_code" "$driver_code" "$validation_code" "$dbos_native_code" "$temporal_native_code" > "$evidence/returncodes.json"
[[ "$unit_code" == 0 && "$driver_code" == 0 && "$validation_code" == 0 && "$dbos_native_code" == 0 && "$temporal_native_code" == 0 ]]
