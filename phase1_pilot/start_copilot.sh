#!/bin/bash
# RtR Copilot · khởi động một lệnh · tự kiểm tra trước khi chạy
#
#   ./start_copilot.sh
#
# Không có API key vẫn chạy (chế độ MOCK). Có key thì chạy LIVE.
# Key và passcode đọc từ file .env cạnh script (nếu có) để không phải export mỗi lần.

cd "$(dirname "$0")" || exit 1

echo "RtR Copilot · kiểm tra trước khi chạy"
echo "─────────────────────────────────────"

# 1 · Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "DỪNG: máy chưa có python3. Cài Python 3 rồi chạy lại."
  exit 1
fi
echo "OK   python3 $(python3 -V 2>&1 | cut -d' ' -f2)"

# 2 · Nạp .env nếu có (ANTHROPIC_API_KEY=... / COPILOT_PASSCODE=... mỗi dòng một biến)
if [ -f .env ]; then
  set -a; . ./.env; set +a
  echo "OK   nạp cấu hình từ .env"
fi

# 3 · File cần thiết
for f in copilot_server.py test_copilot.py; do
  [ -f "$f" ] || { echo "DỪNG: thiếu $f"; exit 1; }
done
GOI=""
for p in GOI_L3.yaml ../l3_pipeline/GOI_L3.yaml; do [ -f "$p" ] && GOI="$p" && break; done
[ -n "$GOI" ] || { echo "DỪNG: không tìm thấy GOI_L3.yaml"; exit 1; }
echo "OK   gói tri thức: $GOI ($(grep -c '^- record:' "$GOI") record)"

# 4 · Bộ test offline · KHÔNG chạy server nếu test fail
echo "..   chạy bộ test offline (khoảng 5 giây)"
if ! python3 test_copilot.py > /tmp/rtr_copilot_test.log 2>&1; then
  echo "DỪNG: bộ test FAIL · không khởi động server với gói lỗi."
  tail -12 /tmp/rtr_copilot_test.log
  echo "(log đầy đủ: /tmp/rtr_copilot_test.log)"
  exit 1
fi
echo "OK   $(grep 'KẾT QUẢ' /tmp/rtr_copilot_test.log)"

# 5 · Chế độ + địa chỉ
PORT="${COPILOT_PORT:-8787}"
if [ -n "$ANTHROPIC_API_KEY" ]; then
  echo "OK   chế độ LIVE (có API key) · model ${COPILOT_MODEL:-claude-sonnet-5}"
  echo "     NHẮC: chạy Phần D trong 03_Bo_Cau_Test_Acceptance.md trước khi mời nhóm"
else
  echo "!    chế độ MOCK (chưa có ANTHROPIC_API_KEY) · trả lời bằng máy tra cứu, không phải AI"
  echo "     Cắm key: tạo file .env với dòng  ANTHROPIC_API_KEY=sk-ant-..."
fi

if [ -n "$COPILOT_PASSCODE" ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
  echo "OK   có passcode · mở cho mạng nội bộ"
  [ -n "$IP" ] && echo "     Gửi nhân viên địa chỉ này:  http://$IP:$PORT"
else
  echo "!    chưa có COPILOT_PASSCODE · server chỉ mở trên máy này (127.0.0.1)"
fi

echo "─────────────────────────────────────"
echo "Khởi động... (Ctrl+C để dừng)"
echo
exec python3 copilot_server.py
