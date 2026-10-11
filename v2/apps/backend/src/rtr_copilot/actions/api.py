import uuid
from collections.abc import Coroutine
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from rtr_copilot.actions.models import (
    ActionEvent,
    ApprovalRequest,
    ApprovalView,
    CapabilityView,
    ContractReceipt,
    PlanRequest,
    PlanView,
    VersionRequest,
)
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.service import ActionService, correlation
from rtr_copilot.auth.models import Subject
from rtr_copilot.db.uow import MaintenanceActive
from rtr_copilot.ingestion.api import file_subject

router = APIRouter(prefix="/api/v1/actions", tags=["action contracts"])


def action_service() -> ActionService:
    return ActionService()


async def perform(
    request: Request, subject: Subject | None, operation: Coroutine[Any, Any, Any]
) -> Any:
    try:
        if subject is None:
            operation.close()
            raise ActionError("authentication_required", 401)
        return await operation
    except ActionError as error:
        return JSONResponse(
            status_code=error.status,
            content={
                "error": {"code": error.code, "message": "Action contract unavailable or invalid"},
                "request_id": str(request.state.request_id),
                "action_correlation_digest": correlation(str(request.state.request_id)),
                "execution_available": False,
            },
        )
    except MaintenanceActive:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "maintenance_active",
                    "message": "Mutations temporarily unavailable",
                },
                "request_id": str(request.state.request_id),
                "action_correlation_digest": correlation(str(request.state.request_id)),
                "execution_available": False,
            },
        )


Caller = Annotated[Subject | None, Depends(file_subject)]
Service = Annotated[ActionService, Depends(action_service)]


@router.get("/capabilities", response_model=tuple[CapabilityView, ...])
async def capabilities(request: Request, subject: Caller, service: Service) -> Any:
    return await perform(request, subject, service.capabilities(cast(Subject, subject)))


@router.post("/capabilities/{capability_id}/admit", response_model=CapabilityView)
async def admit(
    capability_id: str, body: VersionRequest, request: Request, subject: Caller, service: Service
) -> Any:
    return await perform(
        request,
        subject,
        service.admit_capability(
            cast(Subject, subject),
            capability_id,
            body.version,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/capabilities/{capability_id}/revoke")
async def revoke(
    capability_id: str, body: VersionRequest, request: Request, subject: Caller, service: Service
) -> Any:
    async def operation() -> dict[str, bool]:
        assert subject is not None
        await service.revoke_capability(
            subject, capability_id, body.version, request_id=str(request.state.request_id)
        )
        return {"execution_available": False}

    return await perform(request, subject, operation())


@router.post("/plans", status_code=201, response_model=PlanView)
async def create(body: PlanRequest, request: Request, subject: Caller, service: Service) -> Any:
    return await perform(
        request,
        subject,
        service.create_plan(
            cast(Subject, subject),
            body,
            request_id=str(request.state.request_id),
        ),
    )


@router.get("/plans/{plan_id}", response_model=PlanView)
async def read(plan_id: uuid.UUID, request: Request, subject: Caller, service: Service) -> Any:
    return await perform(
        request,
        subject,
        service.read_plan(
            cast(Subject, subject),
            plan_id,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/plans/{plan_id}/validate-ready", response_model=PlanView)
async def ready(plan_id: uuid.UUID, request: Request, subject: Caller, service: Service) -> Any:
    return await perform(
        request,
        subject,
        service.validate_ready(
            cast(Subject, subject),
            plan_id,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/plans/{plan_id}/approvals", response_model=ApprovalView)
async def approve(
    plan_id: uuid.UUID, body: ApprovalRequest, request: Request, subject: Caller, service: Service
) -> Any:
    return await perform(
        request,
        subject,
        service.approve(
            cast(Subject, subject),
            plan_id,
            body,
            request_id=str(request.state.request_id),
        ),
    )


@router.get("/plans/{plan_id}/approvals", response_model=tuple[ApprovalView, ...])
async def approvals(plan_id: uuid.UUID, request: Request, subject: Caller, service: Service) -> Any:
    return await perform(
        request,
        subject,
        service.approvals(
            cast(Subject, subject),
            plan_id,
            request_id=str(request.state.request_id),
        ),
    )


@router.post("/approvals/{approval_id}/revoke")
async def revoke_approval(
    approval_id: uuid.UUID, request: Request, subject: Caller, service: Service
) -> Any:
    async def operation() -> dict[str, bool]:
        assert subject is not None
        await service.revoke_approval(
            subject, approval_id, request_id=str(request.state.request_id)
        )
        return {"execution_available": False}

    return await perform(request, subject, operation())


@router.get("/plans/{plan_id}/events", response_model=tuple[ActionEvent, ...])
async def events(plan_id: uuid.UUID, request: Request, subject: Caller, service: Service) -> Any:
    return await perform(
        request,
        subject,
        service.events(
            cast(Subject, subject),
            plan_id,
            request_id=str(request.state.request_id),
        ),
    )


@router.get("/plans/{plan_id}/receipts", response_model=tuple[ContractReceipt, ...])
async def receipts(plan_id: uuid.UUID, request: Request, subject: Caller, service: Service) -> Any:
    return await perform(
        request,
        subject,
        service.receipts(
            cast(Subject, subject),
            plan_id,
            request_id=str(request.state.request_id),
        ),
    )
