import json
from typing import Any

import pytest

from rtr_copilot.worker.main import execute, ping_result


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.writes = 0

    async def exists(self, key: str) -> bool:
        return key in self.values

    async def set(self, key: str, value: str, **_: Any) -> bool:
        if key not in self.values:
            self.values[key] = value
            self.writes += 1
        return True


def test_ping_result_is_deterministic() -> None:
    assert ping_result("job-1", "req-1") == {
        "job_id": "job-1", "request_id": "req-1", "status": "pong"}


@pytest.mark.asyncio
async def test_retry_has_no_side_effect() -> None:
    redis = FakeRedis()
    job = {"name": "system.ping", "job_id": "job-1", "request_id": "req-1"}
    await execute(redis, job)  # type: ignore[arg-type]
    await execute(redis, job)  # type: ignore[arg-type]
    assert redis.writes == 1
    assert json.loads(redis.values["rtr:result:job-1"])["status"] == "pong"
