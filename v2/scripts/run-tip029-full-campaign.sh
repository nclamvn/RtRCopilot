#!/usr/bin/env bash
# TIP-029 — Approved full enterprise live campaign (Homeowner spend approval 08/08/2026).
# One command, end to end: preflight -> full campaign -> snapshot results ->
# commit + push branch tip-029-full-campaign for independent Contractor verify.
set -euo pipefail

v2_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_root="$(cd "$v2_root/.." && pwd)"
cd "$v2_root"

env_file="${E2E_ENV_FILE:-.env.demo}"

# ---- Preflight (fail loud, before any spend) --------------------------------
if [[ ! -f "$env_file" ]]; then
  echo "PREFLIGHT FAIL: thiếu $env_file — tạo từ .env.demo.example và điền key LLM đã rotate." >&2
  exit 2
fi
if ! grep -qE '^(ANTHROPIC_API_KEY|OPENAI_API_KEY)=..+' "$env_file"; then
  echo "PREFLIGHT FAIL: $env_file chưa có ANTHROPIC_API_KEY/OPENAI_API_KEY." >&2
  echo "Thiếu key, campaign rơi về evidence-only và chắc chắn trượt gate chất lượng — dừng trước khi tốn tiền/thời gian." >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "PREFLIGHT FAIL: Docker daemon chưa chạy — mở Docker Desktop rồi chạy lại." >&2
  exit 2
fi
if ! command -v pnpm >/dev/null 2>&1; then
  echo "PREFLIGHT FAIL: thiếu pnpm (cần cho browser live suite)." >&2
  exit 2
fi
if [[ -n "$(git -C "$repo_root" status --porcelain --untracked-files=no)" ]]; then
  echo "PREFLIGHT FAIL: working tree có thay đổi chưa commit — commit/stash trước để kết quả gắn đúng SHA." >&2
  exit 2
fi
head_sha="$(git -C "$repo_root" rev-parse --short HEAD)"
echo "PREFLIGHT OK · runtime sẽ chứng nhận tại HEAD=$head_sha · env=$env_file"

# ---- Run the approved full campaign (harness gates itself) ------------------
log="/tmp/tip029_full_campaign_$(date -u +%Y%m%d%H%M%S).log"
echo "Log đầy đủ: $log"
run_marker="$(mktemp /tmp/tip029_marker.XXXXXX)"   # mọi file cũ hơn marker = stale
set +e
E2E_APPROVE_FULL=1 \
E2E_SKIP_BUILD="${E2E_SKIP_BUILD:-0}" \
E2E_ENV_FILE="$env_file" \
  ./scripts/run-enterprise-e2e.sh 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
set -e

# ---- Snapshot results into tracked, TIP-stamped artifacts -------------------
summary="eval/real_world/latest_http_summary.json"
out_summary="eval/real_world/tip029_full_campaign_summary.json"
out_tail="eval/real_world/tip029_run_tail.log"
# Chỉ nhận summary SINH RA TRONG lần chạy này (mới hơn marker). File cũ từ lần
# chạy trước là bằng chứng giả — ghi error JSON trung thực thay vì copy nhầm.
if [[ -f "$summary" && "$summary" -nt "$run_marker" ]]; then
  cp "$summary" "$out_summary"
else
  echo '{"error":"campaign did not produce a fresh summary this run (stale or missing)","exit":'"$status"'}' > "$out_summary"
fi
rm -f "$run_marker"
{
  echo "# TIP-029 full campaign · HEAD=$head_sha · exit=$status · $(date -u +%FT%TZ)"
  tail -c 300000 "$log"
} > "$out_tail"

# ---- Commit + push for independent verify (PASS or FAIL — both are evidence) -
cd "$repo_root"
branch="tip-029-full-campaign"
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$current_branch" != "$branch" ]]; then
  # Tạo/chuyển nhánh TỪ HEAD HIỆN TẠI — không reset về main, để giữ nguyên
  # các commit fix đã nằm trên nhánh (chạy lại không phá paper trail).
  git checkout -B "$branch"
fi
git add "v2/$out_summary" "v2/$out_tail" \
  v2/scripts/run-tip029-full-campaign.sh \
  vibecode_v2/TIP-029_FULL_LIVE_CAMPAIGN.md
git commit -m "eval(tip-029): full enterprise live campaign @ $head_sha — exit=$status (spend approved 08/08)"
git push -u origin "$branch"

echo ""
if [[ "$status" -eq 0 ]]; then
  echo "TIP-029: ENTERPRISE E2E PASS — kết quả đã push lên nhánh $branch. Báo Thầu verify."
else
  echo "TIP-029: campaign exit=$status (có gate đỏ) — kết quả VẪN đã push lên $branch để Thầu phân tích. Không phải mất dữ liệu."
fi
exit "$status"
