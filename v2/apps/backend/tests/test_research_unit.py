import json
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from research_fixtures import (
    CAPTURED_AT,
    build_research_package,
    research_record_row,
)

from rtr_copilot.api.main import app
from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.governance.api import STATUS_BY_CODE, governance_subject
from rtr_copilot.governance.models import (
    GraduationProposal,
    ResearchPackage,
    ResearchRecord,
    ResearchSource,
)
from rtr_copilot.research.candidate import build_candidate_package
from rtr_copilot.research.models import (
    CandidateClaim,
    ResearchCitation,
    ResearchHit,
    ResearchRecordView,
    ResearchSearchResponse,
)
from rtr_copilot.research.package import (
    ResearchManifestMember,
    ResearchPackageError,
    ResearchPackageParser,
    research_fingerprint,
    research_payload_sha,
)
from rtr_copilot.sot.package import PackageParser, sha256_bytes, validate_package

NOW = CAPTURED_AT + timedelta(hours=6)
SECRET = "test-only-dedicated-sot-signing-secret-32bytes"


def stage(root: Path, name: str, **parser_args: int) -> Any:
    return ResearchPackageParser(root, **parser_args).stage(name, now=NOW)


def expect(root: Path, name: str, code: str, **parser_args: int) -> None:
    with pytest.raises(ResearchPackageError) as failure:
        stage(root, name, **parser_args).load_records()
    assert failure.value.code == code


def test_valid_package_parses_identically_from_directory_and_zip(
    tmp_path: Path,
) -> None:
    rows = [
        research_record_row(record_key="IND.A", tier="P", text="alpha insight"),
        research_record_row(record_key="IND.B", tier="H", text="beta insight"),
    ]
    directory = build_research_package(tmp_path, records=rows)
    archive = build_research_package(tmp_path, records=rows, as_zip=True)
    staged_dir = stage(tmp_path, directory)
    staged_zip = stage(tmp_path, archive)
    assert staged_dir.manifest.fingerprint == staged_zip.manifest.fingerprint
    records = staged_dir.load_records()
    assert [item.record_key for item in records] == ["IND.A", "IND.B"]
    assert [item.tier for item in records] == ["P", "H"]
    assert staged_zip.load_records() == records
    assert staged_dir.manifest.scope == "industry-uav"
    assert staged_dir.manifest.record_count == 2


def test_manifest_level_violations_reject_before_identity_is_trusted(
    tmp_path: Path,
) -> None:
    missing = build_research_package(tmp_path)
    (tmp_path / missing / "manifest.json").unlink()
    expect(tmp_path, missing, "manifest_missing")

    expect(
        tmp_path,
        build_research_package(tmp_path, fingerprint="a" * 64),
        "fingerprint_mismatch",
    )
    expect(
        tmp_path,
        build_research_package(tmp_path, payload_sha256="b" * 64),
        "payload_checksum_mismatch",
    )

    def forge_member(manifest: dict[str, Any]) -> None:
        manifest["members"][0]["sha256"] = "c" * 64

    expect(
        tmp_path,
        build_research_package(tmp_path, mutate_manifest=forge_member),
        "member_checksum_mismatch",
    )

    unlisted = build_research_package(tmp_path)
    (tmp_path / unlisted / "notes.txt").write_text("smuggled")
    expect(tmp_path, unlisted, "unlisted_package_member")

    gone = build_research_package(tmp_path)
    (tmp_path / gone / "records.jsonl").unlink()
    expect(tmp_path, gone, "member_missing")

    expect(
        tmp_path,
        build_research_package(tmp_path, captured_at=NOW + timedelta(hours=1)),
        "captured_at_in_future",
    )

    def drop_scope(manifest: dict[str, Any]) -> None:
        del manifest["scope"]

    expect(
        tmp_path,
        build_research_package(tmp_path, mutate_manifest=drop_scope),
        "manifest_schema_invalid",
    )

    def future_schema(manifest: dict[str, Any]) -> None:
        manifest["schema_version"] = "2.0"

    expect(
        tmp_path,
        build_research_package(tmp_path, mutate_manifest=future_schema),
        "schema_major_unsupported",
    )


