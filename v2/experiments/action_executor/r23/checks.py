"""Read-only preservation bridge; no import of prior analyzer/product/helpers."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or name != path.as_posix():
        raise ValueError("noncanonical input")
    if any((ROOT / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)):
        raise ValueError("input symlink")
    return (ROOT / path).read_bytes()


def verify():
    current = json.loads((HERE / "input-binding.json").read_bytes())
    pins = dict(current["direct"])
    for path, expected in current["anchors"].items():
        data = read(path)
        if sha(data) != expected:
            raise ValueError("anchor drift: " + path)
        pins[path] = expected
    prior = json.loads(read("v2/experiments/action_executor/r22/input-binding.json"))
    pins.update(prior["direct"])
    links = dict(prior["links"])
    links["v2/experiments/action_executor/r22/main-evidence-binding.sha256"] = current["anchors"][
        "v2/experiments/action_executor/r22/main-evidence-binding.sha256"]
    for path, expected in links.items():
        data = read(path)
        if sha(data) != expected:
            raise ValueError("linked seal drift: " + path)
        pins[path] = expected
        items = json.loads(data)["files"] if path.endswith(".json") else {
            line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in data.decode().splitlines()}
        for name, digest in items.items():
            if name in pins and pins[name] != digest:
                raise ValueError("conflicting pin")
            pins[name] = digest
    total = 0
    for path, expected in pins.items():
        total += (ROOT / path).stat().st_size
        if total > 33554432 or sha(read(path)) != expected:
            raise ValueError("cap/input drift: " + path)
    source = json.loads(read("v2/experiments/action_executor/r18/source-binding-e3.json"))
    ignored = {"__pycache__", ".pytest_cache", ".ruff_cache"}
    for scope, paths in source["scopes"].items():
        dirs = ("src", "migrations") if scope == "product" else ("tests",)
        actual = []
        for directory in dirs:
            for path in (ROOT / "v2/apps/backend" / directory).rglob("*"):
                rel = path.relative_to(ROOT)
                if ignored.intersection(rel.parts) or path.suffix == ".pyc":
                    continue
                if path.is_symlink():
                    raise ValueError("source symlink")
                if path.is_file():
                    actual.append(rel.as_posix())
        actual += [p for p in paths if not any("/" + d + "/" in p for d in dirs)]
        if sorted(actual) != paths or sha("".join(pins[p] + "  " + p + "\n" for p in paths).encode()) != source["digests"][scope]:
            raise ValueError("source inventory/digest drift")
    return {"unique_pins": len(pins), "bytes": total, "digests": source["digests"],
            "r22_seal_entries": 20, "scope": "source/evidence only; no runtime proof"}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
