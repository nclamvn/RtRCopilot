import json
import secrets
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from redis.asyncio import Redis

from rtr_copilot.auth.audit import event
from rtr_copilot.auth.models import PolicyContext, ResourceAttributes, Subject
from rtr_copilot.auth.oidc import (
    OIDCError,
    ProductionOIDCProvider,
    decode_dev_code,
    encode_dev_code,
    pkce_challenge,
    token_url,
    validate_claims,
)
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.auth.storage import SessionStore, TransactionStore
from rtr_copilot.config import Settings, get_settings
from rtr_copilot.repositories.audit import DatabaseAuditSink
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository

router = APIRouter(prefix="/auth", tags=["auth"])
dev_router = APIRouter(prefix="/auth/dev", tags=["auth-development"])
audit = DatabaseAuditSink()


class MeResponse(BaseModel):
    user_id: str
    email: str
    display_name: str
    roles: list[str]
    groups: list[str]
    departments: list[str]
    projects: list[str]


class LogoutResponse(BaseModel):
    ok: bool = True


class ProtectedResponse(BaseModel):
    allow: bool
    reason_code: str
    matched_policy_ids: list[str]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


def request_id(request: Request) -> str:
    return str(request.state.request_id)


def auth_error(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message},
            "request_id": request_id(request),
        },
    )


def clients(settings: Settings) -> tuple[Any, SessionStore, TransactionStore]:
    client = Redis.from_url(settings.redis_url, decode_responses=True)
    return (
        client,
        SessionStore(client, settings.session_ttl_seconds),
        TransactionStore(client),
    )


def group_mapping(settings: Settings) -> dict[str, Any]:
    try:
        value = json.loads(settings.oidc_group_mapping)
        return dict(value) if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def identity_repository(identity_request_id: str) -> Any:
    return PostgresSubjectRepository(request_id=identity_request_id)


async def current_subject(
    request: Request,
    session_id: str | None,
) -> Subject | None:
    settings = get_settings()
    client, sessions, _ = clients(settings)
    try:
        return await sessions.get(session_id)
    finally:
        await client.aclose()


@router.get("/login", response_model=None)
async def login(request: Request) -> RedirectResponse | JSONResponse:
    settings = get_settings()
    client, _, transactions = clients(settings)
    state = token_url()
    nonce = token_url()
    verifier = token_url(48)
    try:
        await transactions.put("state", state, {"nonce": nonce, "verifier": verifier})
        if settings.app_env in {"development", "test"} and settings.dev_oidc_enabled:
            query = urlencode({
                "state": state,
                "nonce": nonce,
                "code_challenge": pkce_challenge(verifier),
            })
            return RedirectResponse(f"/api/auth/dev/authorize?{query}", status_code=302)
        provider = ProductionOIDCProvider(settings)
        return RedirectResponse(
            await provider.authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=pkce_challenge(verifier),
            ),
            status_code=302,
        )
    except OIDCError as error:
        audit.emit(event(
            actor_id=None,
            action="auth.login",
            result="deny",
            reason=str(error),
            request_id=request_id(request),
        ))
        return auth_error(request, 503, "oidc_unavailable", "Identity provider unavailable")
    finally:
        await client.aclose()


