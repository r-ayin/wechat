#!/usr/bin/env bash
# daily-hotspot.sh — 每日热点选题日报编排（确定性，无 LLM 依赖）
#
# 链路：搜索取数 → hot-scanner consume 评分 → daily_report 渲染 HTML
#
# 取数后端（SEARCH_BACKEND，默认 brave；mihomo 不可用时自动降级 bocha）：
#   - brave : Brave API，需 BRAVE_SEARCH_KEY + mihomo 代理（systemd 守护，127.0.0.1:7890）
#   - bocha : 博查 API，需 BOCHA_API_KEY，国内直连（限流严重，fallback 用）
#   - bing  : 抓 cn.bing.com SERP，无需 key，中国 ECS 可达
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
# DeepSeek key 兜底：wechat-env 没配则从 personal-assistant .env 取（ECS 共置）
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f /opt/personal-assistant/.env ]; then
  DEEPSEEK_API_KEY="$(grep -E '^DEEPSEEK_API_KEY=' /opt/personal-assistant/.env \
    | head -1 | cut -d= -f2- | tr -d '\"' || true)"
  export DEEPSEEK_API_KEY
fi

# mihomo 代理自动注入：Brave 后端经 CloudUpup 订阅出海。
# mihomo down 或 Brave 经代理不可达时，把 backend 降级到 bocha（国内直连）。
# 显式 SEARCH_BACKEND 覆盖优先；仅在默认 brave 时触发降级。
BACKEND="${SEARCH_BACKEND:-brave}"
if [ "$BACKEND" = "brave" ]; then
  if ! systemctl is-active --quiet mihomo 2>/dev/null; then
    echo "  WARN: mihomo 不可用，Brave 需代理 — 降级到 bocha" | tee -a "$LOG"
    BACKEND=bocha
  else
    export HTTPS_PROXY="http://127.0.0.1:7890"
    export HTTP_PROXY="http://127.0.0.1:7890"
    # 健康探测：Brave 根路径经代理（5s 超时；-f 把 4xx/5xx 当失败）
    if ! curl -fs -m 5 -x "$HTTPS_PROXY" -o /dev/null https://api.search.brave.com/ 2>/dev/null; then
      echo "  WARN: Brave 经代理不可达 — 降级到 bocha（HTTPS_PROXY 已清）" | tee -a "$LOG"
      unset HTTPS_PROXY HTTP_PROXY
      BACKEND=bocha
    fi
  fi
fi

echo "===== $(date -Iseconds) daily-hotspot [$DATE] ====="

# --- 1. 可选 git pull ---
if [ -d .git ] && command -v git >/dev/null 2>&1; then
  git pull --ff-only 2>>"$LOG" || echo "  WARN: git pull 失败，继续"
fi

# --- 2. 搜索取数 ---
echo "  [2/5] 取数 (backend=$BACKEND)..."
USE_FALLBACK=1
if [ "$BACKEND" = "bocha" ]; then
  if [ -z "${BOCHA_API_KEY:-}" ]; then
    echo "  WARN: BOCHA_API_KEY 未设置，跳过取数（用共享池渲染）" | tee -a "$LOG"
  else
    python3 scripts/bocha_search.py \
      --output "$SCAN_RAW" --top 5 --concurrency 3 --sleep 0.3 2>>"$LOG"
    USE_FALLBACK=0
  fi
elif [ "$BACKEND" = "brave" ]; then
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
  echo "  [3/5] consume 评分..."
  # 3a. 当天日报文件（min-score 0，保留全部今日选题）
  python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
    --output "$SCAN_DAILY" --min-score 0 2>>"$LOG"
  # 3b. 注入共享池（min-score 6.0，保质量，自动去重合并）
  python3 topic-pool/hot-scanner.py consume "$SCAN_RAW" \
    --output "$SCAN_POOL" --min-score 6.0 2>>"$LOG"
else
  echo "  WARN: 取数为空或失败，跳过 consume（用共享池渲染）" | tee -a "$LOG"
fi

# --- 4. DeepSeek 精炼（把 Bing 摘要炼成真热点标题 + 事实摘要）---
# DEEPSEEK_API_KEY 缺失则跳过，保留原 query 标题（不阻断渲染）。
if [ -n "${DEEPSEEK_API_KEY:-}" ] && [ -s "$SCAN_DAILY" ]; then
  echo "  [4/5] DeepSeek 精炼标题+摘要..."
  python3 scripts/deepseek_refine.py \
    --scan "$SCAN_DAILY" --raw "$SCAN_RAW" 2>>"$LOG" \
    && echo "  ✅ 精炼完成" | tee -a "$LOG" \
    || echo "  ⚠️ 精炼失败（保留原标题继续渲染）" | tee -a "$LOG"
else
  echo "  [4/5] 跳过 DeepSeek 精炼（无 key 或无 scan-daily）" | tee -a "$LOG"
fi

# --- 5. 渲染 HTML ---
echo "  [5/5] 渲染日报..."
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

# --- 5. 邮件推送（可选：SMTP_HOST 配置了才推，失败不阻断）---
if [ -n "${SMTP_HOST:-}" ] && [ -n "${MAIL_TO:-}" ]; then
  echo "  [5/5] 邮件推送..."
  python3 scripts/mail_push.py "$REPORT" 2>>"$LOG" \
    && echo "  ✅ 已发邮件到 $MAIL_TO" | tee -a "$LOG" \
    || echo "  ⚠️ 邮件推送失败（报告仍已生成）" | tee -a "$LOG"
fi

# --- 6. QQ 推送（可选：QQ_APP_ID 配置了才推，失败不阻断）---
if [ -n "${QQ_APP_ID:-}" ] && [ -n "${QQ_TARGET:-}" ]; then
  echo "  [6/6] QQ 推送..."
  python3 scripts/qq_push.py "$REPORT" 2>>"$LOG" \
    && echo "  ✅ 已推送到 QQ" | tee -a "$LOG" \
    || echo "  ⚠️ QQ 推送失败（报告仍已生成）" | tee -a "$LOG"
fi

echo "===== done ====="
