#!/usr/bin/env bash
# Serving source + admitted DBOS; no private env/data or existing runtime writes.
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
v2_root=$(cd "$experiment_dir/../.." && pwd)
repo_root=$(cd "$v2_root/.." && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r1}
[[ "$run_id" =~ ^tip054-4b-full-[a-z0-9-]{1,30}$ ]] || exit 2
evidence="$experiment_dir/raw/$run_id"
runner="$run_id-runner"; pg="$run_id-pg"; redis="$run_id-redis"; minio="$run_id-minio"; network="$run_id-offline"
mkdir -p "$evidence"
[[ ! -e "$evidence/fixture-started.json" ]] || exit 2
for target in "$runner" "$pg" "$redis" "$minio"; do if docker inspect "$target" >/dev/null 2>&1; then echo "Refuse occupied target=$target"; exit 2; fi; done
images=(rtr-tip054-local-qa:20261006 pgvector/pgvector:pg16 redis:7-alpine quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z minio/mc:RELEASE.2025-07-21T05-28-08Z)
for image in "${images[@]}"; do docker image inspect "$image" >/dev/null; done
docker image inspect --format '{{json .Id}} {{json .Architecture}} {{json .RepoDigests}}' "${images[@]}" > "$evidence/images.txt"
docker network create --internal --label "tip054.executor=$run_id" "$network" > "$evidence/network-id.txt"
docker run --pull=never -d --name "$pg" --label "tip054.executor=$run_id" --network "$network" --network-alias tip054-pg \
  --memory=4g --cpus=2 --pids-limit=256 --tmpfs /var/lib/postgresql/data:rw,size=3g --tmpfs /tmp:rw,size=128m \
  -e POSTGRES_USER=rtr_tip054_local -e POSTGRES_PASSWORD=rtr_tip054_synthetic_only -e POSTGRES_DB=rtr_tip054_executor_verify \
  "${images[1]}" > "$evidence/pg-id.txt"
docker run --pull=never -d --name "$redis" --label "tip054.executor=$run_id" --network "$network" --network-alias tip054-redis \
  --memory=256m --cpus=1 --pids-limit=64 --tmpfs /data:rw,size=128m "${images[2]}" > "$evidence/redis-id.txt"
docker run --pull=never -d --name "$minio" --label "tip054.executor=$run_id" --network "$network" --network-alias tip054-minio \
  --memory=768m --cpus=1 --pids-limit=128 --tmpfs /data:rw,size=512m --tmpfs /tmp:rw,size=64m \
  -e MINIO_ROOT_USER=rtr_tip054_local -e MINIO_ROOT_PASSWORD=rtr_tip054_synthetic_only "${images[3]}" server /data > "$evidence/minio-id.txt"
mounts=()
for item in src tests migrations pyproject.toml uv.lock alembic.ini; do mounts+=(--mount "type=bind,source=$v2_root/apps/backend/$item,target=/workspace/v2/apps/backend/$item,readonly"); done
for item in scripts Makefile .gitignore .env.example compose.yaml; do mounts+=(--mount "type=bind,source=$v2_root/$item,target=/workspace/v2/$item,readonly"); done
for item in lib migrate parity pilot quality real_world run_eval.py run_parity.py run_real_world_acceptance.py; do mounts+=(--mount "type=bind,source=$v2_root/eval/$item,target=/workspace/v2/eval/$item,readonly"); done
mounts+=(--mount "type=bind,source=$repo_root/phase1_pilot/copilot_server.py,target=/workspace/phase1_pilot/copilot_server.py,readonly")
docker run --pull=never -d --name "$runner" --label "tip054.executor=$run_id" --read-only --memory=4g --cpus=4 --pids-limit=512 \
  --tmpfs /qa:rw,exec,mode=1777,size=2g --tmpfs /tmp:rw,exec,mode=1777,size=512m \
  "${mounts[@]}" --mount "type=bind,source=$experiment_dir,target=/work,readonly" --mount "type=bind,source=$evidence,target=/evidence" \
  -w /workspace/v2/apps/backend -e OPENAI_API_KEY= -e ANTHROPIC_API_KEY= -e POSTGRES_DSN= -e MIGRATION_DSN= -e INTEGRATION_DATABASE_DSN= -e S3_SECRET_KEY= \
  --entrypoint sh "${images[0]}" -c 'exec env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin /bin/sh -c "sleep infinity"' > "$evidence/runner-id.txt"
printf '{"run_id":"%s","retained":true,"caps":true,"no_private_env":true,"selected_source_read_only":true,"no_docker_socket":true,"published_ports":false}\n' "$run_id" > "$evidence/fixture-started.json"
docker exec "$runner" env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin HOME=/tmp TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 /app/.venv/bin/python /work/setup_admission.py > "$evidence/setup.stdout.txt" 2> "$evidence/setup.stderr.txt"
docker network disconnect bridge "$runner"; docker network connect "$network" "$runner"
for attempt in $(seq 1 30); do docker exec "$pg" pg_isready -U rtr_tip054_local -d rtr_tip054_executor_verify >/dev/null && break; sleep 1; done
docker exec "$pg" pg_isready -U rtr_tip054_local -d rtr_tip054_executor_verify > "$evidence/pg-ready.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE ROLE rtr_tip054_engine LOGIN PASSWORD 'rtr_tip054_synthetic_only' NOSUPERUSER NOCREATEDB NOCREATEROLE;" > "$evidence/engine-role.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c 'CREATE DATABASE rtr_tip054_engine OWNER rtr_tip054_engine;' >> "$evidence/engine-role.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_engine -v ON_ERROR_STOP=1 -c 'REVOKE CONNECT ON DATABASE rtr_tip054_engine FROM PUBLIC; GRANT CONNECT ON DATABASE rtr_tip054_engine TO rtr_tip054_engine;' >> "$evidence/engine-role.txt"
ready=0
for attempt in $(seq 1 30); do
  if docker run --pull=never --rm --label "tip054.executor=$run_id" --network "$network" --read-only --memory=128m --cpus=1 --pids-limit=64 --tmpfs /tmp:rw,size=32m --entrypoint sh "${images[4]}" -c 'export MC_CONFIG_DIR=/tmp/mc; mc alias set local http://tip054-minio:9000 rtr_tip054_local rtr_tip054_synthetic_only && mc mb --ignore-existing local/rtr-tip054-synthetic' >> "$evidence/minio-ready.txt" 2>&1; then ready=1; break; fi
  sleep 1
done
[[ "$ready" == 1 ]]
docker inspect "$runner" "$pg" "$redis" "$minio" > "$evidence/fixtures-offline.json"
echo "Owned runner=$runner pg=$pg network=$network evidence=$evidence"
