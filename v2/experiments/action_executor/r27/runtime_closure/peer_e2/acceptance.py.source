"""One real shared-broker seed/parser, installed plugin, fileConfig and host-df flow."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from composition import DriverPort, RefreshingParser, SeedBridge
from controller import DSN
from host import OwnedBroker
from logging_seam import migration_logging_scope
from native_seam import Result, run
from ports import PathPort, RichPath
from pytest_seam import pytest_scope

HERE = Path(__file__).absolute().parent
ROOT = HERE.parents[4]


def execute_local(broker: OwnedBroker, port: PathPort, scratch: Path) -> Result:
    """Genuine pure local algorithms only; no service stage/publish or SQL/HTTP effects."""
    try:
        driver = DriverPort(port)
        seed = SeedBridge(driver, DSN)
        root = driver.path("tmp/seed")
        root.mkdir(parents=True)
        build = cast(Callable[[Path], Path], seed.fixture_build)
        package = cast(RichPath, build(cast(Path, root)))
        parsed = RefreshingParser(root).parse(package.name)
        if len(parsed.records) != 1:
            raise ValueError("unchanged signed fixture/parser local record")
        with pytest_scope(port, "plugins/report.xml") as report:
            code = pytest.main(
                [
                    "-c",
                    str(ROOT / "v2/apps/backend/pyproject.toml"),
                    "--confcutdir=" + str(HERE),
                    "-p",
                    "no:cacheprovider",
                    "-q",
                    "--basetemp=" + str(scratch / "inner-pytest"),
                    "--junitxml=" + report,
                    str(HERE / "plugin_target.py"),
                ]
            )
        if int(code) != 0:
            raise RuntimeError("actual local plugin target failed")
        with migration_logging_scope(port):
            logging.getLogger("alembic.runtime.migration").info(
                "R27 actual local fileConfig record"
            )
        return asyncio.run(run(broker, port, kind="host_df"))
    except BaseException as error:
        port.capture_fault(error)
        raise