def test_traversal_symlink_and_missing_probes_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    for name in ("../evil", "/etc/passwd", "a/b"):
        with pytest.raises(ResearchPackageError) as failure:
            stage(root, name)
        assert failure.value.code == "package_path_unsafe"
    with pytest.raises(ResearchPackageError) as missing:
        stage(root, "does-not-exist")
    assert missing.value.code == "package_missing"

    outside = tmp_path / "outside-package"
    build_research_package(tmp_path, name="outside-package")
    (root / "linked").symlink_to(outside)
    with pytest.raises(ResearchPackageError) as linked:
        stage(root, "linked")
    assert linked.value.code == "package_path_unsafe"

    victim = tmp_path / "victim.jsonl"
    victim.write_text("outside data")
    inlined = build_research_package(root)
    (root / inlined / "records.jsonl").unlink()
    (root / inlined / "records.jsonl").symlink_to(victim)
    with pytest.raises(ResearchPackageError) as member:
        stage(root, inlined)
    assert member.value.code == "member_symlink_forbidden"


def test_size_budgets_reject_oversized_packages(tmp_path: Path) -> None:
    name = build_research_package(tmp_path)
    expect(tmp_path, name, "member_oversized", max_member_bytes=64)
    expect(tmp_path, name, "package_oversized", max_package_bytes=128)


def test_archive_safety_reuses_quarantine_rules(tmp_path: Path) -> None:
    garbage = tmp_path / "garbage.zip"
    garbage.write_bytes(b"PK\x03\x04 not really a zip archive")
    expect(tmp_path, "garbage.zip", "malformed_archive")

    not_zip = tmp_path / "plain.bin"
    not_zip.write_bytes(b"binary blob")
    expect(tmp_path, "plain.bin", "malformed_archive")

    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("../evil.txt", "escape")
    expect(tmp_path, "traversal.zip", "archive_path_unsafe")

    absolute = tmp_path / "absolute.zip"
    with zipfile.ZipFile(absolute, "w") as archive:
        archive.writestr("/etc/passwd", "escape")
    expect(tmp_path, "absolute.zip", "archive_path_unsafe")

    crowded = tmp_path / "crowded.zip"
    with zipfile.ZipFile(crowded, "w") as archive:
        for index in range(5):
            archive.writestr(f"member-{index}.txt", "x")
    expect(tmp_path, "crowded.zip", "archive_budget_exceeded", max_archive_entries=2)

    bloated = tmp_path / "bloated.zip"
    with zipfile.ZipFile(bloated, "w") as archive:
        archive.writestr("records.jsonl", "y" * 4096)
    expect(tmp_path, "bloated.zip", "archive_budget_exceeded", max_member_bytes=128)


