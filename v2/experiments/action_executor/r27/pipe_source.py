"""Fixed finite local fixture; no old helper, network, DB, or arbitrary command."""

import os
import struct
import sys
import time

mode = sys.argv[1]
if mode not in {"ok", "delay", "oversize", "partial"}:
    raise SystemExit(2)
if mode == "delay":
    time.sleep(0.04)
for fd, data in ((1, b"local stdout\x00\xff\n"), (1, b"stdout second\n"),
                 (2, b"stderr raw\xff\n" if mode != "oversize" else b"x" * 513)):
    os.write(fd, struct.pack(">I", len(data)) + data)
if mode == "partial":
    os.write(2, b"\x00\x00")
