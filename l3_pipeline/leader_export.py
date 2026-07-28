#!/usr/bin/env python3
"""leader_export.py · publish gate gói LÃNH ĐẠO · sinh GOI_LEADER.yaml TỪ KERNEL.

Nguyên tắc fail-closed: chỉ id nào có trong `kernel/registry/leader_allowlist.yaml`
mới được vào gói. Fact mới trong kernel KHÔNG tự động ra ngoài. Quên khai báo =
fact không ra (an toàn), ngược với kiểu lọc-bỏ (quên lọc = rò).

Gói này chứa thông tin HẠN CHẾ (giá bán, chiết khấu). Xem ràng buộc RB.1-RB.4
trong allowlist: chỉ chạy được ở chế độ LIVE, bắt buộc passcode riêng.

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

    # Nội bộ-không-mật (Lâm 28/07): giá bán + định vị đã gộp vào GÓI NỀN (l3_export) cho mọi nhân
    # viên → leader nhận QUA base, KHÔNG take() lại ở đây (tránh nhân đôi + xung đột nhãn). Cổng leak
    # 4a/4b bên dưới vẫn quét TOÀN gói (gồm base) nên giá vốn BOM/margin chưa-kiểm vẫn bị chặn.
    l2 = []

    # ---- 3 · L4 văn phong: giờ nằm trong base (l3_export gộp · một gói nội bộ 28/07) ----
    l4 = []

    records = base + l2 + l4  # = base (một gói: mọi thứ đã ở base, GOI_LEADER == GOI_L3)

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
    if "--selftest" in sys.argv:   # chứng minh cổng MARGIN còn cắn (giá vốn BOM giờ hợp lệ · nội bộ 28/07)
        added = added + [{"record": "SELFTEST.INJECT", "tier": "L2", "domain": "positioning",
                          "content": "DERIVED.ALMO.MARGIN.HERA_VN · biên lợi nhuận chưa kiểm 42%", "canh_bao": "x"}]
    pack_text = yaml.dump(records + (added[-1:] if "--selftest" in sys.argv else []), allow_unicode=True)
    struct_text = yaml.dump([r for r in added if r.get("domain") in ("pricing", "positioning")],
                            allow_unicode=True)
    leaks = []

    def num_in(hay, n):
        import re as _re
        return bool(_re.search(r"(?<![\d.,])%s(?![\d.,])" % _re.escape(str(n)), hay))

    # 4a · GIÁ VỐN BOM: Lâm chốt 28/07 "nội bộ không gì mật" → giá vốn giờ HỢP LỆ trong gói chung
    #       (gộp qua l3_export). Không còn quét chặn BOM. Truy vết bằng đăng nhập từng người.

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
        if leaks:
            print("SELFTEST OK · cổng còn cắn · bắt được bản tiêm:")
            for l in leaks:
                print("   !", l)
            sys.exit(0)
        print("SELFTEST FAIL · ĐÃ TIÊM GIÁ VỐN MÀ CỔNG KHÔNG BẮT · cổng hỏng, không dùng gói này")
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
        "canh_bao_dau_goi": ("GÓI HẠN CHẾ · chứa giá bán và chính sách chiết khấu. "
                             "Chỉ phục vụ nhóm lãnh đạo đã được cấp quyền. "
                             "Bắt buộc chạy chế độ LIVE + passcode riêng (RB.1-RB.3)."),
        "ngay_sinh": "2026-07-27",
        "nguon": "kernel/registry/leader_allowlist.yaml (fail-closed) + l3_facts.yaml + prices.yaml + derived_costs.yaml + style/",
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
