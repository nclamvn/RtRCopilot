import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.governance.admin import AdminGovernanceService
from rtr_copilot.governance.admin_api import TRUTH_FAMILIES
from rtr_copilot.governance.admin_api import router as admin_router
from rtr_copilot.governance.api import STATUS_BY_CODE, governance_subject
from rtr_copilot.governance.dashboard import (
    AGE_BUCKETS,
    CoverageTile,
    FreshnessTile,
    GapFlowTile,
    GraduationFunnelTile,
    ResearchIntakeTile,
    aging_bucket,
)

EXPECTED_ADMIN_SURFACE = {
    ("/api/v1/admin/research-sources", "GET"),
    ("/api/v1/admin/research-sources", "POST"),
    ("/api/v1/admin/research-sources/{source_id}", "GET"),
    ("/api/v1/admin/research-sources/{source_id}", "PATCH"),
    ("/api/v1/admin/settings", "GET"),
    ("/api/v1/admin/settings/{setting_key}", "PUT"),
    ("/api/v1/admin/settings/{setting_key}/versions", "GET"),
    ("/api/v1/admin/gaps/{gap_id}/priority", "POST"),
    ("/api/v1/admin/subjects", "GET"),
    ("/api/v1/admin/subjects/{subject_id}/bindings", "POST"),
    ("/api/v1/admin/jobs/health", "GET"),
    ("/api/v1/admin/pilot-readiness", "GET"),
}
BOUNDARY_PREFIXES = tuple(f"/api/v1/admin/{family}/" for family in TRUTH_FAMILIES)


