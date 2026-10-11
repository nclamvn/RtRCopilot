#!/usr/bin/env bash
# NEW R11 authoring: every execution stage needs a separate Contractor ACK.
# pre_sql cannot CREATE a database or execute integration controls.
set -euo pipefail
new_dir=$(cd "$(dirname "$0")" && pwd)
experiment_dir=$(cd "$new_dir/.." && pwd)
repo_root=$(cd "$experiment_dir/../../.." && pwd)
r_dir="$experiment_dir/r"
stage=${1:?pre_sql sql_builder sql_review on off required}
gate_id=${2:?fresh r11-prefixed gate ID required}
[[ $# == 2 && "$gate_id" =~ ^r11_[a-z0-9_]{1,20}$ ]] || exit 2
case "$stage" in pre_sql|sql_builder|sql_review|on|off) ;; *) exit 2 ;; esac
[[ "${TIP054_R11_STAGE_ACK:-}" == "$stage" ]] || exit 2
run_id=${TIP054_FULL_RUN_ID:?exact retained fixture required}
[[ "$run_id" == tip054-4b-full-20261007-r5qa1 ]] || exit 2
[[ "${TIP054_PRODUCT_FROZEN_SHA256:-}" == 56fa5d71fc61efc6dd3dcae8ce0a313a5b0a7f3d410145093f45365c2704e209 ]] || exit 2
expected_stage=${TIP054_R11_STAGE_SHA256:?explicit frozen NEW stage SHA required}
[[ "$expected_stage" =~ ^[a-f0-9]{64}$ ]] || exit 2
read -r actual_stage ignored < <(shasum -a 256 "$new_dir/run-stage.sh")
[[ "$actual_stage" == "$expected_stage" ]] || exit 2
source_manifest=${TIP054_R11_SOURCE_MANIFEST:?fresh frozen NEW source manifest required}
manifest_sha=${TIP054_R11_SOURCE_MANIFEST_SHA256:?explicit source manifest SHA required}
[[ "$source_manifest" == "$new_dir"/source_freeze_*/manifest.json && "$manifest_sha" =~ ^[a-f0-9]{64}$ ]] || exit 2
# Manifest is generated only after all authors HOLD; includes this stage's SHA.
python3 -B - "$new_dir" "$source_manifest" "$manifest_sha" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root, manifest = map(Path, sys.argv[1:3])
assert manifest.is_file() and not manifest.is_symlink()
assert manifest.resolve() == manifest and root.resolve() == root
raw = manifest.read_bytes()
assert len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == sys.argv[3]
packet = json.loads(raw)
assert packet["product_sha256"] == "56fa5d71fc61efc6dd3dcae8ce0a313a5b0a7f3d410145093f45365c2704e209"
declared = {"run-stage.sh", "overhead_observer.py", "run_observed.py", "analyze.py",
            "test_observer_exposure_builder_unit.py", "test_observer_exposure_review_unit.py",
            "test_observer_exposure_builder_integration.py", "test_observer_exposure_review_integration.py"}
