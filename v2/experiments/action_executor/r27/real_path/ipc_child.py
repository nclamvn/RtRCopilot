"""Exact finite cooperative IPC control child; no artifact directory or descriptor."""

from __future__ import annotations

import json
import os
import sys

from transport import IPCClient


def main() -> None:
    address, mode = sys.argv[1:]
    if mode not in {"ok", "lost_ack", "bad_encode"}:
        raise ValueError("fixed child mode")
    try:
        with IPCClient(address, os.environ["R27_IPC_TOKEN"]) as port:
            port.path("child").mkdir()
            path = port.path("child/raw")
            if mode == "bad_encode":
                fault = TypeError("original pre-I/O producer fault")
                port.capture_fault(fault)
                try:
                    path.write_bytes(b"must not write")
                except BaseException as caught:
                    assert caught is fault
                    raise
            assert path.write_bytes(b"\x00\xff\n") == 3
            assert path.read_bytes() == b"\x00\xff\n"
            copy = port.path("child/copy")
            assert copy.write_bytes(path.read_bytes()) == 3
            with port.path("child/text").open("w") as output:
                assert output.write("Đ") == 1
                output.flush()
            assert port.path("child/text").stat().st_size == 2
            print(
                json.dumps(
                    {
                        "status": "OK",
                        "raw": path.read_bytes().hex(),
                        "logical_only": not hasattr(path, "_root"),
                    }
                )
            )
    except BaseException:
        if mode == "ok":
            raise
        print(json.dumps({"status": "STOP", "mode": mode}))


if __name__ == "__main__":
    main()
