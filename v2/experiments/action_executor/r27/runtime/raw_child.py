"""Fixed bounded raw emitter, no inherited framed-record protocol or network."""

import os
import sys
import time

mode = sys.argv[1]
if mode not in ("ok", "delay", "excess"):
    raise SystemExit(2)
if mode == "delay":
    time.sleep(0.04)
os.write(1, b"actual raw stdout\x00\xff\nsecond line\n")
os.write(2, b"x" * 600 if mode == "excess" else b"actual raw stderr\xff\n")
