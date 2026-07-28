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

def fmt_price(f):
    """Một dòng người đọc được từ fact giá · giữ nguyên đơn vị và trạng thái. (đồng bộ leader_export)"""
    val = f.get("value", f.get("claim"))
    unit = f.get("unit", "")
    txt = f"{f.get('key', f['id'])}: {val}"
    if unit and unit != "fraction":
        txt += f" {unit}"
    elif unit == "fraction" and isinstance(val, (int, float)):
        txt = f"{f.get('key', f['id'])}: {val*100:.1f}%"
    st = f.get("status", "")
    if st and st not in ("CHỐT", "VERIFIED"):
        txt += f" · TRẠNG THÁI {st} · chưa chốt, không dùng để cam kết"
    if f.get("notes"):
        txt += f" · ghi chú: {f['notes']}"
    return txt


def main():
    out_name = "GOI_L3.yaml"
    if "--out" in sys.argv:
        out_name = sys.argv[sys.argv.index("--out") + 1]

    reg = yaml.safe_load(KERNEL_REG.read_text())
    records, errors = [], []
    K = KERNEL_REG.parent  # kernel/registry

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

    # ---- GIÁ BÁN + GIÁ VỐN + ĐỊNH VỊ + VOICE · một gói nội bộ (Lâm chốt 28/07: "nội bộ không gì mật") ----
    # Mọi nhân viên nội bộ thấy hết: giá bán (prices.yaml), giá vốn BOM (boms.yaml), định vị
    # (derived_costs, chỉ id đã khai), văn phong CEO (style/). Đăng nhập từng người giữ để TRUY VẾT.
    # Vẫn giữ ngoài gói: margin chưa-kiểm (derived DRAFT/FLAG · doctrine A3) + deal/intel bên thứ ba.
    allow = yaml.safe_load((K / "leader_allowlist.yaml").read_text()) or {}

    def take_l2(section_key, reg_file, domain):
        wanted = list(((allow.get(section_key) or {}).get("allow", [])))
        if not wanted:
            return
        reg2 = yaml.safe_load((K / reg_file).read_text()) or {}
        by_id = {f["id"]: f for f in reg2.get("facts", [])}
        # mỏ neo tiếng Việt: content giá gốc tiếng Anh ("HERA US list price") · query Việt cần từ khoá Việt.
        vn = {"PRICE": "Giá bán nội bộ", "DISCOUNT": "Chiết khấu đại lý", "FX": "Tỷ giá tham chiếu",
              "REG": "Chính sách giá", "DERIVED": "Định vị giá so đối thủ"}
        for fid in wanted:
            f = by_id.get(fid)
            if not f:
                errors.append(f"{section_key}: allowlist khai {fid} nhưng kernel không có")
                continue
            anchor = vn.get(fid.split(".")[0], "Giá")
            records.append({
                "record": fid, "content": f"{anchor} · {fmt_price(f)}", "domain": domain,
                "tier": "L2", "status": "noi_bo", "kernel_ref": fid,
                "source": (f.get("source") or {}).get("file"),
                "effective_date": f.get("verified_date"),
            })

    take_l2("l2_pricing", "prices.yaml", "pricing")
    take_l2("l2_positioning", "derived_costs.yaml", "positioning")

    # Giá vốn linh kiện (BOM) · nội bộ-không-mật (Lâm 28/07): gộp cho mọi nhân viên.
    boms = yaml.safe_load((K / "boms.yaml").read_text()) or {}
    for f in boms.get("facts", []):
        vendor = f.get("vendor") or "?"
        country = f.get("country") or ""
        unit = f.get("unit") or ""
        records.append({
            "record": f["id"],
            "content": (f"Giá vốn linh kiện · {f.get('key', f['id'])}: {f.get('cost_usd')} USD"
                        + (f"/{unit}" if unit and unit != "USD" else "")
                        + f" · nhà cung cấp: {vendor}"
                        + (f" ({country})" if country else "")
                        + (f" · NDAA {f['ndaa_status']}" if f.get("ndaa_status") else "")),
            "domain": "cost", "tier": "L2", "status": "noi_bo", "kernel_ref": None,
            "source": (f.get("source") or {}).get("file") if isinstance(f.get("source"), dict) else f.get("source"),
            "effective_date": None,
        })

    # Văn phong CEO (L4) · để soạn thảo đúng giọng công ty. (allowlist path là kernel-root-relative)
    for rel in (allow.get("l4_voice") or {}).get("allow_files", []):
        vp = K.parent / rel
        if not vp.exists():
            errors.append(f"l4_voice: không thấy {rel}")
            continue
        records.append({
            "record": "VOICE." + Path(rel).stem.upper(),
            "content": vp.read_text(encoding="utf-8").strip(),
            "domain": "voice", "tier": "L4", "status": "noi_bo", "kernel_ref": rel,
            "source": rel, "effective_date": None,
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
