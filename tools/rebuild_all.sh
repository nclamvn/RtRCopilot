#!/bin/bash
# Tái sinh TOÀN BỘ artefact dẫn xuất từ kernel · một lệnh, đúng thứ tự.
#
#   ./tools/rebuild_all.sh
#
# Chạy sau MỌI lần sửa kernel (l3_facts.yaml, leader_allowlist.yaml, prices.yaml...).
# Lý do tồn tại: ba lần liên tiếp sửa kernel xong quên regen một artefact dẫn xuất
# (gói lãnh đạo, gói trong zip), khiến bản đang phục vụ mang thông tin cũ. Kỷ luật
# nhớ-thủ-công không chặn được, nên gộp thành một lệnh và khoá bằng test.

set -e
cd "$(dirname "$0")/.." || exit 1
ROOT="$PWD"
# Hai môi trường hai gốc đường dẫn (Claude Code vs Cowork) · dò thay vì đoán
for K in /Users/os/RtR/kernel /sessions/*/mnt/RtR/kernel; do
  [ -d "$K" ] && KERNEL="$K" && break
done
[ -n "$KERNEL" ] || { echo "DỪNG: không tìm thấy thư mục kernel"; exit 1; }
echo "RtR Copilot · tái sinh từ kernel"
echo "kernel: $KERNEL"
echo "────────────────────────────────────────"

# 1 · gói nhân viên
cd "$ROOT/l3_pipeline"
echo "[1/6] gói nhân viên"
python3 l3_export.py | sed 's/^/      /'

# 2 · gói lãnh đạo (chỉ khi đã dựng)
if [ -f GOI_LEADER.yaml ]; then
  echo "[2/6] gói lãnh đạo"
  python3 leader_export.py | sed 's/^/      /'
  echo "[3/6] cổng chống rò · tự chứng minh còn cắn"
  python3 leader_export.py --selftest | sed 's/^/      /'
else
  echo "[2-3/6] chưa dựng gói lãnh đạo · bỏ qua"
fi

# 4a · preview phải bám theo ui.html (nếu không, người soi thấy bản cũ)
echo "[4/6] preview giao diện"
python3 "$ROOT/tools/build_preview.py" | sed 's/^/      /'

# 4b · đóng gói · GÓI LÃNH ĐẠO KHÔNG BAO GIỜ VÀO ZIP
echo "[5/6] đóng gói kit"
cd "$ROOT/phase1_pilot"
rm -f qa_log.jsonl.bak
rm -f "$ROOT/Phase1_Pilot_Kit.zip"
zip -j -q "$ROOT/Phase1_Pilot_Kit.zip" \
  01_Setup_API_Server.md 01_Setup_Claude_Project.md 02_Huong_Dan_Nhom_Pilot.md \
  03_Bo_Cau_Test_Acceptance.md 04_So_Theo_Doi_4_Tuan.md 05_Van_Hanh_Lien_Tuc.md \
  06_Thu_Moi_Nhom_Pilot.md 07_Goi_Lanh_Dao.md 08_Tao_Tai_Lieu.md 09_Dang_Nhap_Nguoi_Dung.md com.rtr.copilot.plist \
  copilot_server.py ui.html test_copilot.py e2e_tester.py start_copilot.sh weekly_review.py users.example.yaml \
  "$ROOT/l3_pipeline/TIP7_SYSTEM_PROMPT_ClaudeProject.md" \
  "$ROOT/l3_pipeline/GOI_L3.yaml" \
  "$ROOT/l3_pipeline/l3_export.py" \
  "$ROOT/l3_pipeline/leader_export.py" \
  "$ROOT/RtR_Copilot_UI_Preview.html" \
  "$ROOT/tools/render_doc.py" \
  "$ROOT/tools/xlsx_patch.py" \
  "$ROOT/templates/registry.yaml" \
  "$ROOT/templates/CongVan_RTR.docx" \
  "$ROOT/templates/SalesBrief_VN.xlsx" \
  "$ROOT/templates/FactSheet_SanPham.docx" \
  "$ROOT/templates/SlideCard_RtR.docx" \
  "$KERNEL/registry/leader_allowlist.yaml"
echo "      $(unzip -l "$ROOT/Phase1_Pilot_Kit.zip" | tail -1 | tr -s ' ')"

# 5 · test · lớp 7 kiểm chính hai thứ vừa làm ở trên có khớp kernel không
echo "[6/6] bộ test (gồm cổng chống lệch pha)"
if python3 test_copilot.py > /tmp/rtr_rebuild_test.log 2>&1; then
  grep "KẾT QUẢ" /tmp/rtr_rebuild_test.log | sed 's/^/      /'
  rm -f qa_log.jsonl gap_log.jsonl; rm -rf __pycache__
  echo "────────────────────────────────────────"
  echo "XONG · kernel, hai gói, zip đồng bộ."
else
  echo "      TEST FAIL · KHÔNG dùng bản này"
  tail -14 /tmp/rtr_rebuild_test.log | sed 's/^/      /'
  exit 1
fi
