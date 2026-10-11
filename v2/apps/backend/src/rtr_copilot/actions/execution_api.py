"""Bounded domain acknowledgements; never a native workflow result waiter."""

import asyncio
import uuid
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from rtr_copilot.actions.api import Caller, perform
from rtr_copilot.actions.execution import ExecutionService
from rtr_copilot.actions.execution_models import ExecutionView, SubmitExecution
from rtr_copilot.auth.models import Subject

router = APIRouter(prefix="/api/v1/actions", tags=["action execution"])


def execution_service() -> ExecutionService:
    return ExecutionService()


Service = Annotated[ExecutionService, Depends(execution_service)]


async def bounded(request: Request, subject: Subject | None, service: ExecutionService,
                  operation: Any) -> Any:
    try:
        async with asyncio.timeout(service.settings.action_executor_operation_timeout_seconds):
            return await perform(request, subject, operation)
    except TimeoutError:
        return JSONResponse(status_code=503, content={"error": {"code": "action_operation_timeout",
                            "message": "Check durable action status before resubmitting"}})


@router.post("/plans/{plan_id}/execute", status_code=202, response_model=ExecutionView)
async def submit(plan_id: uuid.UUID, body: SubmitExecution, request: Request, subject: Caller,
                 service: Service) -> Any:
    return await bounded(request, subject, service, service.submit(
        cast(Subject, subject), plan_id, body.expected_plan_digest,
        request_id=str(request.state.request_id)))


@router.get("/runs/{run_id}", response_model=ExecutionView)
async def status(run_id: uuid.UUID, request: Request, subject: Caller,
                 service: Service) -> Any:
    return await bounded(request, subject, service, service.status(cast(Subject, subject), run_id))


@router.post("/runs/{run_id}/cancel", status_code=202, response_model=ExecutionView)
async def cancel(run_id: uuid.UUID, request: Request, subject: Caller,
                 service: Service) -> Any:
    return await bounded(request, subject, service, service.cancel(cast(Subject, subject), run_id))


@router.post("/runs/{run_id}/resume", status_code=202, response_model=ExecutionView)
async def resume(run_id: uuid.UUID, request: Request, subject: Caller,
                 service: Service) -> Any:
    return await bounded(request, subject, service, service.resume(
        cast(Subject, subject), run_id, request_id=str(request.state.request_id)))


@router.get("/runs/{run_id}/steps/{step_key}/output")
async def output(run_id: uuid.UUID, step_key: str, request: Request, subject: Caller,
                 service: Service) -> Any:
    return await bounded(request, subject, service, service.read_output(
        cast(Subject, subject), run_id, step_key, request_id=str(request.state.request_id)))
