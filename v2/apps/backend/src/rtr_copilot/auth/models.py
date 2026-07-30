from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    STAFF = "staff"
    LEADER = "leader"
    CURATOR = "curator"
    ADMIN = "admin"


class SubjectStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class TemporaryEntitlement(BaseModel):
    action: str
    resource_id: str | None = None
    classification: str | None = None
    expires_at: datetime

    def active(self, now: datetime | None = None) -> bool:
        instant = now or datetime.now(UTC)
        return self.expires_at > instant


class Subject(BaseModel):
    user_id: str
    issuer: str
    sub: str
    email: str
    canonical_domain: str
    display_name: str = ""
    status: SubjectStatus = SubjectStatus.ACTIVE
    security_version: int = Field(default=1, ge=1)
    roles: set[Role] = Field(default_factory=lambda: {Role.STAFF})
    groups: set[str] = Field(default_factory=set)
    departments: set[str] = Field(default_factory=set)
    projects: set[str] = Field(default_factory=set)
    temporary_entitlements: list[TemporaryEntitlement] = Field(default_factory=list)


class ResourceAttributes(BaseModel):
    resource_id: str = "*"
    owner_id: str | None = None
    classification: str = "internal"
    department: str | None = None
    project: str | None = None
    source_zone: str = "sot"
    lifecycle_state: str = "published"
    proposed_by: str | None = None
    explicit_deny: bool = False


class PolicyContext(BaseModel):
    request_id: str
    separation_of_duties: bool = True
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PolicyDecision(BaseModel):
    allow: bool
    reason_code: str
    matched_policy_ids: list[str] = Field(default_factory=list)