def subject(role: Role, user_id: uuid.UUID | None = None) -> Subject:
    return Subject(
        user_id=str(user_id or uuid.uuid4()),
        issuer="test",
        sub=uuid.uuid4().hex,
        email="person@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


def override_subject(identity: Subject | None) -> None:
    async def resolve() -> Subject | None:
        return identity

    app.dependency_overrides[governance_subject] = resolve


def clear_override() -> None:
    app.dependency_overrides.pop(governance_subject, None)


def test_admin_surface_inventory_contains_no_truth_mutation_routes() -> None:
    """AC-11 by construction: the admin surface is closed and enumerable.

    Every admin route is either one of the expected governance operations or
    an explicit truth-family boundary guard; no route family can reach SOT
    record content, research record content, audit events or issuances.
    """
    openapi = app.openapi()
    admin_routes = {
        (path, method.upper())
        for path, operations in openapi["paths"].items()
        if path.startswith("/api/v1/admin")
        for method in operations
    }
    assert admin_routes == EXPECTED_ADMIN_SURFACE
    router_routes: set[tuple[str, str]] = set()
    boundary_routes: set[str] = set()
    for route in admin_router.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        assert path is not None and methods is not None
        if path.endswith("{rest:path}"):
            boundary_routes.add(path)
            continue
        router_routes.update(
            (path, method) for method in methods if method != "HEAD"
        )
    assert router_routes == EXPECTED_ADMIN_SURFACE
    assert boundary_routes == {
        f"/api/v1/admin/{family}/{{rest:path}}" for family in TRUTH_FAMILIES
    }


def test_anonymous_probes_on_admin_and_dashboard_endpoints_are_rejected() -> None:
    override_subject(None)
    try:
        with TestClient(app) as client:
            probes = [
                client.get("/api/v1/governance/dashboard"),
                client.get("/api/v1/admin/research-sources"),
                client.post("/api/v1/admin/research-sources", json={
                    "stable_key": "refinery.probe",
                    "display_name": "probe",
                    "origin": "refinery",
                    "owner_subject_id": str(uuid.uuid4()),
                    "classification": "internal",
                }),
                client.get(f"/api/v1/admin/research-sources/{uuid.uuid4()}"),
                client.patch(
                    f"/api/v1/admin/research-sources/{uuid.uuid4()}",
                    json={"reason": "probe"},
                ),
                client.get("/api/v1/admin/settings"),
                client.put(
                    "/api/v1/admin/settings/gap.sla.assign_hours",
                    json={"value": 48, "reason": "probe"},
                ),
                client.get("/api/v1/admin/settings/gap.sla.assign_hours/versions"),
                client.post(
                    f"/api/v1/admin/gaps/{uuid.uuid4()}/priority",
                    json={"priority": "high", "reason": "probe"},
                ),
                client.get("/api/v1/admin/subjects"),
                client.post(
                    f"/api/v1/admin/subjects/{uuid.uuid4()}/bindings",
                    json={
                        "binding": "role",
                        "key": "curator",
                        "operation": "assign",
                        "reason": "probe",
                    },
                ),
                client.get("/api/v1/admin/jobs/health"),
                client.get("/api/v1/admin/pilot-readiness"),
            ] + [
                client.post(f"{prefix}anything", json={})
                for prefix in BOUNDARY_PREFIXES
            ]
    finally:
        clear_override()
    for response in probes:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"
        assert response.json()["request_id"]


@pytest.mark.asyncio
async def test_non_admin_subjects_are_refused_before_any_data_access() -> None:
    """Policy gates run before any repository call, so no DB is needed here."""
    service = AdminGovernanceService()
    curator = subject(Role.CURATOR)
    staff = subject(Role.STAFF)
    for caller in (curator, staff):
        with pytest.raises(PermissionError, match="admin_required"):
            await service.create_source(
                caller,
                stable_key="refinery.unit",
                display_name="unit",
                description="",
                origin="refinery",
                owner_subject_id=uuid.uuid4(),
                classification="internal",
                lifecycle="active",
                request_id="admin-unit-1",
            )
        with pytest.raises(PermissionError, match="admin_required"):
            await service.update_source(
                caller,
                uuid.uuid4(),
                classification="restricted",
                reason="probe",
                request_id="admin-unit-2",
            )
        with pytest.raises(PermissionError, match="admin_required"):
            await service.list_sources(caller, request_id="admin-unit-3")
        with pytest.raises(PermissionError, match="admin_required"):
            await service.source_detail(
                caller,
                uuid.uuid4(),
                request_id="admin-unit-4",
            )
        with pytest.raises(PermissionError, match="admin_required"):
            await service.settings_overview(caller, request_id="admin-unit-5")
        with pytest.raises(PermissionError, match="admin_required"):
            await service.setting_versions(
                caller,
                "gap.sla.assign_hours",
                request_id="admin-unit-6",
            )
        with pytest.raises(PermissionError, match="admin_required"):
            await service.list_subjects(caller, request_id="admin-unit-7")
        with pytest.raises(PermissionError, match="admin_required"):
            await service.mutate_binding(
                caller,
                uuid.uuid4(),
                binding="role",
                key="curator",
                operation="assign",
                reason="probe",
                request_id="admin-unit-8",
            )
        with pytest.raises(PermissionError, match="admin_required"):
            await service.job_health(caller, request_id="admin-unit-9")
        with pytest.raises(PermissionError, match="admin_required"):
            await service.pilot_readiness(caller, request_id="admin-unit-10")


def test_bounded_admin_payloads_refuse_unknown_and_malformed_fields() -> None:
    """AC-11 bounded fields: content smuggling through admin payloads fails
    with a typed validation error before any handler or database access."""
    override_subject(subject(Role.ADMIN))
    try:
        with TestClient(app) as client:
            content_smuggle = client.patch(
                f"/api/v1/admin/research-sources/{uuid.uuid4()}",
                json={"reason": "smuggle", "content": {"value": "forged fact"}},
            )
            searchable_smuggle = client.post(
                "/api/v1/admin/research-sources",
                json={
                    "stable_key": "refinery.unit",
                    "display_name": "unit",
                    "origin": "refinery",
                    "owner_subject_id": str(uuid.uuid4()),
                    "classification": "internal",
                    "searchable_text": "forged research text",
                },
            )
            bad_priority = client.post(
                f"/api/v1/admin/gaps/{uuid.uuid4()}/priority",
                json={"priority": "extreme", "reason": "bad vocabulary"},
            )
            bad_binding = client.post(
                f"/api/v1/admin/subjects/{uuid.uuid4()}/bindings",
                json={
                    "binding": "policy",
                    "key": "curator",
                    "operation": "assign",
                    "reason": "policy objects are not bindable",
                },
            )
    finally:
        clear_override()
    for response in (content_smuggle, searchable_smuggle, bad_priority, bad_binding):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


def test_admin_error_codes_are_mapped_to_stable_statuses() -> None:
    assert STATUS_BY_CODE["research_source_not_found"] == 404
    assert STATUS_BY_CODE["subject_not_found"] == 404
    assert STATUS_BY_CODE["binding_not_found"] == 404
    assert STATUS_BY_CODE["research_source_exists"] == 409
    assert STATUS_BY_CODE["binding_exists"] == 409
    assert STATUS_BY_CODE["owner_subject_unknown"] == 422
    assert STATUS_BY_CODE["source_update_empty"] == 422
    assert STATUS_BY_CODE["role_unknown"] == 422
    assert STATUS_BY_CODE["group_unknown"] == 422


def test_dashboard_zone_labels_are_structurally_unforgeable() -> None:
    """Every tile carries its constant zone label; forging any other zone is
    a validation error, so the UI can always separate SOT from research."""
    sot_tiles = (
        CoverageTile(
            total_records=0,
            by_source_key={},
            by_owner={},
            by_classification={},
        ),
        FreshnessTile(total=0, expiring=0, expired=0, assigned=0, unassigned=0),
        GapFlowTile(
            open_total=0,
            closed_total=0,
            overdue=0,
            by_state={},
            aging=dict.fromkeys(AGE_BUCKETS, 0),
        ),
    )
    for tile in sot_tiles:
        assert tile.zone_label == "sot"
    research_tiles = (
        ResearchIntakeTile(
            sources_total=0,
            sources_active=0,
            packages_by_state={},
            records_by_tier={},
        ),
        GraduationFunnelTile(proposed=0, approved=0, rejected=0, submitted=0),
    )
    for tile in research_tiles:
        assert tile.zone_label == "research"
    with pytest.raises(ValidationError):
        CoverageTile(
            zone_label="research",  # type: ignore[arg-type]
            total_records=0,
            by_source_key={},
            by_owner={},
            by_classification={},
        )
    with pytest.raises(ValidationError):
        ResearchIntakeTile(
            zone_label="sot",  # type: ignore[arg-type]
            sources_total=0,
            sources_active=0,
            packages_by_state={},
            records_by_tier={},
        )


def test_gap_aging_buckets_have_exact_boundaries() -> None:
    now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
    assert aging_bucket(now, now=now) == "under_24h"
    assert aging_bucket(now - timedelta(hours=23, minutes=59), now=now) == "under_24h"
    assert aging_bucket(now - timedelta(hours=24), now=now) == "days_1_3"
    assert aging_bucket(now - timedelta(hours=71, minutes=59), now=now) == "days_1_3"
    assert aging_bucket(now - timedelta(hours=72), now=now) == "days_3_7"
    assert aging_bucket(now - timedelta(hours=167, minutes=59), now=now) == "days_3_7"
    assert aging_bucket(now - timedelta(hours=168), now=now) == "over_7_days"
    assert aging_bucket(now - timedelta(days=90), now=now) == "over_7_days"