@router.get("/callback", response_model=None)
async def callback(
    request: Request,
    state: str,
    code: str,
) -> RedirectResponse | JSONResponse:
    settings = get_settings()
    client, sessions, transactions = clients(settings)
    try:
        transaction = await transactions.consume("state", state)
        if transaction is None:
            raise OIDCError("state_invalid_or_replayed")
        if settings.app_env in {"development", "test"} and settings.dev_oidc_enabled:
            payload = decode_dev_code(code)
            if not secrets.compare_digest(
                str(payload.get("code_challenge", "")),
                pkce_challenge(str(transaction["verifier"])),
            ):
                raise OIDCError("pkce_failed")
            claims = validate_claims(
                dict(payload["claims"]),
                str(transaction["nonce"]),
                settings.allowed_domains,
            )
        else:
            claims = await ProductionOIDCProvider(settings).exchange(
                code=code,
                code_verifier=str(transaction["verifier"]),
                expected_nonce=str(transaction["nonce"]),
            )
        subject = await identity_repository(request_id(request)).upsert_from_claims(
            claims,
            group_mapping(settings),
        )
        await sessions.sync_authority(subject)
        if subject.status.value != "active":
            raise OIDCError("subject_disabled")
        old_session = request.cookies.get(settings.session_cookie_name)
        session_id = await sessions.rotate(old_session, subject)
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            settings.session_cookie_name,
            session_id,
            max_age=settings.session_ttl_seconds,
            httponly=True,
            secure=settings.session_cookie_secure_effective,
            samesite="lax",
            path="/",
        )
        audit.emit(event(
            actor_id=subject.user_id,
            action="auth.login",
            result="allow",
            reason="oidc_success",
            request_id=request_id(request),
        ))
        return response
    except (OIDCError, KeyError):
        audit.emit(event(
            actor_id=None,
            action="auth.login",
            result="deny",
            reason="oidc_rejected",
            request_id=request_id(request),
        ))
        return auth_error(request, 401, "oidc_rejected", "Corporate login was rejected")
    finally:
        await client.aclose()


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request) -> JSONResponse:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)
    client, sessions, _ = clients(settings)
    try:
        subject = await sessions.get(session_id)
        await sessions.revoke(session_id)
        audit.emit(event(
            actor_id=subject.user_id if subject else None,
            action="auth.session_revoke",
            result="allow",
            reason="logout",
            request_id=request_id(request),
        ))
        audit.emit(event(
            actor_id=subject.user_id if subject else None,
            action="auth.logout",
            result="allow",
            reason="session_revoked",
            request_id=request_id(request),
        ))
        response = JSONResponse({"ok": True})
        response.delete_cookie(settings.session_cookie_name, path="/")
        return response
    finally:
        await client.aclose()


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"model": ErrorResponse}},
)
async def me(
    request: Request,
) -> MeResponse | JSONResponse:
    settings = get_settings()
    subject = await current_subject(
        request,
        request.cookies.get(settings.session_cookie_name),
    )
    if subject is None:
        return auth_error(request, 401, "authentication_required", "Sign in required")
    return MeResponse(
        user_id=subject.user_id,
        email=subject.email,
        display_name=subject.display_name,
        roles=sorted(role.value for role in subject.roles),
        groups=sorted(subject.groups),
        departments=sorted(subject.departments),
        projects=sorted(subject.projects),
    )


@dev_router.get("/authorize")
async def dev_authorize(
    state: str,
    nonce: str,
    code_challenge: str,
    email: str = "staff@rtrobotics.com",
    sub: str = "dev-staff",
    name: str = "Development Staff",
    verified: bool = True,
    groups: Annotated[list[str] | None, Query()] = None,
) -> RedirectResponse:
    settings = get_settings()
    claims = {
        "iss": "https://dev-oidc.invalid",
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "name": name,
        "groups": groups or [],
        "nonce": nonce,
    }
    code = encode_dev_code({"claims": claims, "code_challenge": code_challenge})
    callback_url = str(settings.public_base_url).rstrip("/") + "/api/auth/callback"
    return RedirectResponse(
        f"{callback_url}?{urlencode({'state': state, 'code': code})}",
        status_code=302,
    )


@dev_router.get(
    "/protected",
    response_model=ProtectedResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def protected(
    request: Request,
    action: str = "view",
    classification: str = "classified",
) -> ProtectedResponse | JSONResponse:
    settings = get_settings()
    subject = await current_subject(
        request,
        request.cookies.get(settings.session_cookie_name),
    )
    if subject is None:
        return auth_error(request, 401, "authentication_required", "Sign in required")
    decision = PolicyEngine(audit).decide(
        subject,
        action,
        ResourceAttributes(classification=classification),
        PolicyContext(request_id=request_id(request)),
    )
    if not decision.allow:
        return auth_error(request, 403, decision.reason_code, "Access denied")
    return ProtectedResponse(**decision.model_dump())
