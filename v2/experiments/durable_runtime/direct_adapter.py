"""Matched direct source benchmark: identical transactions and fake provider."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from shared import execute


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--requests", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()
    cases = json.loads(Path(args.requests).read_text())
    def run(case):
        started = time.perf_counter()
        try:
            outcome = execute(case, args.state_dir)
            return {"id": case["id"], "result": outcome, "elapsed_ms": (time.perf_counter() - started) * 1000}
        except Exception as exc:
            return {"id": case["id"], "result": None, "error": repr(exc), "elapsed_ms": (time.perf_counter() - started) * 1000}
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        records = list(pool.map(run, cases))
    Path(args.output).write_text(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
