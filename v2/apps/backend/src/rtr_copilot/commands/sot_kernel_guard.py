import argparse
import json
from pathlib import Path

from rtr_copilot.sot.kernel_guard import probe_kernel_read_only


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/Users/os/RtR/kernel"))
    parser.add_argument("--record-key", default="L3F.ENT.002")
    args = parser.parse_args()
    result = probe_kernel_read_only(args.root, args.record_key)
    summary = {
        key: value
        for key, value in result.items()
        if key not in {"before_fingerprint", "after_fingerprint"}
    }
    summary["file_count"] = len(result["before_fingerprint"])
    print(json.dumps(summary, sort_keys=True))
    return 0 if result["decision"] == "blocked" and result["read_only"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
