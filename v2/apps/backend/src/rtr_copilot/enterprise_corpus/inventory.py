"""Read-only inventory of the RtR enterprise knowledge ecosystem."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Zone = Literal["sot", "research", "private", "candidate"]
Admission = Literal["active", "adapter_ready", "inventory_only", "blocked"]

DOCUMENT_EXTENSIONS = frozenset({".pdf", ".docx", ".xlsx", ".pptx", ".md"})
STRUCTURED_EXTENSIONS = frozenset({
    ".csv", ".json", ".jsonl", ".sql", ".yaml", ".yml",
})
SKIP_DIRECTORIES = frozenset({
    ".git", ".next", ".venv", "node_modules", "__pycache__", "dist", "build",
})


@dataclass(frozen=True)
class SourceInventoryItem:
    source_key: str
    display_name: str
    zone: Zone
    admission: Admission
    root: str
    owner_boundary: str
    classification: str
    adapter: str | None
    record_count: int | None
    document_count: int
    structured_file_count: int
    gate: str


@dataclass(frozen=True)
class EcosystemInventory:
    items: list[SourceInventoryItem]

    def to_dict(self) -> dict[str, object]:
        return {"items": [asdict(item) for item in self.items]}


def _file_count(root: Path, extensions: frozenset[str]) -> int:
    if not root.exists():
        return 0
    count = 0
    for current, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in SKIP_DIRECTORIES]
        current_path = Path(current)
        count += sum(
            (current_path / name).suffix.casefold() in extensions
            for name in files
        )
    return count


def _document_count(root: Path) -> int:
    return _file_count(root, DOCUMENT_EXTENSIONS)


def _structured_count(root: Path) -> int:
    return _file_count(root, STRUCTURED_EXTENSIONS)


def _sum_counts(roots: list[Path], counter: Callable[[Path], int]) -> int:
    return sum(counter(root) for root in roots)


def _json_length(path: Path, key: str | None = None) -> int | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if key is not None and isinstance(value, dict):
        value = value.get(key)
    return len(value) if isinstance(value, dict | list) else None


def build_inventory(rtr_root: Path, knowledge_root: Path) -> EcosystemInventory:
    """Return a policy-aware inventory without reading credentials or databases."""

    rtr_root = rtr_root.resolve()
    knowledge_root = knowledge_root.resolve()
    kernel = rtr_root / "kernel"
    skywatch = rtr_root / "rtr-news" / "portal" / "out"
    skywatch_entities = _json_length(skywatch / "site-data.json", "entities") or 0
    skywatch_articles = _json_length(skywatch / "articles_records.json") or 0
    project_root = rtr_root / "rtr-quanlyduan"
    project_workspaces = sorted(
        path for path in rtr_root.glob("project_*") if path.is_dir()
    )
    project_roots = [project_root, rtr_root / "rtr-pm", *project_workspaces]
    items = [
        SourceInventoryItem(
            source_key="rtr.company-kernel",
            display_name="RtR company kernel and capability matrix",
            zone="sot",
            admission="active",
            root=str(kernel),
            owner_boundary="Company curator / domain owners",
            classification="internal + restricted by record",
            adapter="TIP-013B kernel adapter and SOT publish gate",
            record_count=219,
            document_count=_document_count(kernel / "source_canonical"),
            structured_file_count=_structured_count(kernel),
            gate="Existing active corpus; refresh only through curator publish",
        ),
        SourceInventoryItem(
            source_key="rtr.knowledgebase",
            display_name="RtR internal KnowledgeBase",
            zone="candidate",
            admission="inventory_only",
            root=str(knowledge_root),
            owner_boundary="Document owner + information-security classification",
            classification="unknown until manifest classification",
            adapter="TIP-008 file ingestion after approved manifest",
            record_count=None,
            document_count=_document_count(knowledge_root),
            structured_file_count=_structured_count(knowledge_root),
            gate="Owner, duplicate, freshness and ACL manifest required",
        ),
        SourceInventoryItem(
            source_key="rtr.projects",
            display_name="Project and proposal portfolio",
            zone="candidate",
            admission="inventory_only",
            root=str(rtr_root),
            owner_boundary="PMO / project owner",
            classification="internal to highly_restricted",
            adapter="Document manifest + project entity resolver",
            record_count=None,
            document_count=_sum_counts(project_roots, _document_count),
            structured_file_count=_sum_counts(project_roots, _structured_count),
            gate="Per-project ACL and current/superseded state required",
        ),
        SourceInventoryItem(
            source_key="theskywatch.registry",
            display_name="TheSkyWatch UAV and manufacturer registry",
            zone="research",
            admission="adapter_ready",
            root=str(skywatch),
            owner_boundary="TheSkyWatch data/editorial team",
            classification="public_internal",
            adapter="theskywatch-adapter-1.0",
            record_count=skywatch_entities + skywatch_articles,
            document_count=skywatch_articles,
            structured_file_count=_structured_count(skywatch),
            gate="Checksum, tier, evidence and Research-zone import",
        ),
        SourceInventoryItem(
            source_key="rtr.crm",
            display_name="CRM customers, deals and service records",
            zone="private",
            admission="inventory_only",
            root=str(rtr_root / "crm"),
            owner_boundary="Sales / account owner",
            classification="restricted by account and field",
            adapter="enterprise-readonly-connector-v1 (contract only)",
            record_count=None,
            document_count=_document_count(rtr_root / "crm"),
            structured_file_count=_structured_count(rtr_root / "crm"),
            gate=(
                "Contract ready; approved endpoint, service credential and "
                "owner sign-off required"
            ),
        ),
        SourceInventoryItem(
            source_key="rtr.mrp",
            display_name="MRP production, materials, quality and procurement",
            zone="private",
            admission="inventory_only",
            root=str(rtr_root / "rtr-mrp"),
            owner_boundary="Operations / finance / quality",
            classification="restricted by function and field",
            adapter="enterprise-readonly-connector-v1 (contract only)",
            record_count=None,
            document_count=_document_count(rtr_root / "rtr-mrp"),
            structured_file_count=_structured_count(rtr_root / "rtr-mrp"),
            gate=(
                "Contract ready; approved endpoint, service credential and "
                "owner sign-off required"
            ),
        ),
        SourceInventoryItem(
            source_key="rtr.ip",
            display_name="IP, patent and prior-art portfolio",
            zone="private",
            admission="inventory_only",
            root=str(rtr_root / "ip"),
            owner_boundary="IP/legal owner",
            classification="restricted to highly_restricted",
            adapter="enterprise-readonly-connector-v1 (contract only)",
            record_count=None,
            document_count=_document_count(rtr_root / "ip"),
            structured_file_count=_structured_count(rtr_root / "ip"),
            gate=(
                "Contract ready; privilege-preserving endpoint, credential and "
                "legal sign-off required"
            ),
        ),
        SourceInventoryItem(
            source_key="rtr.hrm",
            display_name="HRM people and organization data",
            zone="private",
            admission="blocked",
            root=str(rtr_root),
            owner_boundary="People operations / employee self-service",
            classification="restricted to highly_restricted by field",
            adapter=None,
            record_count=None,
            document_count=0,
            structured_file_count=0,
            gate="No authoritative HRM repository was discovered; connector and owner required",
        ),
        SourceInventoryItem(
            source_key="rtr.product-experience",
            display_name="Product websites, simulators and digital twins",
            zone="candidate",
            admission="inventory_only",
            root=str(rtr_root),
            owner_boundary="Product and engineering owners",
            classification="internal; public release artifacts separated by manifest",
            adapter="Build/artifact metadata adapter after product-owner approval",
            record_count=None,
            document_count=_sum_counts([
                rtr_root / "rtr-website",
                rtr_root / "rtr-simulator",
                rtr_root / "rtr-twin",
                rtr_root / "controltower",
                rtr_root / "XPO26",
            ], _document_count),
            structured_file_count=_sum_counts([
                rtr_root / "rtr-website",
                rtr_root / "rtr-simulator",
                rtr_root / "rtr-twin",
                rtr_root / "controltower",
                rtr_root / "XPO26",
            ], _structured_count),
            gate="Exclude build outputs and tests; bind releases to product/version owners",
        ),
        SourceInventoryItem(
            source_key="research.policy-sector",
            display_name="Policy and sector intelligence snapshots",
            zone="research",
            admission="inventory_only",
            root=str(knowledge_root / "Dataset_CongNgheChienLuoc"),
            owner_boundary="Research curator",
            classification="public_internal",
            adapter="Refinery snapshot adapter after TheSkyWatch",
            record_count=None,
            document_count=_document_count(
                knowledge_root / "Dataset_CongNgheChienLuoc",
            ),
            structured_file_count=_structured_count(
                knowledge_root / "Dataset_CongNgheChienLuoc",
            ),
            gate="Source-date, authority, quote span and supersession checks required",
        ),
    ]
    return EcosystemInventory(items=items)