assert set(packet["files"]) == declared
assert {p.name for p in root.iterdir() if p.suffix in {".py", ".sh"}} == declared
total = 0
for name, expected in packet["files"].items():
    path = root / name
    assert path.is_file() and not path.is_symlink() and path.resolve() == path
    size = path.stat().st_size
    total += size
    assert size == expected["bytes"] and size <= 524288 and total <= 2097152
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"], name
print("FROZEN_EXACT_NEW_EIGHT_SOURCE_FILES_PASS")
PY
# These selected preflight inputs are immutable source/cap baselines, not Env.
[[ $(shasum -a 256 "$new_dir/preflight_e1/source-history-before.json" | awk '{print $1}') == c1659dee44535956aebf9abed06128f57d0af9cae309d4b41deac55ede4ed635 ]] || exit 2
[[ $(shasum -a 256 "$new_dir/preflight_e1/fixture-preflight.json" | awk '{print $1}') == 20f09111f8ae374a55792d1e346a1a8d47134e4453624c8108850460b527252e ]] || exit 2
TIP054_REAL_DOCKER=$(command -v docker)
export TIP054_REAL_DOCKER
[[ "$TIP054_REAL_DOCKER" == /* && -x "$TIP054_REAL_DOCKER" && "$TIP054_REAL_DOCKER" != "$r_dir/bin/docker" ]] || exit 2
runner="$run_id-runner"; pg="$run_id-pg"
evidence="$experiment_dir/raw/$run_id/$gate_id"
[[ ! -e "$evidence" && ! -e "$experiment_dir/raw/$run_id/r_bind_$gate_id" ]] || exit 2
export TIP054_CAPACITY_TRACE="$experiment_dir/raw/$run_id/r_bind_$gate_id/capacity-create.jsonl"
export PATH="$r_dir/bin:$PATH"
cd "$repo_root"

# Selected Docker fields only. No Config.Env, private environment, SQL or SDK.
python3 -B - "$new_dir/preflight_e1/fixture-preflight.json" "$TIP054_REAL_DOCKER" <<'PY'
import json
import subprocess
import sys

baseline = json.load(open(sys.argv[1]))
docker = sys.argv[2]

def call(*args):
    return subprocess.check_output([docker, *args], text=True, timeout=20)

def mounts(rows):
    return sorted([{k: row.get(k) for k in ("Type", "Source", "Destination", "RW", "Propagation")}
                   for row in rows], key=lambda row: row["Destination"])

for old in baseline["containers"]:
    fmt = ('{"Id":{{json .Id}},"Owner":{{json (index .Config.Labels "tip054.executor")}},'
           '"ImageId":{{json .Image}},"ImageRef":{{json .Config.Image}},'
           '"Mounts":{{json .Mounts}},"Ports":{{json .NetworkSettings.Ports}},'
           '"Networks":{{json .NetworkSettings.Networks}},'
           '"Running":{{json .State.Running}},"Paused":{{json .State.Paused}},'
           '"Restarting":{{json .State.Restarting}},"OOMKilled":{{json .State.OOMKilled}},'
           '"RestartCount":{{json .RestartCount}},'
           '"Caps":{"Memory":{{json .HostConfig.Memory}},"NanoCpus":{{json .HostConfig.NanoCpus}},'
           '"PidsLimit":{{json .HostConfig.PidsLimit}},"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},'
           '"CapDrop":{{json .HostConfig.CapDrop}},"SecurityOpt":{{json .HostConfig.SecurityOpt}},'
           '"Tmpfs":{{json .HostConfig.Tmpfs}}}}')
    now = json.loads(call("inspect", "--format", fmt, old["Id"]))
    assert now["Id"] == old["Id"] and now["Owner"] == old["ExecutorOwner"]
    assert all(now[k] == old[k] for k in ("ImageId", "ImageRef", "Caps", "Ports", "RestartCount"))
    assert mounts(now["Mounts"]) == mounts(old["Mounts"])
    assert now["Running"] and not any(now[k] for k in ("Paused", "Restarting", "OOMKilled"))
    assert set(now["Networks"]) == set(old["Networks"])
    assert all(now["Networks"][k]["NetworkID"] == old["Networks"][k]["NetworkID"] for k in now["Networks"])
    if old["Name"].endswith("-runner"):
        top = call("top", old["Id"], "-eo", "pid,comm,args")
        assert all(row.split()[1] in {"sh", "sleep"} for row in top.strip().splitlines()[1:])
network = baseline["network"]
fmt = ('{"Id":{{json .Id}},"Internal":{{json .Internal}},'
       '"Owner":{{json (index .Labels "tip054.executor")}},"Containers":{{json .Containers}}}')
now = json.loads(call("network", "inspect", "--format", fmt, network["Id"]))
assert now["Id"] == network["Id"] and now["Internal"] is True
assert now["Owner"] == network["ExecutorOwner"] and set(now["Containers"]) == set(network["Containers"])
print("EXACT_RETAINED_FIXTURE_IDLE_PASS")
PY

bash "$r_dir/gate-boundary.sh" "$gate_id" begin
mkdir "$evidence"
output="/evidence/$gate_id"
snapshot() {
  rg --files "$new_dir" | rg '\.(py|sh)$' | LC_ALL=C sort | xargs shasum -a 256 > "$1"
}
protected() {
  python3 -B - "$repo_root" "$new_dir/preflight_e1/source-history-before.json" "$1" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root, baseline, output = map(Path, sys.argv[1:])
expected = json.loads(baseline.read_text())
experiment = root / "v2/experiments/action_executor"

def path(key):
    if key.startswith("verification_r/"):
        return experiment / "r" / key.removeprefix("verification_r/")
    if key.startswith("verification/"):
        return experiment / key.removeprefix("verification/")
    if key.startswith("v2/"):
        return root / key
    return root / "v2/apps/backend" / key

result = {}
for name in ("old400", "archives73", "current8"):
    current = {}
    for key, digest in expected[name].items():
        item = path(key) if name == "old400" else root / key
        assert item.is_file() and not item.is_symlink()
        current[key] = hashlib.sha256(item.read_bytes()).hexdigest()
        assert current[key] == digest, key
    result[name] = current
# Stream only the exact frozen protected rows, outside all measured HTTP work.
def digest(item):
    assert item.is_file() and not item.is_symlink()
    state = hashlib.sha256()
    with item.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            state.update(chunk)
    return state.hexdigest()

r10 = experiment / "analysis/tip054-4b-r10"
history_path = r10 / "technical-freeze-e1/history-before.json"
assert digest(history_path) == "5ede35abc96f09bbc95639146920b615d702dead886531b0b459ce47b94ed148"
history = json.loads(history_path.read_text())
total = 0
for folder, key, count in (("raw", "raw_rows", 7666), ("analysis", "analysis_rows", 92)):
    rows = history[key]
    assert len(rows) == count
    for relative, expected_digest in rows:
        item = experiment / folder / relative
        total += item.stat().st_size
        assert total <= 2147483648
        assert digest(item) == expected_digest, relative
snapshot_path = r10 / "final_closure_e1/R10-snapshot.json"
assert digest(snapshot_path) == "a4490626ef13aa3c89015506689a336c8dcf74a5aa475d17e246e207b231c6b4"
snapshot = json.loads(snapshot_path.read_text())
assert len(snapshot["new_artifacts"]) == 44
for relative, entry in snapshot["new_artifacts"].items():
    item = root / relative
    assert item.stat().st_size == entry["bytes"] and digest(item) == entry["sha256"], relative
result["protected_history"] = {"raw7666_match": True, "analysis92_match": True,
                               "R10_artifact44_match": True, "streamed_bytes": total,
                               "excludes": "Only NEW R11 artifacts and permitted post-seal report annotations"}
with output.open("x") as stream:
    json.dump(result, stream, indent=2, sort_keys=True)
    stream.write("\n")
PY
}
finish() {
  original_code=$?
  trap - EXIT
  set +e
  snapshot "$evidence/r11-after.sha256"; snapshot_code=$?
  protected "$evidence/protected-after.json"; protected_code=$?
  cmp "$evidence/r11-before.sha256" "$evidence/r11-after.sha256"; new_binding_code=$?
  cmp "$evidence/protected-before.json" "$evidence/protected-after.json"; old_binding_code=$?
  final_code=$original_code
  for code in "$snapshot_code" "$protected_code" "$new_binding_code" "$old_binding_code"; do
    [[ "$code" == 0 ]] || final_code=1
  done
  bash "$r_dir/gate-boundary.sh" "$gate_id" end "$final_code"; boundary_code=$?
  [[ "$boundary_code" == 0 ]] || final_code=$boundary_code
  printf '{"original_returncode":%d,"snapshot":%d,"protected":%d,"new_binding":%d,"old_binding":%d,"boundary":%d,"final_returncode":%d}\n' \
    "$original_code" "$snapshot_code" "$protected_code" "$new_binding_code" "$old_binding_code" "$boundary_code" "$final_code" > "$evidence/closure-returncodes.json"
  exit "$final_code"
}
trap finish EXIT
snapshot "$evidence/r11-before.sha256"
protected "$evidence/protected-before.json"

base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 TMPDIR=/tmp
  PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src:/workspace/v2/apps/backend/tests:/work/r11:/work/r9:/work/r:/work/r/r2
  APP_ENV=test POSTGRES_DSN=postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_executor_verify
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000
  S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic
  RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
config=/workspace/v2/apps/backend/pyproject.toml
unit_builder=/work/r11/test_observer_exposure_builder_unit.py
unit_review=/work/r11/test_observer_exposure_review_unit.py
sql_builder=/work/r11/test_observer_exposure_builder_integration.py
sql_review=/work/r11/test_observer_exposure_review_integration.py
junit_guard() {
  exec_runner /app/.venv/bin/python -B -c '
import json,sys,xml.etree.ElementTree as ET
root=ET.parse(sys.argv[1]).getroot()
cases=list(root.iter("testcase"))
bad=sum(len(list(case.iter(tag))) for case in cases for tag in ("failure","error","skipped"))
assert len(cases)==int(sys.argv[2]) and bad==0, (len(cases),bad)
print(json.dumps({"actual_tests":len(cases),"failures_errors_skips":bad,"status":"PASS"},sort_keys=True))
' "$1" "$2"
}

if [[ "$stage" == pre_sql ]]; then
  set +e
  exec_runner /app/.venv/bin/python -B -c 'import os,pathlib; assert pathlib.Path.cwd()==pathlib.Path("/workspace/v2/apps/backend"); assert pathlib.Path("src").is_dir() and pathlib.Path("tests").is_dir(); print("EXACT_BACKEND_WORKINGDIR_PASS")' > "$evidence/workingdir.stdout.txt" 2> "$evidence/workingdir.stderr.txt"; workingdir_code=$?
  exec_runner /app/.venv/bin/python -B -c 'import ast,pathlib; paths=sorted(pathlib.Path("/work/r11").glob("*.py")); assert len(paths)<=12; [compile(ast.parse(p.read_text()),str(p),"exec") for p in paths]; print("NEW_R11_SYNTAX_PASS",len(paths))' > "$evidence/syntax.stdout.txt" 2> "$evidence/syntax.stderr.txt"; syntax_code=$?
  exec_runner /app/.venv/bin/ruff check --config "$config" --no-cache src tests /work/r11 > "$evidence/ruff.stdout.txt" 2> "$evidence/ruff.stderr.txt"; ruff_code=$?
  exec_runner /app/.venv/bin/ruff format --config "$config" --check --no-cache /work/r11 > "$evidence/format.stdout.txt" 2> "$evidence/format.stderr.txt"; format_code=$?
  exec_runner /app/.venv/bin/mypy --no-incremental --cache-dir=/dev/null > "$evidence/mypy.stdout.txt" 2> "$evidence/mypy.stderr.txt"; mypy_code=$?
  exec_runner /app/.venv/bin/python -B -c 'import rtr_copilot.api.main,rtr_copilot.worker.main; from importlib.metadata import version; assert version("dbos")=="3.2.0"; assert version("sqlalchemy")=="2.0.43"; assert version("asyncpg")=="0.30.0"; assert version("psycopg")=="3.2.9"; print("EXACT_SERVING_IMPORTS_PASS")' > "$evidence/import.stdout.txt" 2> "$evidence/import.stderr.txt"; import_code=$?
  exec_runner /app/.venv/bin/python -B -m pytest -q -c "$config" -p conftest -p no:cacheprovider --collect-only "$unit_builder" "$unit_review" "$sql_builder" "$sql_review" > "$evidence/collection.stdout.txt" 2> "$evidence/collection.stderr.txt"; collection_code=$?
  exec_runner /app/.venv/bin/python -B -c '
import ast,json,re,sys
from collections import Counter,defaultdict
from pathlib import Path
modules=(("test_observer_exposure_builder_unit.py",4),("test_observer_exposure_review_unit.py",4),("test_observer_exposure_builder_integration.py",2),("test_observer_exposure_review_integration.py",2))
expected=Counter(); owners=defaultdict(list)
for filename,count in modules:
    path=Path("/work/r11")/filename
    assert path.stat().st_size<=262144
    tree=ast.parse(path.read_text())
    assert not any(isinstance(n,ast.ClassDef) and n.name.startswith("Test") for n in tree.body)
    names=[n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith("test_")]
    assert len(names)==len(set(names))==count
    for name in names: expected[filename+"::"+name]+=1; owners[name].append(filename)
assert all(len(v)==1 for v in owners.values())
path=Path(sys.argv[1]);assert path.stat().st_size<=1048576
seen=Counter()
for raw in path.read_text().splitlines():
    line=raw.strip()
    if not(line.startswith("::") or ".py::" in line or "::test_" in line):continue
    parts=line.split("::");assert len(parts)==2 and re.fullmatch(r"test_[a-zA-Z0-9_]+",parts[1])
    prefix,name=parts;assert name in owners
    filename=owners[name][0];assert prefix in ("",filename,"/work/r11/"+filename)
    seen[filename+"::"+name]+=1
assert seen==expected and all(v==1 for v in seen.values())
print(json.dumps({"status":"PASS","modules":dict(modules),"structural":8,"SQL":4,"total":12,"identifiers":sorted(seen)},sort_keys=True))
' "$output/collection.stdout.txt" > "$evidence/collection-guard.stdout.txt" 2> "$evidence/collection-guard.stderr.txt"; guard_code=$?
  structural_code=-1; junit_code=-1
  if [[ "$workingdir_code" == 0 && "$syntax_code" == 0 && "$ruff_code" == 0 && "$format_code" == 0 && "$mypy_code" == 0 && "$import_code" == 0 && "$collection_code" == 0 && "$guard_code" == 0 ]]; then
    exec_runner /app/.venv/bin/python -B -m pytest -q -rs -c "$config" -p conftest -p no:cacheprovider --junitxml="$output/structural.xml" "$unit_builder" "$unit_review" > "$evidence/structural.stdout.txt" 2> "$evidence/structural.stderr.txt"; structural_code=$?
    if [[ "$structural_code" == 0 ]]; then junit_guard "$output/structural.xml" 8 > "$evidence/junit-guard.stdout.txt" 2> "$evidence/junit-guard.stderr.txt"; junit_code=$?; fi
  fi
  set -e
  printf '{"workingdir":%d,"syntax":%d,"ruff":%d,"format":%d,"mypy":%d,"import":%d,"collection":%d,"collection_guard":%d,"structural":%d,"junit_guard":%d,"SQL_ran":false}\n' "$workingdir_code" "$syntax_code" "$ruff_code" "$format_code" "$mypy_code" "$import_code" "$collection_code" "$guard_code" "$structural_code" "$junit_code" > "$evidence/returncodes.json"
  child_code=0
  for code in "$workingdir_code" "$syntax_code" "$ruff_code" "$format_code" "$mypy_code" "$import_code" "$collection_code" "$guard_code" "$structural_code" "$junit_code"; do [[ "$code" == 0 ]] || child_code=1; done
  exit "$child_code"
fi

# Every actual CREATE goes through the ORIGINAL unchanged host shim above.
database="rtr_tip054_r11_${gate_id}"; engine="rtr_tip054_r11e_${gate_id}"
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
    exec_runner timeout --signal=TERM --kill-after=10 120 /app/.venv/bin/python -B -m pytest -q -rs -c "$config" -p conftest -p no:cacheprovider -o asyncio_default_test_loop_scope=session --junitxml="$output/sql.xml" "/work/r11/test_observer_exposure_${owner}_integration.py" > "$evidence/sql.stdout.txt" 2> "$evidence/sql.stderr.txt"
    child_code=$?; junit_code=-1
    if [[ "$child_code" == 0 ]]; then junit_guard "$output/sql.xml" 2 > "$evidence/junit-guard.stdout.txt" 2> "$evidence/junit-guard.stderr.txt"; junit_code=$?; fi
    printf '{"SQL_returncode":%d,"junit_guard":%d,"stage":"%s","declared_unique_SQL":2}\n' "$child_code" "$junit_code" "$stage" > "$evidence/returncodes.json"
    [[ "$junit_code" == 0 ]] || child_code=1 ;;
  on)
    exec_runner timeout --signal=TERM --kill-after=10 190 /app/.venv/bin/python -B /work/r11/run_observed.py "$output/run" > "$evidence/latency.stdout.txt" 2> "$evidence/latency.stderr.txt"
    load_code=$?; child_code=$load_code
    exec_runner /app/.venv/bin/python -B /work/r/r2/summarize_audit_tail.py "$output/run" --verify-chain > "$evidence/audit.stdout.txt" 2> "$evidence/audit.stderr.txt"; metric_code=$?
    [[ "$metric_code" == 0 ]] || child_code=$metric_code
    # Original R9 graph check only. NEW paired R11 analyzer needs OFF too and
    # is run HOST-ONLY after both packets, under a separate Contractor ACK.
    exec_runner /app/.venv/bin/python -B /work/r9/analyze.py "$output/run" "$output/r9-analysis" > "$evidence/analysis.stdout.txt" 2> "$evidence/analysis.stderr.txt"; analysis_code=$?
    [[ "$analysis_code" == 0 ]] || child_code=$analysis_code
    # Strict NEW raw graph/zero-fault gate, not the paired/cohort analysis.
    exec_runner /app/.venv/bin/python -B -c '
import json,sys
from pathlib import Path
from overhead_observer import decoded_records
path=Path(sys.argv[1]);assert path.stat().st_size<=134217728
packet=json.loads(path.read_bytes())
records=decoded_records(packet)
keys={"callback_errors","dropped","window_exceeded","open","late_unexpected","restore_errors"}
assert set(packet["integrity"])==keys
assert all(type(v) is int and v==0 for v in packet["integrity"].values())
assert packet["limits"]=={"records":800000,"bytes":134217728,"seconds":180}
assert 0<len(records)<=800000
print(json.dumps({"status":"PASS","records":len(records),"bytes":path.stat().st_size,"integrity":packet["integrity"],"censorship":packet["censorship"],"limits":packet["limits"],"paired_analysis_ran":False},sort_keys=True))
' "$output/run/observer-exposure.json" > "$evidence/exposure-integrity.stdout.txt" 2> "$evidence/exposure-integrity.stderr.txt"; exposure_code=$?
    [[ "$exposure_code" == 0 ]] || child_code=$exposure_code
    printf '{"load_returncode":%d,"metric_chain_returncode":%d,"original_R9_analysis_returncode":%d,"R11_raw_integrity_returncode":%d,"paired_R11_analysis_ran":false,"OFF_requires_separate_ACK":true}\n' "$load_code" "$metric_code" "$analysis_code" "$exposure_code" > "$evidence/returncodes.json" ;;
  off)
    exec_runner timeout --signal=TERM --kill-after=10 190 /app/.venv/bin/python -B /work/r/run_phase_baseline.py "$output/run" off > "$evidence/latency.stdout.txt" 2> "$evidence/latency.stderr.txt"
    child_code=$?
    printf '{"load_returncode":%d,"observer":"unchanged_off_no_R11_instrumentation"}\n' "$child_code" > "$evidence/returncodes.json" ;;
esac
set -e
exit "$child_code"
