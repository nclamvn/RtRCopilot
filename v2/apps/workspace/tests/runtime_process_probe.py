"""Subprocess entry for production Runtime recovery, without network or model APIs."""
import argparse
import asyncio
import os
from pathlib import Path

from agent_workspace.config import Settings
from agent_workspace.runtime import Runtime
from agent_workspace.store import Store, TERMINAL


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir")
    parser.add_argument("owner")
    parser.add_argument("run_id")
    parser.add_argument("--crash-after-effect", action="store_true")
    args = parser.parse_args()
    store = Store(Path(args.data_dir) / "catalogue.sqlite")
    if args.crash_after_effect:
        publish = store.publish

        def crash_after_receipt(*a, **kw):
            publish(*a, **kw)
            # Real SQLite transaction committed; native DBOS step has not returned.
            os._exit(41)

        store.publish = crash_after_receipt
    runtime = Runtime(Settings(Path(args.data_dir), test_mode=True), store)
    try:
        await runtime.start()
        for _ in range(300):
            if store.run(args.owner, args.run_id)["state"] in TERMINAL:
                return
            await asyncio.sleep(.05)
        raise RuntimeError("probe_deadline")
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
