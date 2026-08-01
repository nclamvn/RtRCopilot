#!/usr/bin/env bash
# TIP-012 Task 4 (D-012-06/07, AC-11) — migration gate.
#
# Asserts, statically and without a database, that:
#   1. the alembic migration graph has EXACTLY ONE head (no divergence);
#   2. that single head == the `expected_schema_revision` pin shipped in
#      config.py (so a checkout can never boot expecting a schema it does not
#      carry);
#   3. every revision resolves (no dangling down_revision).
#
# Used by ci-local.sh, verify.yml, deploy.sh and `make migration-gate`.
#
# Typed, fail-closed exit codes:
#   0  gate passes
#   2  not exactly one head (zero, or divergent multiple heads)
#   3  head does not equal the config pin
#   4  dangling / unresolved revision reference
#   5  gate could not read its inputs (missing dir/file, parse error)
#
# Overridable inputs (used by the proven-failing scratch test; default to the
# real repo layout):
#   MIGRATION_GATE_VERSIONS_DIR   default apps/backend/migrations/versions
#   MIGRATION_GATE_CONFIG_FILE    default apps/backend/src/rtr_copilot/config.py
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
versions_dir="${MIGRATION_GATE_VERSIONS_DIR:-$project_root/apps/backend/migrations/versions}"
config_file="${MIGRATION_GATE_CONFIG_FILE:-$project_root/apps/backend/src/rtr_copilot/config.py}"

if [[ ! -d "$versions_dir" ]]; then
  echo "migration_gate_error: versions dir not found: $versions_dir" >&2
  exit 5
fi
if [[ ! -f "$config_file" ]]; then
  echo "migration_gate_error: config file not found: $config_file" >&2
  exit 5
fi

python3 - "$versions_dir" "$config_file" <<'PY'
import ast
import pathlib
import sys

versions_dir = pathlib.Path(sys.argv[1])
config_file = pathlib.Path(sys.argv[2])


def module_str_assign(tree, name):
    """Return the string value of a module-level `name = "..."` assignment."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return None
    return None


def down_revisions(value):
    """Normalise a down_revision (None / str / tuple/list) to a list of str."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (tuple, list)):
        return [v for v in value if isinstance(v, str)]
    return []


revisions = {}          # revision id -> file
parents = {}            # revision id -> [down_revision ...]
for path in sorted(versions_dir.glob("*.py")):
    if path.name.startswith("__"):
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - defensive
        print(f"migration_gate_error: cannot parse {path.name}: {exc}", file=sys.stderr)
        sys.exit(5)
    rev = module_str_assign(tree, "revision")
    if not rev:
        # A versions/*.py without a revision id is not a migration script.
        continue
    if rev in revisions:
        print(
            f"migration_gate_error: duplicate revision {rev} in "
            f"{revisions[rev].name} and {path.name}",
            file=sys.stderr,
        )
        sys.exit(5)
    revisions[rev] = path
    # down_revision may be absent (rare); treat as a root.
    down = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "down_revision" for t in node.targets
        ):
            try:
                down = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                down = None
    parents[rev] = down_revisions(down)

if not revisions:
    print("migration_gate_error: no migration revisions found", file=sys.stderr)
    sys.exit(5)

# Dangling reference: a parent that names a revision we never defined.
all_parents = {p for plist in parents.values() for p in plist}
dangling = sorted(all_parents - set(revisions))
if dangling:
    print(
        "migration_divergence: dangling down_revision(s): " + ", ".join(dangling),
        file=sys.stderr,
    )
    sys.exit(4)

# Heads = revisions that are never named as a parent by another revision.
heads = sorted(set(revisions) - all_parents)

pin = module_str_assign(ast.parse(config_file.read_text(encoding="utf-8")), "expected_schema_revision")
# config.py declares the pin as a class attribute default, not a module assign;
# walk the whole tree for an AnnAssign / Assign named expected_schema_revision.
if pin is None:
    ctree = ast.parse(config_file.read_text(encoding="utf-8"))
    for node in ast.walk(ctree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "expected_schema_revision":
            try:
                pin = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pin = None
        elif isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "expected_schema_revision" for t in node.targets
        ):
            try:
                pin = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pin = None

if pin is None:
    print("migration_gate_error: expected_schema_revision pin not found in config", file=sys.stderr)
    sys.exit(5)

print(f"migration_gate: revisions={len(revisions)} heads={heads} pin={pin!r}")

if len(heads) != 1:
    print(
        f"migration_multiple_heads: expected exactly 1 head, found {len(heads)}: {heads}",
        file=sys.stderr,
    )
    sys.exit(2)

head = heads[0]
if head != pin:
    print(
        f"migration_pin_mismatch: head={head!r} != expected_schema_revision={pin!r}",
        file=sys.stderr,
    )
    sys.exit(3)

print(f"MIGRATION GATE PASS · single head {head!r} == pin · {len(revisions)} revisions, no divergence")
PY
