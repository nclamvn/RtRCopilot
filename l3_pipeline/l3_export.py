#!/usr/bin/env python3
"""l3_export.py · publish gate · sinh GOI_L3.yaml TỪ KERNEL (NT-1 reproducible).

Nguồn duy nhất: kernel/registry/l3_facts.yaml (facts approved + kernel_refs).
KHÔNG đọc candidates/ (candidates là hồ sơ pipeline, không phải SOT).
Vòng cập nhật: curator nạp fact vào l3_facts.yaml → chạy script này → thay file trong Claude Project.

Usage: python3 l3_export.py [--out GOI_L3.yaml]
"""
import sys
import yaml
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL_REG = Path("/Users/os/RtR/kernel/registry/l3_facts.yaml")
if not KERNEL_REG.exists():  # Cowork sandbox mount
    KERNEL_REG = Path("/sessions/intelligent-affectionate-planck/mnt/RtR/kernel/registry/l3_facts.yaml")

def main():
    out_name = "GOI_L3.yaml"
    if "--out" in sys.argv:
        out_name = sys.argv[sys.argv.index("--out") + 1]

    reg = yaml.safe_load(KERNEL_REG.read_text())
    records, errors = [], []

    for f in reg.get("facts", []):
        if f.get("tier") not in ("L3", "L4"):
            errors.append(f"{f['id']}: tier lạ {f.get('tier')}")
            continue
        rec = {
            "record": f["id"],
            "content": f["content"],
            "domain": f.get("domain"),
            "tier": f["tier"],
            "status": "approved",
            "kernel_ref": None,
            "source": f.get("source_path"),
            "effective_date": f.get("effective_date"),
        }
        if "PROPOSED" in str(f.get("note") or "") + str(f.get("content") or ""):
            rec["label"] = "PROPOSED · chưa cam kết với khách"
        records.append(rec)

    for f in reg.get("kernel_refs", []):
        if f.get("tier") not in ("L3", "L4"):
            errors.append(f"{f['id']}: tier lạ")
            continue
        records.append({
            "record": f.get("origin_card") or f["id"],
            "content": f["content"],
            "domain": f.get("domain"),
            "tier": f["tier"],
            "status": "kernel_confirmed",
            "kernel_ref": f.get("kernel_ref"),
            "source": f.get("source_path"),
            "effective_date": f.get("effective_date"),
        })

    if errors:
        print(yaml.dump({"STATUS": "FAIL", "errors": errors}, allow_unicode=True))
        sys.exit(2)

    pack = {
        "goi": "RtR Copilot · Gói tri thức L3",
        "phien_ban": "1.0 · Lâm duyệt batch 27/07/2026",
        "ngay_sinh": "2026-07-27",
        "nguon": "kernel/registry/l3_facts.yaml (facts + kernel_refs) · export deterministic từ kernel",
        "luat_su_dung": [
            "Bot chỉ trả lời từ gói này (NT-1)",
            "Không có trong gói thì honest null (NT-2)",
            "Mọi câu trả lời kèm mã record (NT-3)",
            "Record label PROPOSED không được dùng cam kết với khách",
        ],
        "thong_ke": {
            "tong_record": len(records),
            "approved": sum(1 for r in records if r["status"] == "approved"),
            "kernel_confirmed": sum(1 for r in records if r["status"] == "kernel_confirmed"),
        },
        "records": records,
    }
    (HERE / out_name).write_text(yaml.dump(pack, allow_unicode=True, sort_keys=False, width=110))
    print(yaml.dump({"STATUS": "OK", "out": out_name, "thong_ke": pack["thong_ke"]}, allow_unicode=True))

if __name__ == "__main__":
    main()
