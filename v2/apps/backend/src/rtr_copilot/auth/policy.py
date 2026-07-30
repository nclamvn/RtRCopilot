from rtr_copilot.auth.audit import AuditSink, event
from rtr_copilot.auth.models import (
    PolicyContext,
    PolicyDecision,
    ResourceAttributes,
    Role,
    Subject,
    SubjectStatus,
)

ACTIONS = {
    "ask",
    "search",
    "view",
    "upload",
    "download",
    "render",
    "approve",
    "curate",
    "manage_users",
    "manage_policies",
}
CONTENT_ACTIONS = {"ask", "search", "view", "download", "render"}
CLASSIFICATION_LEVEL = {"public": 0, "internal": 1, "restricted": 2, "classified": 3}
ROLE_CLEARANCE = {
    Role.STAFF: 1,
    Role.LEADER: 2,
    Role.CURATOR: 2,
    Role.ADMIN: 1,
}


class PolicyEngine:
    def __init__(self, audit: AuditSink) -> None:
        self.audit = audit

    def decide(
        self,
        subject: Subject,
        action: str,
        resource: ResourceAttributes,
        context: PolicyContext,
    ) -> PolicyDecision:
        decision = self._decide(subject, action, resource, context)
        privileged_content = (
            action in {"view", "download", "render"}
            and resource.classification in {"restricted", "classified"}
        )
        if privileged_content or action in {
            "approve",
            "curate",
            "manage_users",
            "manage_policies",
        }:
            self.audit.emit(event(
                actor_id=subject.user_id,
                action=f"policy.{action}",
                result="allow" if decision.allow else "deny",
                reason=decision.reason_code,
                request_id=context.request_id,
                policy_ids=decision.matched_policy_ids,
            ))
        return decision

    def _decide(
        self,
        subject: Subject,
        action: str,
        resource: ResourceAttributes,
        context: PolicyContext,
    ) -> PolicyDecision:
        if action not in ACTIONS:
            return PolicyDecision(allow=False, reason_code="unknown_action")
        if resource.classification not in CLASSIFICATION_LEVEL:
            return PolicyDecision(allow=False, reason_code="unknown_resource")
        if subject.status != SubjectStatus.ACTIVE:
            return PolicyDecision(allow=False, reason_code="subject_disabled")
        if resource.explicit_deny:
            return PolicyDecision(
                allow=False,
                reason_code="explicit_deny",
                matched_policy_ids=["deny.explicit"],
            )
        if action in {"manage_users", "manage_policies"}:
            allowed = Role.ADMIN in subject.roles
            return PolicyDecision(
                allow=allowed,
                reason_code="admin_management" if allowed else "role_required",
                matched_policy_ids=["rbac.admin"] if allowed else [],
            )
        if (
            action == "approve"
            and context.separation_of_duties
            and resource.proposed_by == subject.user_id
        ):
            return PolicyDecision(
                allow=False,
                reason_code="separation_of_duties",
                matched_policy_ids=["deny.sod"],
            )

        entitlement = next((
            item for item in subject.temporary_entitlements
            if item.active(context.now)
            and item.action == action
            and (item.resource_id is None or item.resource_id == resource.resource_id)
            and (
                item.classification is None
                or item.classification == resource.classification
            )
        ), None)
        if entitlement is not None:
            return PolicyDecision(
                allow=True,
                reason_code="temporary_entitlement",
                matched_policy_ids=["abac.temporary"],
            )

        clearance = max((ROLE_CLEARANCE[role] for role in subject.roles), default=0)
        required = CLASSIFICATION_LEVEL[resource.classification]
        if action in CONTENT_ACTIONS and required > clearance:
            return PolicyDecision(
                allow=False,
                reason_code="classification_denied",
                matched_policy_ids=["deny.classification"],
            )
        if resource.department and resource.department not in subject.departments:
            return PolicyDecision(
                allow=False,
                reason_code="department_denied",
                matched_policy_ids=["deny.department"],
            )
        if resource.project and resource.project not in subject.projects:
            return PolicyDecision(
                allow=False,
                reason_code="project_denied",
                matched_policy_ids=["deny.project"],
            )
        if action == "curate":
            allowed = Role.CURATOR in subject.roles
            return PolicyDecision(
                allow=allowed,
                reason_code="curator_role" if allowed else "role_required",
                matched_policy_ids=["rbac.curator"] if allowed else [],
            )
        if action == "approve":
            allowed = Role.LEADER in subject.roles
            return PolicyDecision(
                allow=allowed,
                reason_code="leader_role" if allowed else "role_required",
                matched_policy_ids=["rbac.leader"] if allowed else [],
            )
        if action == "upload":
            return PolicyDecision(
                allow=True,
                reason_code="authenticated_upload",
                matched_policy_ids=["rbac.authenticated"],
            )
        if action in CONTENT_ACTIONS:
            return PolicyDecision(
                allow=True,
                reason_code="content_scope",
                matched_policy_ids=["abac.content"],
            )
        return PolicyDecision(allow=False, reason_code="default_deny")
