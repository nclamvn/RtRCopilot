#!/usr/bin/env python3
"""leader_export.py · publish gate gói LÃNH ĐẠO · sinh GOI_LEADER.yaml TỪ KERNEL.

Nguyên tắc fail-closed: chỉ id nào có trong `kernel/registry/leader_allowlist.yaml`
mới được vào gói. Fact mới trong kernel KHÔNG tự động ra ngoài. Quên khai báo =
fact không ra (an toàn), ngược với kiểu lọc-bỏ (quên lọc = rò).

Gói này chứa thông tin HẠN CHẾ: giá bán, chiết khấu, VÀ giá vốn linh kiện + nhà cung
cấp (l2_cost · leader-only · nhân viên không có). Xem ràng buộc RB.1-RB.4 trong
allowlist: chỉ chạy được ở chế độ LIVE, bắt buộc passcode riêng.

Usage: python3 leader_export.py [--out GOI_LEADER.yaml]
"""
import sys
import yaml
from pathlib import Path

HERE = Path(__file__).resolve().parent

def kernel_root():
    for p in (Path("/Users/os/RtR/kernel"), Path("/sessions/intelligent-affectionate-planck/mnt/RtR/kernel")):
        if p.exists():
            return p
    sys.exit("Không tìm thấy thư mục kernel")

K = kernel_root()
ALLOW = K / "registry/leader_allowlist.yaml"


def load(p):
    return yaml.safe_load(Path(p).read_text(encoding="utf-8"))


