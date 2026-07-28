import openpyxl, os, sys
BK="/sessions/intelligent-affectionate-planck/mnt/KnowledgeBase/_archives/maintenance_workbooks_truoc_SPECFIX01_20260727"
INTENDED = {
 "00_RtR_Chuong_Trinh_Bao_Duong_Tong_The.xlsx": {"05_Gap_Phe_duyet!"+c for c in ("I5","J5","I6","J6","I8","J8","I9","J9")},
 "01_CRM_Bao_Duong_HERA.xlsx": {"00_Kich_ban!C5"} | {"01_Danh_muc_nen!"+c for c in ("D6","H11","C12","H12","H16","C17","D17","H17","C19","D19","H19")} | {"02_Khach_hang_TS!"+c for c in ("E12","E13","E14")},
 "02_CRM_Bao_Duong_HeraHub.xlsx": {"01_Danh_muc_nen!H13"},
 "09_Vi_Du_Bao_Duong_HERA_3_Thang_3_Khach_Hang.xlsx": {"01_KH_Tai_san!"+c for c in ("H6","H7","H8")},
}
fail = 0
for mode, lbl in ((True, "GIÁ TRỊ (gồm cached công thức)"), (False, "CÔNG THỨC")):
    print(f"\n===== {lbl} =====")
    for f, want in INTENDED.items():
        a=openpyxl.load_workbook(os.path.join(BK,f), data_only=mode)
        b=openpyxl.load_workbook(f, data_only=mode)
        got=set()
        for sn in b.sheetnames:
            for row in b[sn].iter_rows():
                for c in row:
                    if (a[sn].cell(c.row,c.column).value or "")!=(c.value or ""):
                        got.add(f"{sn}!{c.coordinate}")
        extra, miss = got-want, want-got
        ok = not extra and not miss
        print(f"  {'OK  ' if ok else 'FAIL'} {f}: {len(got)} ô đổi / mong đợi {len(want)}")
        if extra: print("        DÔI:", sorted(extra)); fail=1
        if miss:  print("        THIẾU:", sorted(miss)); fail=1
# công thức còn sống?
wb=openpyxl.load_workbook("01_CRM_Bao_Duong_HERA.xlsx", data_only=True)
kpi=[wb["09_KPI"].cell(r,7).value for r in range(6,10)]
cost=wb["04_Van_hanh_DV"]["N6"].value
print(f"\nGiá trị công thức còn nguyên? KPI={kpi} · tổng chi phí N6={cost}")
if not all(kpi) or not cost: print("  FAIL: mất giá trị công thức"); fail=1
else: print("  OK: cached formula values nguyên vẹn")
sys.exit(fail)
