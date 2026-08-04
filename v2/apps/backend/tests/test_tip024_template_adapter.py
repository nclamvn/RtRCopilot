import io
from pathlib import Path

from docx import Document
from openpyxl import Workbook, load_workbook

from rtr_copilot.pilot.template_adapter import adapt_templates


def _docx(path: Path, fields: list[str]) -> None:
    document = Document()
    document.add_paragraph(" · ".join("{{" + item + "}}" for item in fields))
    document.save(path)


def _registry() -> str:
    return """schema_version: '1.0'
last_updated: '2026-07-27'
templates:
- id: congvan
  name: Cong van
  desc: Governed letter
  file: CongVan_RTR.docx
  kind: docx
  category: External
  version: v1
  fields:
  - {key: ngay_ky, label: Date, type: user, required: true, format: date}
  - {key: ngay, label: Day, type: derived, from: ngay_ky, part: day}
  - {key: nguoi_ky, label: Signer, type: locked, record: L3F.RES.002}
- id: salesbrief
  name: Sales brief
  desc: Governed workbook
  file: SalesBrief_VN.xlsx
  kind: xlsx
  sheet: Brief
  category: Sales
  version: v1
  fields:
  - {key: customer, label: Customer, type: user, required: true, cell: C6}
- id: factsheet
  name: Fact sheet
  desc: Governed facts
  file: FactSheet_SanPham.docx
  kind: docx
  category: Product
  version: v1
  fields:
  - {key: payload, label: Payload, type: locked, record: CAND.1.005}
  - {key: flight, label: Flight, type: locked, record: CAND.1.006}
- id: slidecard
  name: Slide card
  desc: Governed slide card
  file: SlideCard_RtR.docx
  kind: docx
  category: Deck
  version: v1
  fields:
  - {key: range, label: Range, type: locked, record: L3R.K.007}
"""


def test_adapter_remaps_retired_facts_and_is_byte_deterministic(tmp_path: Path) -> None:
    (tmp_path / "registry.yaml").write_text(_registry(), encoding="utf-8")
    _docx(tmp_path / "CongVan_RTR.docx", ["ngay_ky", "ngay", "nguoi_ky"])
    _docx(tmp_path / "FactSheet_SanPham.docx", ["payload", "flight"])
    _docx(tmp_path / "SlideCard_RtR.docx", ["range"])
    workbook = Workbook()
    workbook.active.title = "Brief"
    workbook.save(tmp_path / "SalesBrief_VN.xlsx")

    first = adapt_templates(tmp_path)
    second = adapt_templates(tmp_path)
    assert [item.fingerprint for item in first.templates] == [
        item.fingerprint for item in second.templates
    ]
    factsheet = next(item for item in first.templates if item.template_id == "factsheet")
    facts = {
        field.field_path: field for field in factsheet.payload.field_schema.bindings
    }
    assert facts["payload"].record_key == "SPEC.HERA.PAYLOAD.MAX"
    assert facts["payload"].value_template == "{value} {unit}"
    assert facts["flight"].record_key == "SPEC.HERA.FLIGHT.NO_PAYLOAD"
    assert not any(
        str(field.record_key).startswith("CAND.")
        for item in first.templates for field in item.payload.field_schema.bindings
    )
    sales = next(item for item in first.templates if item.template_id == "salesbrief")
    binary = __import__("base64").b64decode(sales.payload.source_base64)
    adapted = load_workbook(io.BytesIO(binary))
    try:
        assert adapted["Brief"]["C6"].value == "{{customer}}"
    finally:
        adapted.close()
