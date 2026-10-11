"""Pinned finite raw EOF producer for local controls, never an effectful command."""

import sys
import time

mode = sys.argv[1]
if mode not in {"okay", "overflow", "nonzero", "delay"}:
    raise SystemExit(2)
if mode == "delay":
    time.sleep(1)
stdout = b"\x00\xffwhole-native-stdout\n" if mode != "overflow" else b"x" * 2049
stderr = b"\xffwhole-native-stderr\n"
sys.stdout.buffer.write(stdout)
sys.stdout.buffer.flush()
sys.stderr.buffer.write(stderr)
sys.stderr.buffer.flush()
raise SystemExit(3 if mode == "nonzero" else 0)