def test_record_level_violations_reject_the_whole_package(tmp_path: Path) -> None:
    def package(rows: list[dict[str, Any]], **overrides: Any) -> str:
        return build_research_package(tmp_path, records=rows, **overrides)

    no_tier = research_record_row()
    del no_tier["tier"]
    expect(tmp_path, package([research_record_row(), no_tier]), "record_tier_missing")

    bad_tier = research_record_row()
    bad_tier["tier"] = "Z"
    expect(tmp_path, package([bad_tier]), "record_tier_invalid")

    no_evidence = research_record_row()
    no_evidence["evidence"] = []
    expect(tmp_path, package([no_evidence]), "record_evidence_missing")

    dropped_evidence = research_record_row()
    del dropped_evidence["evidence"]
    expect(tmp_path, package([dropped_evidence]), "record_evidence_missing")

    forged_span = research_record_row()
    forged_span["evidence"][0]["checksum"] = "f" * 64
    expect(tmp_path, package([forged_span]), "evidence_checksum_mismatch")

    forged_content = research_record_row()
    forged_content["content_sha256"] = "e" * 64
    expect(tmp_path, package([forged_content]), "record_checksum_mismatch")

    twin = research_record_row(record_key="IND.TWIN")
    expect(tmp_path, package([twin, dict(twin)]), "duplicate_record_key")

    expect(
        tmp_path,
        package([research_record_row()], record_count=5),
        "record_count_mismatch",
    )
    expect(tmp_path, package([], record_count=0), "record_set_empty")

    masquerading = research_record_row()
    masquerading["zone_label"] = "sot"
    expect(tmp_path, package([masquerading]), "zone_label_forged")

    labeled = research_record_row()
    labeled["zone_label"] = "research"
    staged = stage(tmp_path, package([labeled]))
    assert staged.load_records()[0].record_key == labeled["record_key"]

    broken = build_research_package(tmp_path, records=[research_record_row()])
    _rewrite_records(tmp_path / broken, b"{not json}\n")
    expect(tmp_path, broken, "record_schema_invalid")


def _rewrite_records(package_root: Path, payload: bytes) -> None:
    """Swap record bytes while keeping manifest identity checks consistent."""
    (package_root / "records.jsonl").write_bytes(payload)
    manifest = json.loads((package_root / "manifest.json").read_text())
    manifest["members"][0]["byte_size"] = len(payload)
    manifest["members"][0]["sha256"] = sha256_bytes(payload)
    manifest["payload_sha256"] = research_payload_sha([
        ResearchManifestMember.model_validate(member)
        for member in manifest["members"]
    ])
    manifest["fingerprint"] = research_fingerprint(
        source_key=manifest["source_key"],
        scope=manifest["scope"],
        captured_at=datetime.fromisoformat(manifest["captured_at"]),
        adapter_version=manifest["adapter_version"],
        payload_sha256=manifest["payload_sha256"],
    )
    (package_root / "manifest.json").write_text(json.dumps(manifest))


