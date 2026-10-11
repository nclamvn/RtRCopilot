#!/usr/bin/env bash
# Technical-only explicit stages. pre_sql NEVER creates a database or runs SQL.
set -euo pipefail
new_dir=$(cd "$(dirname "$0")" && pwd)
experiment_dir=$(cd "$new_dir/.." && pwd)
r_dir="$experiment_dir/r"
stage=${1:?pre_sql sql_builder sql_review on off required}
gate_id=${2:?unique gate id required}
run_id=${TIP054_FULL_RUN_ID:?exact retained fixture required}
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
case "$stage" in pre_sql|sql_builder|sql_review|on|off) ;; *) exit 2 ;; esac
runner="$run_id-runner"; pg="$run_id-pg"
TIP054_REAL_DOCKER=$(command -v docker)
export TIP054_REAL_DOCKER
[[ "$TIP054_REAL_DOCKER" == /* && -x "$TIP054_REAL_DOCKER" && "$TIP054_REAL_DOCKER" != "$r_dir/bin/docker" ]] || exit 2
export TIP054_CAPACITY_TRACE="$experiment_dir/raw/$run_id/r_bind_$gate_id/capacity-create.jsonl"
export PATH="$r_dir/bin:$PATH"
bash "$r_dir/gate-boundary.sh" "$gate_id" begin
evidence="$experiment_dir/raw/$run_id/$gate_id"
[[ ! -e "$evidence" ]] || exit 2
mkdir "$evidence"
output="/evidence/$gate_id"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r9:/work/r:/work/r/r2
  APP_ENV=test POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_executor_verify
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic
  RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
config=/workspace/v2/apps/backend/pyproject.toml
rg --files "$new_dir" | rg '\.(py|sh)$' | LC_ALL=C sort | xargs shasum -a 256 > "$evidence/r9-before.sha256"
child_code=0
if [[ "$stage" == pre_sql ]]; then
  set +e
  exec_runner /app/.venv/bin/ruff check --config "$config" --no-cache src tests /work/r9 > "$evidence/ruff.stdout.txt" 2> "$evidence/ruff.stderr.txt"; ruff_code=$?
  exec_runner /app/.venv/bin/ruff format --config "$config" --check --no-cache /work/r9 > "$evidence/format.stdout.txt" 2> "$evidence/format.stderr.txt"; format_code=$?
  exec_runner /app/.venv/bin/mypy --no-incremental --cache-dir=/dev/null > "$evidence/mypy.stdout.txt" 2> "$evidence/mypy.stderr.txt"; mypy_code=$?
  exec_runner /app/.venv/bin/python -c 'import rtr_copilot.api.main,rtr_copilot.worker.main; from importlib.metadata import version; assert version("dbos")=="3.2.0"; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; assert version("psycopg")=="3.2.9"; print("EXACT_IMPORTS_PASS")' > "$evidence/import.stdout.txt" 2> "$evidence/import.stderr.txt"; import_code=$?
  exec_runner /app/.venv/bin/python -m pytest -q -c "$config" -p conftest -p no:cacheprovider --collect-only /work/r9/test_pool_boundary_builder_unit.py /work/r9/test_pool_boundary_review_unit.py /work/r9/test_pool_boundary_builder_integration.py /work/r9/test_pool_boundary_review_integration.py > "$evidence/collection.stdout.txt" 2> "$evidence/collection.stderr.txt"; collection_code=$?
  exec_runner /app/.venv/bin/python -c '
# R9_COLLECTION_GUARD_BEGIN
import ast
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

MODULES = (
    ("test_pool_boundary_builder_unit.py", 12),
    ("test_pool_boundary_review_unit.py", 4),
    ("test_pool_boundary_builder_integration.py", 6),
    ("test_pool_boundary_review_integration.py", 4),
)

def expected_ids(root):
    expected = Counter()
    for filename, count in MODULES:
        path = root / filename
        if path.stat().st_size > 262144:
            raise ValueError("bounded fixed-module source exceeded")
        tree = ast.parse(path.read_text())
        if any(isinstance(item, ast.ClassDef) and item.name.startswith("Test")
               for item in tree.body):
            raise ValueError("unexpected nested test collection shape")
        names = [item.name for item in tree.body
                 if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and item.name.startswith("test_")]
        if len(names) != count or len(set(names)) != count:
            raise ValueError("fixed-module control count/identity changed")
        expected.update(filename + "::" + name for name in names)
    return expected

def normalize(text, expected):
    owners = defaultdict(list)
    for identifier, count in expected.items():
        if count != 1:
            raise ValueError("duplicate expected identity")
        filename, name = identifier.split("::")
        owners[name].append(filename)
    if any(len(filenames) != 1 for filenames in owners.values()):
        raise ValueError("ambiguous expected bare identity")
    seen = Counter()
    for raw in text.splitlines():
        line = raw.strip()
        if not (line.startswith("::") or ".py::" in line or "::test_" in line):
            continue
        parts = line.split("::")
        if len(parts) != 2 or re.fullmatch(r"test_[a-zA-Z0-9_]+", parts[1]) is None:
            raise ValueError("unexpected nested/parameterized collection identity")
        prefix, name = parts
        if name not in owners:
            raise ValueError("unknown collected name")
        filename = owners[name][0]
        if prefix not in ("", filename, "/work/r9/" + filename):
            raise ValueError("unknown or wrong-module collected identity")
        seen[filename + "::" + name] += 1
    if seen != expected or any(count != 1 for count in seen.values()):
        raise ValueError("missing/duplicate/unknown collected identity")
    return sorted(seen)

if __name__ == "__main__":
    expected = expected_ids(Path("/work/r9"))
    path = Path(sys.argv[1])
    if path.stat().st_size > 1048576:
        raise ValueError("bounded collection stdout exceeded")
    identifiers = normalize(path.read_text(), expected)
    print(json.dumps({"status": "PASS", "identifiers": identifiers,
                      "modules": dict(MODULES), "structural": 16, "sql": 10,
                      "total": len(identifiers)}, sort_keys=True))
# R9_COLLECTION_GUARD_END
' "$output/collection.stdout.txt" > "$evidence/collection-guard.stdout.txt" 2> "$evidence/collection-guard.stderr.txt"
  guard_code=$?
  if [[ "$collection_code" == 0 && "$guard_code" != 0 ]]; then collection_code=2; fi
  structural_code=-1
  if [[ "$ruff_code" == 0 && "$format_code" == 0 && "$mypy_code" == 0 && "$import_code" == 0 && "$collection_code" == 0 ]]; then
    exec_runner /app/.venv/bin/python -m pytest -q -c "$config" -p conftest -p no:cacheprovider --junitxml="$output/structural.xml" /work/r9/test_pool_boundary_builder_unit.py /work/r9/test_pool_boundary_review_unit.py > "$evidence/structural.stdout.txt" 2> "$evidence/structural.stderr.txt"; structural_code=$?
  fi
  set -e
  for result in "$ruff_code" "$format_code" "$mypy_code" "$import_code" "$collection_code" "$structural_code"; do [[ "$result" == 0 ]] || child_code=1; done
  printf '{"ruff":%d,"format":%d,"mypy":%d,"import":%d,"collection":%d,"structural":%d,"sql_ran":false}\n' "$ruff_code" "$format_code" "$mypy_code" "$import_code" "$collection_code" "$structural_code" > "$evidence/returncodes.json"
else
  # Explicit non-pre_sql stage requires separate Contractor runtime authority.
  [[ "${TIP054_R9_RUNTIME_ACK:-}" == "$stage" ]] || exit 2
  database="rtr_tip054_r9_${gate_id}"; engine="rtr_tip054_r9e_${gate_id}"
  docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$database\";" > "$evidence/databases.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$engine\" OWNER rtr_tip054_engine;" >> "$evidence/databases.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d "$engine" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$engine\" TO rtr_tip054_engine;" >> "$evidence/databases.txt"
  base+=(POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
    INTEGRATION_DATABASE_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
    MIGRATION_DSN="postgresql://rtr_tip054_local:rtr_tip054_synthetic_only@tip054-pg:5432/$database"
    ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$engine"
    ACTION_EXECUTOR_ENABLED=true LIMITS_RATE_RENDER_MAX=5000 LIMITS_RATE_DEFAULT_READ_MAX=5000)
  exec_runner /app/.venv/bin/alembic upgrade head > "$evidence/migrate.stdout.txt" 2> "$evidence/migrate.stderr.txt"
  docker exec "$pg" psql -U rtr_tip054_local -d "$database" -v ON_ERROR_STOP=1 -c "ALTER ROLE rtr_app LOGIN PASSWORD 'rtr_tip054_synthetic_only'; REVOKE CONNECT ON DATABASE \"$database\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$database\" TO rtr_app;" >> "$evidence/databases.txt"
  set +e
  case "$stage" in
    sql_builder|sql_review)
      owner=${stage#sql_}
      exec_runner /app/.venv/bin/python -m pytest -q -rs -c "$config" -p conftest -p no:cacheprovider -o asyncio_default_test_loop_scope=session --junitxml="$output/sql.xml" "/work/r9/test_pool_boundary_${owner}_integration.py" > "$evidence/sql.stdout.txt" 2> "$evidence/sql.stderr.txt"
      child_code=$?
      printf '{"sql_returncode":%d,"stage":"%s"}\n' "$child_code" "$stage" > "$evidence/returncodes.json" ;;
    on)
      exec_runner timeout --signal=TERM --kill-after=10 190 /app/.venv/bin/python /work/r9/run_observed.py "$output/run" > "$evidence/latency.stdout.txt" 2> "$evidence/latency.stderr.txt"
      load_code=$?; child_code=$load_code
      exec_runner /app/.venv/bin/python /work/r/r2/summarize_audit_tail.py "$output/run" --verify-chain > "$evidence/audit.stdout.txt" 2> "$evidence/audit.stderr.txt"; metric_code=$?
      [[ "$metric_code" == 0 ]] || child_code=$metric_code
      exec_runner /app/.venv/bin/python /work/r9/analyze.py "$output/run" "$output/analysis" > "$evidence/analysis.stdout.txt" 2> "$evidence/analysis.stderr.txt"; analysis_code=$?
      [[ "$analysis_code" == 0 ]] || child_code=$analysis_code
      printf '{"load_returncode":%d,"metric_chain_returncode":%d,"analysis_returncode":%d}\n' "$load_code" "$metric_code" "$analysis_code" > "$evidence/returncodes.json" ;;
    off)
      exec_runner timeout --signal=TERM --kill-after=10 190 /app/.venv/bin/python /work/r/run_phase_baseline.py "$output/run" off > "$evidence/latency.stdout.txt" 2> "$evidence/latency.stderr.txt"
      child_code=$?
      printf '{"load_returncode":%d,"observer":"unchanged_off"}\n' "$child_code" > "$evidence/returncodes.json" ;;
  esac
  set -e
fi
rg --files "$new_dir" | rg '\.(py|sh)$' | LC_ALL=C sort | xargs shasum -a 256 > "$evidence/r9-after.sha256"
cmp "$evidence/r9-before.sha256" "$evidence/r9-after.sha256" || child_code=1
bash "$r_dir/gate-boundary.sh" "$gate_id" end "$child_code"
exit "$child_code"
