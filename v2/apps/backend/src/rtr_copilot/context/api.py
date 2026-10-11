"""Authenticated local context API; compute is read-only, memory is explicit."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from rtr_copilot.auth.models import Subject
from rtr_copilot.context.models import (
    ContextError,
    ContextPacket,
    MemoryCorrection,
    MemoryCreate,
    MemoryScope,
    MemoryTombstone,
    MemoryView,
    PacketRequest,
)
from rtr_copilot.context.service import ContextService
from rtr_copilot.db.uow import MaintenanceActive
from rtr_copilot.ingestion.api import file_subject
from rtr_copilot.rag.use_class import UseClass

router = APIRouter(prefix="/api/v1/context", tags=["context"])


def context_service() -> ContextService:
    return ContextService()


def error(request: Request, code: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": "Context operation is unavailable"},
            "request_id": str(request.state.request_id),
        },
    )


async def call(request: Request, actor: Subject | None, operation: Any) -> Any:
    if actor is None:
        # Close the coroutine without starting a service read or mutation.
        operation.close()
        return error(request, "authentication_required", 401)
    try:
        return await operation
    except ContextError as failure:
        return error(request, failure.code, failure.status)
    except MaintenanceActive:
        return error(request, "maintenance_active", 503)


Actor = Annotated[Subject | None, Depends(file_subject)]
Service = Annotated[ContextService, Depends(context_service)]


@router.post("/resolve", response_model=ContextPacket)
async def resolve(request: Request, payload: PacketRequest, actor: Actor, service: Service) -> Any:
    return (
        await call(
            request,
            actor,
            service.resolve(
                actor,
                payload,
                request_id=str(request.state.request_id),
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )


@router.post("/packets", response_model=ContextPacket)
async def create_packet(
    request: Request, payload: PacketRequest, actor: Actor, service: Service
) -> Any:
    return (
        await call(
            request,
            actor,
            service.resolve(
                actor,
                payload,
                request_id=str(request.state.request_id),
                persist=True,
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )


@router.get("/packets/{packet_id}", response_model=ContextPacket)
async def read_packet(request: Request, packet_id: UUID, actor: Actor, service: Service) -> Any:
    return (
        await call(
            request,
            actor,
            service.read_packet(
                actor,
                packet_id,
                request_id=str(request.state.request_id),
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )


@router.post("/memory", response_model=MemoryView)
async def create_memory(
    request: Request, payload: MemoryCreate, actor: Actor, service: Service
) -> Any:
    return (
        await call(
            request,
            actor,
            service.create_memory(
                actor,
                payload,
                request_id=str(request.state.request_id),
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )


@router.get("/memory", response_model=tuple[MemoryView, ...])
async def list_memory(
    request: Request,
    actor: Actor,
    service: Service,
    scope_kind: Literal["private", "project", "department"] = "private",
    scope_key: UUID | None = None,
    use_class: UseClass = "proposal",
    limit: Annotated[int, Query(ge=1, le=20)] = 20,
) -> Any:
    if actor is None:
        return error(request, "authentication_required", 401)
    if (scope_kind == "private") != (scope_key is None):
        return error(request, "context_scope_invalid", 422)
    return await call(
        request,
        actor,
        service.list_memory(
            actor,
            MemoryScope(kind=scope_kind, key=scope_key),
            use_class=use_class,
            limit=limit,
            request_id=str(request.state.request_id),
        ),
    )


@router.get("/memory/{memory_id}", response_model=MemoryView)
async def read_memory(request: Request, memory_id: UUID, actor: Actor, service: Service) -> Any:
    return (
        await call(
            request,
            actor,
            service.read_memory(
                actor,
                memory_id,
                request_id=str(request.state.request_id),
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )


@router.patch("/memory/{memory_id}", response_model=MemoryView)
async def correct_memory(
    request: Request,
    memory_id: UUID,
    payload: MemoryCorrection,
    actor: Actor,
    service: Service,
) -> Any:
    return (
        await call(
            request,
            actor,
            service.correct_memory(
                actor,
                memory_id,
                payload,
                request_id=str(request.state.request_id),
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )


@router.delete("/memory/{memory_id}", response_model=MemoryTombstone)
async def delete_memory(
    request: Request,
    memory_id: UUID,
    actor: Actor,
    service: Service,
    expected_revision: Annotated[int, Query(ge=1)],
) -> Any:
    return (
        await call(
            request,
            actor,
            service.delete_memory(
                actor,
                memory_id,
                expected_revision,
                request_id=str(request.state.request_id),
            ),
        )
        if actor
        else error(request, "authentication_required", 401)
    )