def test_zone_labels_are_structurally_unforgeable() -> None:
    record_view_payload: dict[str, Any] = {
        "research_record_id": uuid.uuid4(),
        "package_id": uuid.uuid4(),
        "package_fingerprint": "a" * 64,
        "source_key": "refinery.synthetic",
        "record_key": "IND.X",
        "version_ordinal": 1,
        "tier": "P",
        "content": {},
        "searchable_text": "text",
        "evidence": [],
        "corroboration_state": "uncorroborated",
        "content_sha256": "b" * 64,
        "created_at": datetime.now(UTC),
    }
    assert ResearchRecordView(**record_view_payload).zone_label == "research"
    with pytest.raises(ValidationError):
        ResearchRecordView(**record_view_payload, zone_label="sot")  # type: ignore[arg-type]
    citation_payload: dict[str, Any] = {
        "research_record_id": uuid.uuid4(),
        "record_key": "IND.X",
        "version_ordinal": 1,
        "tier": "S",
        "source_key": "refinery.synthetic",
        "package_fingerprint": "a" * 64,
        "content_sha256": "b" * 64,
        "corroboration_state": "uncorroborated",
        "evidence_checksums": ["c" * 64],
    }
    citation = ResearchCitation(**citation_payload)
    assert citation.zone_label == "research"
    with pytest.raises(ValidationError):
        ResearchCitation(**citation_payload, zone_label="sot")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ResearchHit(
            research_record_id=uuid.uuid4(),
            record_key="IND.X",
            tier="P",
            snippet="snippet",
            lexical_score=0.5,
            citation=citation,
            zone_label="private",  # type: ignore[arg-type]
        )
    response = ResearchSearchResponse(results=[], request_id="req-1")
    assert response.zone_label == "research"
    assert response.grounding == "research_supported"
    with pytest.raises(ValidationError):
        ResearchSearchResponse(
            results=[],
            request_id="req-1",
            grounding="sot_grounded",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        ResearchRecord(
            package_id=uuid.uuid4(),
            record_key="IND.X",
            version_ordinal=1,
            tier="P",
            zone_label="sot",  # type: ignore[arg-type]
            content={},
            searchable_text="text",
            evidence_spans=[{
                "source_url": "https://example.org",
                "locator": {},
                "quoted_text": "quote",
                "checksum": "d" * 64,
            }],
            content_sha256="e" * 64,
        )


def _graduation_fixture(
    *,
    source_classification: str = "internal",
    claim_classification: str = "internal",
) -> tuple[GraduationProposal, CandidateClaim, list[Any]]:
    proposer = uuid.uuid4()
    source = ResearchSource(
        stable_key="refinery.synthetic",
        display_name="Synthetic refinery corpus",
        origin="refinery",
        owner_subject_id=proposer,
        classification=source_classification,  # type: ignore[arg-type]
    )
    package = ResearchPackage(
        source_id=source.source_id,
        fingerprint="1" * 64,
        payload_sha256="2" * 64,
        snapshot_manifest={"scope": "industry", "adapter_version": "refinery-1"},
        captured_at=CAPTURED_AT,
        snapshot_scope="industry",
        adapter_version="refinery-1",
        import_state="imported",
        importer_subject_id=proposer,
    )
    record = ResearchRecord(
        package_id=package.package_id,
        record_key="IND.GRAD",
        version_ordinal=1,
        tier="P",
        content={"claim": "industry uses beacon relays"},
        searchable_text="industry uses beacon relays",
        evidence_spans=[{
            "source_url": "https://example.org/report",
            "locator": {"selector": "p:nth-of-type(4)"},
            "quoted_text": "industry uses beacon relays",
            "checksum": "3" * 64,
        }],
        content_sha256="4" * 64,
    )
    proposal = GraduationProposal(
        proposal_id=uuid.uuid4(),
        research_record_ids=[record.research_record_id],
        claim_draft={"claim_text": "Company operates beacon relays"},
        target_record_key="company.claims.beacon",
        proposer_subject_id=proposer,
        rationale="verbatim evidence supports the claim",
        state="approved",
        proposed_at=NOW,
    )
    claim = CandidateClaim(
        claim_text="Company operates beacon relays",
        classification=claim_classification,  # type: ignore[arg-type]
    )
    return proposal, claim, [(record, package, source)]


def test_candidate_package_is_a_valid_draft_claim_for_the_publish_gate(
    tmp_path: Path,
) -> None:
    proposal, claim, evidence = _graduation_fixture()
    staging_name = build_candidate_package(
        tmp_path,
        proposal=proposal,
        claim=claim,
        evidence=evidence,
        decider_id=uuid.uuid4(),
        signing_secret=SECRET,
        now=NOW,
    )
    parsed = PackageParser(tmp_path).parse(staging_name)
    report = validate_package(parsed, now=NOW)
    assert report.valid, [item.code for item in report.findings]
    record = parsed.records[0]
    assert record.provenance_level == "claim"
    assert record.verification_state == "claim"
    assert record.fact_state == "claim"
    lineage = record.value["lineage"]
    assert lineage["proposal_id"] == str(proposal.proposal_id)
    assert lineage["research_record_ids"] == [
        str(evidence[0][0].research_record_id)
    ]
    assert lineage["packages"][0]["fingerprint"] == "1" * 64
    assert lineage["evidence_checksums"] == ["3" * 64]
    assert record.source_refs == [f"research:{'1' * 64}"]
    assert parsed.evidence[0].quoted_text == "industry uses beacon relays"
    assert parsed.source_hashes[f"research:{'1' * 64}"].sha256 == "1" * 64


def test_candidate_package_downgrading_classification_fails_the_gate(
    tmp_path: Path,
) -> None:
    proposal, claim, evidence = _graduation_fixture(
        source_classification="restricted",
        claim_classification="internal",
    )
    staging_name = build_candidate_package(
        tmp_path,
        proposal=proposal,
        claim=claim,
        evidence=evidence,
        decider_id=uuid.uuid4(),
        signing_secret=SECRET,
        now=NOW,
    )
    report = validate_package(PackageParser(tmp_path).parse(staging_name), now=NOW)
    assert not report.valid
    assert "classification_downgrade" in {item.code for item in report.findings}


def override_subject(identity: Subject | None) -> None:
    async def resolve() -> Subject | None:
        return identity

    app.dependency_overrides[governance_subject] = resolve


def _staff_subject() -> Subject:
    return Subject(
        user_id=str(uuid.uuid4()),
        issuer="research-unit",
        sub=uuid.uuid4().hex,
        email="person@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={Role.STAFF},
    )


def test_anonymous_probes_on_research_and_graduation_endpoints() -> None:
    override_subject(None)
    identifier = uuid.uuid4()
    try:
        with TestClient(app) as client:
            probes = [
                client.post(
                    "/api/v1/research/packages/import",
                    json={"staging_name": "probe"},
                ),
                client.get("/api/v1/research/packages"),
                client.get(f"/api/v1/research/packages/{identifier}"),
                client.get(f"/api/v1/research/packages/{identifier}/records"),
                client.get(f"/api/v1/research/records/{identifier}"),
                client.post("/api/v1/research/search", json={"query": "probe"}),
                client.post("/api/v1/graduation/proposals", json={
                    "research_record_ids": [str(identifier)],
                    "claim": {"claim_text": "probe", "classification": "internal"},
                    "target_record_key": "company.probe",
                    "rationale": "probe",
                }),
                client.get("/api/v1/graduation/proposals"),
                client.get(f"/api/v1/graduation/proposals/{identifier}"),
                client.post(
                    f"/api/v1/graduation/proposals/{identifier}/decide",
                    json={"decision": "approved", "reason": "probe"},
                ),
            ]
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    for response in probes:
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"
        assert response.json()["request_id"]


def test_staff_cannot_import_or_propose_and_bad_decisions_are_422() -> None:
    override_subject(_staff_subject())
    try:
        with TestClient(app) as client:
            imported = client.post(
                "/api/v1/research/packages/import",
                json={"staging_name": "probe"},
            )
            proposed = client.post("/api/v1/graduation/proposals", json={
                "research_record_ids": [str(uuid.uuid4())],
                "claim": {"claim_text": "probe", "classification": "internal"},
                "target_record_key": "company.probe",
                "rationale": "probe",
            })
            malformed = client.post(
                f"/api/v1/graduation/proposals/{uuid.uuid4()}/decide",
                json={"decision": "maybe", "reason": "probe"},
            )
            unknown_state = client.get(
                "/api/v1/graduation/proposals",
                params={"state": "pending"},
            )
    finally:
        app.dependency_overrides.pop(governance_subject, None)
    assert imported.status_code == 403
    assert imported.json()["error"]["code"] == "curator_required"
    assert proposed.status_code == 403
    assert proposed.json()["error"]["code"] == "curator_required"
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "validation_error"
    assert unknown_state.status_code == 404
    assert unknown_state.json()["error"]["code"] == "not_found"


def test_status_map_covers_research_contract_codes() -> None:
    expectations = {
        "fingerprint_mismatch": 422,
        "manifest_missing": 422,
        "record_tier_missing": 422,
        "record_evidence_missing": 422,
        "evidence_checksum_mismatch": 422,
        "zone_label_forged": 422,
        "record_version_conflict": 422,
        "research_record_not_graduatable": 422,
        "research_package_not_found": 404,
        "research_record_not_found": 404,
        "proposal_not_found": 404,
        "package_path_unsafe": 400,
        "malformed_archive": 400,
        "archive_path_unsafe": 400,
    }
    for code, status in expectations.items():
        assert STATUS_BY_CODE[code] == status
