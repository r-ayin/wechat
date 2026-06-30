#!/usr/bin/env bash
# daily-hotspot.sh — 每日热点选题日报编排（确定性，无 LLM 依赖）
#
# 链路：搜索取数 → hot-scanner consume 评分 → daily_report 渲染 HTML
#
# 取数后端（SEARCH_BACKEND，默认 bing）：
#   - bing  : 抓 cn.bing.com SERP，无需 key，中国 ECS 可达（默认）
#   - brave : Brave API，需 BRAVE_SEARCH_KEY，中国 ECS 被封不可用（供有代理/海外机器用）
#
# 设计：
#   - 当天选题写独立日期戳文件 output/state/scan-daily-{date}.json（min-score 0，
#     保留全部今日选题给日报；不污染共享池）。
#   - 同时把高质量选题注入共享池 topic-pool/scan-results.json（min-score 6.0，
#     供文章管线选题用；consume 自动按 title 去重合并）。
#   - graceful fallback：取数失败时用共享池现有数据渲染，保证每天必有 HTML。
#
# 挂 cron（每天 07:00）：
#   0 7 * * * /opt/wechat/scripts/cron/daily-hotspot.sh >> /opt/wechat/output/cron/cron.log 2>&1

set -u  # 未定义变量报错；不用 -e，单步失败不阻断整体（每步自带 fallback）

# --- 路径与日期 ---
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || { echo "❌ 无法 cd 到 $ROOT"; exit 1; }

DATE="${REPORT_DATE:-$(date +%F)}"                     # YYYY-MM-DD
SCAN_RAW="/tmp/wechat-scan-${DATE}.json"               # 搜索取数原始输出
SCAN_DAILY="output/state/scan-daily-${DATE}.json"      # 当天选题（日报用）
SCAN_POOL="topic-pool/scan-results.json"               # 共享池（文章管线用）
REPORT="output/hotspot-report-${DATE}.html"
LOG_DIR="output/cron"
LOG="${LOG_DIR}/daily-${DATE}.log"

mkdir -p "$LOG_DIR" output/state

# 加载密钥（不打印）
if [ -f "${WECHAT_ENV:-$HOME/.wechat-env}" ]; then
  # shellcheck disable=SC1090
  set +u; source "${WECHAT_ENV:-$HOME/.wechat-env}"; set -u
fi

echo "===== $(date -Iseconds) daily-hotspot [$DATE] ====="

# --- 1. 可选 git pull ---
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  git pull --ff-only 2>>"$LOG" || echo "  WARN: git pull 失败，继续"
fi

# --- 2. 搜索取数 ---
BACKEND="${SEARCH_BACKEND:-bing}"
echo "  [2/4] 取数 (backend=$BACKEND)..."
USE_FALLBACK=1
if [ "$BACKEND" = "brave" ]; then
  if [ -z "${BRAVE_SEARCH_KEY:-}" ]; then
    echo "  WARN: BRAVE_SEARCH_KEY 未设置，跳过取数（用共享池渲染）" | tee -a "$LOG"
  else
    python3 scripts/brave_search.py \
      --output "$SCAN_RAW" --freshness pd --sleep 1.0 2>>"$LOG"
    USE_FALLBACK=0
  fi
elif [ "$BACKEND" = "bing" ]; then
  python3 scripts/bing_search.py \
    --output "$SCAN_RAW" --sleep 1.0 2>>"$LOG"
  USE_FALLBACK=0
else
  echo "  WARN: 未知 SEARCH_BACKEND=$BACKEND，跳过取数" | tee -a "$LOG"
fi

# --- 3. consume 评分 ---
if [ "${USE_FALLBACK:-0}" = "0" ] && [ -s "$SCAN_RAW" ]; then
  echo "  [3/4] consume 评分..."
  # 3a. 当天日报文件（min-score 0，保留全部今日选题）
  python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
    --output "$SCAN_DAILY" --min-score 0 2>>"$LOG"
  # 3b. 注入共享池（min-score 6.0，保质量，自动去重合并）
  python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
    --output "$SCAN_POOL" --min-score 6.0 2>>"$LOG"
else
  echo "  WARN: 取数为空或失败，跳过 consume（用共享池渲染）" | tee -a "$LOG"
fi

# --- 4. 渲染 HTML ---
echo "  [4/4] 渲染日报..."
# 优先用当天日报文件；为空则回退共享池
SCAN_FOR_REPORT="$SCAN_DAILY"
if [ ! -s "$SCAN_DAILY" ]; then
  echo "  WARN: 当天日报文件为空，回退到共享池 $SCAN_POOL" | tee -a "$LOG"
  SCAN_FOR_REPORT="$SCAN_POOL"
fi

python3 scripts/daily_report.py \
  --scan "$SCAN_FOR_REPORT" --date "$DATE" --output "$REPORT" 2>>"$LOG"

if [ -s "$REPORT" ]; then
  echo "  ✅ 报告: $REPORT ($(wc -c <"$REPORT") 字节)" | tee -a "$LOG"
else
  echo "  ❌ 报告生成失败: $REPORT" | tee -a "$LOG"
  exit 1
fi

echo "===== done ====="
