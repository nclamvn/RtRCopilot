import json
import uuid
from typing import Any

import pytest
from starlette.requests import Request

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.rag.api import _ask_stream
from rtr_copilot.rag.models import (
    AskProgressEvent,
    AskRequest,
    AskResponse,
)


class StreamingAnswerStub:
    async def ask(self, subject: Subject, question: str, **kwargs: Any) -> AskResponse:
        del subject, question
        progress = kwargs["progress"]
        await progress(AskProgressEvent(
            stage="understanding",
            status="started",
            elapsed_ms=2,
        ))
        await progress(AskProgressEvent(
            stage="retrieving",
            status="completed",
            elapsed_ms=8,
            source_count=1,
            sources=[{
                "marker": "C1",
                "record_key": "rtr.product.hera",
                "source_label": "HERA specification",
                "verification_state": "approved",
                "freshness_state": "current",
            }],
        ))
        return AskResponse(
            state="honest_null",
            answer="No answer in this transport stub.",
            citations=[],
            conversation_id=uuid.uuid4(),
            answer_run_id=uuid.uuid4(),
            reason_code="manual_entry",
            request_id=str(kwargs["request_id"]),
        )


@pytest.mark.asyncio
async def test_ask_stream_emits_only_bounded_progress_then_existing_result() -> None:
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/ask",
        "headers": [],
    })
    subject = Subject(
        user_id=str(uuid.uuid4()),
        issuer="https://accounts.google.com",
        sub="stream-test-subject",
        email="staff@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        display_name="Staff",
        roles={Role.STAFF},
    )
    frames = [frame async for frame in _ask_stream(
        AskRequest(question="HERA là gì?"),
        request,
        subject,
        StreamingAnswerStub(),  # type: ignore[arg-type]
        "stream-test",
    )]

    assert [frame.splitlines()[0] for frame in frames] == [
        "event: progress",
        "event: progress",
        "event: result",
    ]
    source_frame = json.loads(frames[1].split("data: ", 1)[1])
    first_frame = json.loads(frames[0].split("data: ", 1)[1])
    assert first_frame["sequence"] == 1
    assert source_frame["sequence"] == 2
    assert source_frame["stage_elapsed_ms"] == 0
    assert source_frame["milestone"] == "sources_ready"
    assert set(source_frame["sources"][0]) == {
        "marker",
        "record_key",
        "source_label",
        "verification_state",
        "freshness_state",
    }
    result = json.loads(frames[-1].split("data: ", 1)[1])
    assert result["response"]["state"] == "honest_null"