def fmt_price(f):
    """Một dòng người đọc được từ fact giá · giữ nguyên đơn vị và trạng thái."""
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
    out_name = "GOI_LEADER.yaml"
    if "--out" in sys.argv:
        out_name = sys.argv[sys.argv.index("--out") + 1]

    allow = load(ALLOW)
    records, errors, denied_hits = [], [], []

    # ---- 1 · nền: toàn bộ gói L3 (chạy l3_export trước, đọc lại kết quả) ----
    l3_path = HERE / "GOI_L3.yaml"
    if not l3_path.exists():
        sys.exit("Chưa có GOI_L3.yaml · chạy `python3 l3_export.py` trước")
    l3 = load(l3_path)
    base = l3.get("records", [])
    if not allow.get("base_pack", {}).get("include_all_l3"):
        sys.exit("allowlist tắt base_pack · chưa hỗ trợ")

    # ---- 2 · L2 giá + định vị theo allowlist ----
    def take(section_key, reg_file, tier_label):
        sec = allow.get(section_key) or {}
        wanted = list(sec.get("allow", []))
        if not wanted:
            return []
        reg = load(K / reg_file)
        by_id = {f["id"]: f for f in reg.get("facts", [])}
        out = []
        for fid in wanted:
            f = by_id.get(fid)
            if not f:
                errors.append(f"{section_key}: allowlist khai {fid} nhưng kernel không có")
                continue
            out.append({
                "record": fid,
                "content": fmt_price(f),
                "domain": "pricing" if section_key == "l2_pricing" else "positioning",
                "tier": "L2",
                "status": "restricted",
                "kernel_ref": fid,
                "source": (f.get("source") or {}).get("file"),
                "effective_date": f.get("verified_date"),
                "canh_bao": "THÔNG TIN HẠN CHẾ · chỉ nhóm lãnh đạo · không chuyển tiếp ra ngoài",
            })
        # cảnh báo nếu allowlist bỏ sót fact nhạy cảm mà kernel có
        for fid, f in by_id.items():
            if fid not in wanted:
                denied_hits.append(f"{reg_file}:{fid} (không trong allowlist · giữ ngoài gói)")
        return out

    # Giá bán + định vị + voice: đã ở GÓI NỀN (base, từ l3_export) cho mọi nhân viên → leader nhận
    # qua base, không take() lại (tránh nhân đôi). Leader THÊM đúng một lớp: giá VỐN BOM (l2_cost),
    # thứ đã rời khỏi gói nhân viên khi khôi phục ranh giới 28/07/2026 (nhân viên thấy BÁN, leader thấy MUA).
    def take_cost():
        sec = allow.get("l2_cost") or {}
        if not sec.get("include_all"):
            return []
        reg = load(K / "registry/boms.yaml")
        out = []
        for f in reg.get("facts", []):
            vendor = f.get("vendor") or "?"
            country = f.get("country") or ""
            unit = f.get("unit") or ""
            # Doctrine A3: fact giá vốn chưa kiểm chứng (provenance claim/flagged · vd SKU.* từ worksheet
            # Almo) phải mang nhãn CHƯA KIỂM — không cite ra ngoài khi chưa CFO duyệt.
            chua_kiem = f.get("provenance_level") not in ("verified_primary", "verified")
            out.append({
                "record": f["id"],
                "content": (f"Giá vốn linh kiện · {f.get('key', f['id'])}: {f.get('cost_usd')} USD"
                            + (f"/{unit}" if unit and unit != "USD" else "")
                            + f" · nhà cung cấp: {vendor}"
                            + (f" ({country})" if country else "")
                            + (f" · NDAA {f['ndaa_status']}" if f.get("ndaa_status") else "")
                            + (" · CHƯA KIỂM CHỨNG · CFO duyệt trước khi cite" if chua_kiem else "")),
                "domain": "cost", "tier": "L2", "status": "restricted", "kernel_ref": f["id"],
                "source": (f.get("source") or {}).get("file") if isinstance(f.get("source"), dict) else f.get("source"),
                "effective_date": None,
                "canh_bao": "THÔNG TIN HẠN CHẾ · giá vốn + nhà cung cấp · chỉ nhóm lãnh đạo · không chuyển tiếp",
            })
        return out

    l2 = take_cost()

    # ---- 3 · L4 văn phong: giờ nằm trong base (l3_export gộp · một gói nội bộ 28/07) ----
    l4 = []

    records = base + l2 + l4  # base (gói nhân viên) + l2 (giá vốn BOM leader-only) · GOI_LEADER ⊋ GOI_L3

    # ---- 4 · CỔNG TỰ KIỂM · chứng minh gói KHÔNG chứa thứ bị cấm ----
    # Không đủ nếu chỉ "không đọc tới": phải quét thành phẩm tìm dấu vết dữ liệu cấm.
    #
    # Phạm vi có chủ đích:
    #  · quét ID trên TOÀN gói (id là chuỗi riêng, không đụng hàng)
    #  · quét CON SỐ chỉ trên phần exporter này thêm vào (added), vì số trần
    #    trùng lặp vô hại rất nhiều trong gói nền (35000 mAh dung lượng pin
    #    trùng 35000 USD giá vốn khung). Gói nền có cổng kiểm riêng ở test_copilot.
    #  · quét CON SỐ chỉ trên record GIÁ có cấu trúc (một dòng do exporter sinh),
    #    không quét văn xuôi tự do: số nhỏ như 400 va vào bất kỳ đoạn văn nào.
    added = l2 + l4
    if "--selftest" in sys.argv:   # tiêm 1 record margin chưa-kiểm để chứng minh cổng 4b còn cắn
        added = added + [{"record": "SELFTEST.INJECT", "tier": "L2", "domain": "positioning",
                          "content": "DERIVED.ALMO.MARGIN.HERA_VN · biên lợi nhuận chưa kiểm 42%", "canh_bao": "x"}]
    pack_text = yaml.dump(records + (added[-1:] if "--selftest" in sys.argv else []), allow_unicode=True)
    struct_text = yaml.dump([r for r in added if r.get("domain") in ("pricing", "positioning")],
                            allow_unicode=True)
    leaks = []

    def num_in(hay, n):
        import re as _re
        return bool(_re.search(r"(?<![\d.,])%s(?![\d.,])" % _re.escape(str(n)), hay))

    # 4a · GIÁ VỐN leader-only (ranh giới khôi phục 28/07/2026): base = gói NHÂN VIÊN, KHÔNG được
    #      chứa id nào của boms.yaml. Canh theo TẬP ID NGUỒN (25 fact: 16 BOM.* linh kiện + 9 SKU.*
    #      giá vốn thành phẩm), KHÔNG theo tiền tố "BOM." — tiền tố sót 9 SKU. Leader tự thêm qua l2.
    cost_ids = {f["id"] for f in (load(K / "registry/boms.yaml") or {}).get("facts", [])}
    scan_base = list(base)
    if "--selftest" in sys.argv and cost_ids:
        scan_base.append({"record": sorted(cost_ids)[0]})   # tiêm 1 id giá vốn THẬT vào base
    for r in scan_base:
        if r.get("record") in cost_ids:
            leaks.append(f"giá vốn lọt vào GÓI NHÂN VIÊN (base): {r['record']}")

    # 4b · fact chi phí phái sinh CHƯA KIỂM (margin DRAFT/FLAG) · doctrine A3 vẫn cấm phơi số chưa kiểm
    derived = load(K / "registry/derived_costs.yaml")
    allowed_ids = set((allow.get("l2_positioning") or {}).get("allow", []))
    for f in derived.get("facts", []):
        if f["id"] in allowed_ids:
            continue
        if f["id"] in pack_text:
            leaks.append(f"fact chi phí bị cấm lọt vào gói: {f['id']}")
        v = f.get("value", f.get("claim"))
        if v and num_in(struct_text, v):
            leaks.append(f"số chi phí bị cấm lọt vào gói: {f['id']} = {v}")

    # 4c · mọi record HẠN CHẾ do exporter này thêm phải mang nhãn cảnh báo
    #     (record trong gói nền không thuộc phạm vi này · chúng là fact công khai)
    for r in added:
        if not r.get("canh_bao"):
            leaks.append(f"record hạn chế thiếu nhãn cảnh báo: {r['record']}")

    if "--selftest" in sys.argv:
        bom_bit = any("giá vốn lọt vào" in l for l in leaks)       # cổng 4a (giá vốn vào gói nhân viên)
        margin_bit = any("chi phí bị cấm" in l for l in leaks)     # cổng 4b (margin chưa kiểm)
        if bom_bit and margin_bit:
            print("SELFTEST OK · cả hai cổng còn cắn (4a giá vốn leader-only + 4b margin chưa kiểm):")
            for l in leaks:
                print("   !", l)
            sys.exit(0)
        print(f"SELFTEST FAIL · cổng không bắt đủ bản tiêm · 4a(BOM)={bom_bit} 4b(margin)={margin_bit} · không dùng gói này")
        sys.exit(3)

    if leaks:
        print("STATUS: FAIL · CỔNG TỰ KIỂM BẮT ĐƯỢC RÒ")
        for l in leaks:
            print("  !", l)
        sys.exit(2)

    if errors:
        print("STATUS: FAIL")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    doc = {
        "goi": "RtR Copilot · GÓI LÃNH ĐẠO",
        "canh_bao_dau_goi": ("GÓI HẠN CHẾ · chứa giá bán, chính sách chiết khấu VÀ giá vốn linh kiện "
                             "+ tên nhà cung cấp (leader-only · nhân viên không có). "
                             "Chỉ phục vụ nhóm lãnh đạo đã được cấp quyền. "
                             "Bắt buộc chạy chế độ LIVE + passcode riêng (RB.1-RB.3)."),
        "ngay_sinh": "2026-07-27",
        "nguon": "kernel/registry/leader_allowlist.yaml (fail-closed) + l3_facts.yaml + prices.yaml + derived_costs.yaml + boms.yaml (l2_cost leader-only) + style/",
        "duyet_boi": allow.get("approved_by"),
        "thong_ke": {
            "tong_record": len(records),
            "l3_nen": len(base),
            "l2_han_che": len(l2),
            "l4_van_phong": len(l4),
            "giu_ngoai_goi": len(denied_hits),
        },
        "records": records,
    }
    out = HERE / out_name
    out.write_text(yaml.dump(doc, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")

    print("STATUS: OK")
    print("out:", out_name)
    print(yaml.dump(doc["thong_ke"], allow_unicode=True, sort_keys=False))
    print("Giữ ngoài gói (fail-closed đã chặn):")
    for d in denied_hits:
        print("  -", d)


if __name__ == "__main__":
    main()
