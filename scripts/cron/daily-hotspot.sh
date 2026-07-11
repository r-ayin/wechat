#!/usr/bin/env bash
# daily-hotspot.sh — 每日热点选题日报编排 (v3.0)
#
# 链路：搜索取数 → hot-scanner consume (LLM 评分+标题+摘要) → daily_report 渲染 HTML
#
# v3.0 变更:
#   - 默认 bing 搜索（免费无 cap，ECS 直连）
#   - hot-scanner consume 内置 LLM 评分，不再需要单独 deepseek_refine
#   - 移除 evergreen-pool 常青兜底
#   - 移除 brave 代理探测逻辑（bing 直连无需代理）
#
# 取数后端:
#   - bing  : 默认，抓 cn.bing.com SERP，无需 key，中国 ECS 可达
#   - brave : Brave API，需 BRAVE_SEARCH_KEY + 代理
#   - bocha : 博查 API，需 BOCHA_API_KEY
#
# 挂 cron（每天 07:00）：
#   0 7 * * * /opt/wechat/scripts/cron/daily-hotspot.sh >> /opt/wechat/output/cron/cron.log 2>&1

set -u

# --- 路径与日期 ---
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || { echo "❌ 无法 cd 到 $ROOT"; exit 1; }

DATE="${REPORT_DATE:-$(date +%F)}"
SCAN_RAW="/tmp/wechat-scan-${DATE}.json"
SCAN_DAILY="output/state/scan-daily-${DATE}.json"
SCAN_POOL="topic-pool/scan-results.json"
REPORT="output/hotspot-report-${DATE}.html"
LOG_DIR="output/cron"
LOG="${LOG_DIR}/daily-${DATE}.log"

mkdir -p "$LOG_DIR" output/state

# 加载密钥
if [ -f "${WECHAT_ENV:-$HOME/.wechat-env}" ]; then
  # shellcheck disable=SC1090
  set +u; source "${WECHAT_ENV:-$HOME/.wechat-env}"; set -u
fi
# DeepSeek key 兜底
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f /opt/personal-assistant/.env ]; then
  _ds_raw="$(sed -n 's/^DEEPSEEK_API_KEY=//p' /opt/personal-assistant/.env | head -1)"
  case "$_ds_raw" in
    \"*\") _ds_raw="${_ds_raw#\"}"; _ds_raw="${_ds_raw%\"}" ;;
    \'*\') _ds_raw="${_ds_raw#\'}"; _ds_raw="${_ds_raw%\'}" ;;
  esac
  if [ -n "$_ds_raw" ]; then
    DEEPSEEK_API_KEY="$_ds_raw"
    export DEEPSEEK_API_KEY
  fi
  unset _ds_raw
fi

# 取数后端 (默认 bing，免费无 cap)
BACKEND="${SEARCH_BACKEND:-bing}"
case "$BACKEND" in
  brave|bocha|bing) ;;
  *) echo "  WARN: 未知 SEARCH_BACKEND=$BACKEND，回退到 bing" | tee -a "$LOG"; BACKEND=bing ;;
esac

echo "===== $(date -Iseconds) daily-hotspot [$DATE] ====="

# --- 1. git pull ---
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  git pull --ff-only 2>>"$LOG" || echo "  WARN: git pull 失败，继续"
fi

# --- 2. 搜索取数 ---
echo "  [2/5] 取数 (backend=$BACKEND)..."
USE_FALLBACK=1
case "$BACKEND" in
  bing)
    python3 scripts/bing_search.py \
      --output "$SCAN_RAW" --sleep 1.0 2>>"$LOG"
    USE_FALLBACK=0
    ;;
  brave)
    if [ -z "${BRAVE_SEARCH_KEY:-}" ]; then
      echo "  WARN: BRAVE_SEARCH_KEY 未设置，跳过取数" | tee -a "$LOG"
    else
      python3 scripts/brave_search.py \
        --output "$SCAN_RAW" --freshness pd --sleep 1.0 2>>"$LOG"
      USE_FALLBACK=0
    fi
    ;;
  bocha)
    if [ -z "${BOCHA_API_KEY:-}" ]; then
      echo "  WARN: BOCHA_API_KEY 未设置，跳过取数" | tee -a "$LOG"
    else
      python3 scripts/bocha_search.py \
        --output "$SCAN_RAW" --top 5 --concurrency 3 --sleep 0.3 2>>"$LOG"
      USE_FALLBACK=0
    fi
    ;;
esac

# --- 3. consume 评分 (v3.0: LLM 一步到位 — 标题+摘要+评分) ---
if [ "${USE_FALLBACK:-0}" = "0" ] && [ -s "$SCAN_RAW" ]; then
  echo "  [3/5] consume 评分..."
  rm -f "$SCAN_DAILY"
  # 3a. 当天日报文件 (min-score 0，保留全部，让 LLM 评分决定质量)
  # 先尝试 LLM 评分；失败则自动回退到 --no-llm 本地评分
  python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
    --output "$SCAN_DAILY" --min-score 0 2>>"$LOG" \
    || python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
      --output "$SCAN_DAILY" --min-score 0 --no-llm 2>>"$LOG"
  # 3b. 注入共享池 (min-score 6.0，供文章管线选题)
  python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
    --output "$SCAN_POOL" --min-score 6.0 2>>"$LOG" \
    || python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
      --output "$SCAN_POOL" --min-score 6.0 --no-llm 2>>"$LOG"
else
  echo "  WARN: 取数为空或失败，跳过 consume" | tee -a "$LOG"
fi

# v3.0: deepseek_refine.py 已改为 no-op 兼容层
# (hot-scanner consume 已内置 LLM 精炼，不再需要单独 refine)

# --- 4. 渲染 HTML ---
echo "  [4/5] 渲染日报..."
SCAN_FOR_REPORT="$SCAN_DAILY"
if [ ! -s "$SCAN_DAILY" ]; then
  echo "  WARN: 当天日报文件为空，渲染占位页" | tee -a "$LOG"
fi

python3 scripts/daily_report.py \
  --scan "$SCAN_FOR_REPORT" --date "$DATE" --output "$REPORT" 2>>"$LOG"

if [ -s "$REPORT" ]; then
  echo "  ✅ 报告: $REPORT ($(wc -c <"$REPORT") 字节)" | tee -a "$LOG"
else
  echo "  ❌ 报告生成失败: $REPORT" | tee -a "$LOG"
  exit 1
fi

# --- 5. 邮件推送 ---
if [ -n "${SMTP_HOST:-}" ] && [ -n "${MAIL_TO:-}" ]; then
  echo "  [5/5] 邮件推送..."
  python3 scripts/mail_push.py "$REPORT" 2>>"$LOG" \
    && echo "  ✅ 已发邮件到 $MAIL_TO" | tee -a "$LOG" \
    || echo "  ⚠️ 邮件推送失败" | tee -a "$LOG"
fi

echo "===== done ====="