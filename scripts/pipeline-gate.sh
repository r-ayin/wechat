#!/bin/bash
# pipeline-gate.sh — 微信管线强制执行门禁 v1.1
# 用法: bash pipeline-gate.sh {check|verify|status} {phase} {topic} {date}
# 每个阶段启动前必须先过门禁。不过门禁 = 管线拒绝执行。
# 这不是建议，是硬编码阻断。
#
# v1.1 修复:
#   GATE-01: Phase 3.5 FALSIFIED 正则适配实际报告格式（表格式/标题式/旧式）
#   GATE-03: Phase 3 摘要检查兼容 markdown 加粗格式
#   GATE-04: resolve_checkpoint 严格匹配 topic，不再静默 fallback 到无关 topic
#   GATE-05: local var=$(cmd) 拆分声明与赋值，避免吞掉 set -e 退出码
#   GATE-06: 标题长度取首个 markdown 标题行，不取 frontmatter
#   GATE-07: 标题长度去除末尾换行，避免恒 +1
#   GATE-09: DATE 参数生效（非空时按日期过滤），默认空=取最新
#
# 门禁阈值来源:
# Phase 0/1: 基于历史产出文件大小分布的下限
# Phase 2: 基于 CLAUDE.md 定义的字数标准 (15000 汉字 × 3 bytes/char ≈ 45000 bytes)
# Phase 3: 同上
# 标题长度: 微信公众号显示约束 (短标题无辨识度，长标题被截断)

set -euo pipefail

ACTION="${1:-}"
PHASE="${2:-}"
TOPIC="${3:-}"
# GATE-09: DATE 默认空（不按日期过滤，取最新）；显式传入时按该日期过滤
DATE="${4:-}"
RESEARCH_DIR="output/research"
ARTICLE_DIR="output/wechat_articles"
WECHAT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# GATE-10 (WM-GATE-02): TOPIC 直接插值进 find -name 的 glob（resolve_checkpoint 各 case）。
# TOPIC 来自 agent/用户输入；含 glob 元字符 * ? [ ] 时会拓宽匹配（strict 模式下
# ${TOPIC}_*.md 变 *_*.md 全匹配），导致跨 topic 误判/checkpoint 串读。
# 空 TOPIC 是合法值（status/loose 模式），仅在非空时校验为 slug 字符集。
if [ -n "$TOPIC" ] && [[ "$TOPIC" =~ [^a-zA-Z0-9_-] ]]; then
    echo "❌ GATE-10: 非法 TOPIC 字符（仅允许 [a-zA-Z0-9_-]）：拒绝 glob 注入到 find -name" >&2
    exit 1
fi

# 确保输出目录存在
mkdir -p "$WECHAT_ROOT/$RESEARCH_DIR" "$WECHAT_ROOT/$ARTICLE_DIR/hot" "$WECHAT_ROOT/$ARTICLE_DIR/evergreen"

# === checkpoint 文件解析 ===
# 严格模式：仅匹配指定 TOPIC 的文件；TOPIC 为空或无匹配时返回空（不 fallback 到无关 topic）
# 松散模式：仅供 status 使用，允许跨 topic 取最新（带 sort -r）
resolve_checkpoint() {
    local key="$1"
    local mode="${2:-strict}"
    local list=""

    case "$key" in
        "0-competitor")
            list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_competitor-style_*.md" 2>/dev/null)
            [ -z "$list" ] && [ "$mode" = "loose" ] && list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_competitor-style_*.md" 2>/dev/null)
            ;;
        "1-brief")
            list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_brief_*.md" 2>/dev/null)
            [ -z "$list" ] && [ "$mode" = "loose" ] && list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_brief_*.md" 2>/dev/null)
            ;;
        "2-analysis")
            list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_analysis_*.md" 2>/dev/null)
            [ -z "$list" ] && [ "$mode" = "loose" ] && list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_analysis_*.md" 2>/dev/null)
            ;;
        "3-article")
            list=$(find "$WECHAT_ROOT/$ARTICLE_DIR" -maxdepth 3 -name "${TOPIC}_*.md" 2>/dev/null)
            [ -z "$list" ] && [ "$mode" = "loose" ] && list=$(find "$WECHAT_ROOT/$ARTICLE_DIR" -maxdepth 3 -name "*.md" -path "*20[0-9][0-9]*" 2>/dev/null)
            ;;
        "3.5-qa")
            # 兼容新管线（output/state/{slug}_qa_report.json）与旧 markdown（output/research/{slug}_QA_*.md）
            list=$(find "$WECHAT_ROOT/output/state" -maxdepth 1 -name "${TOPIC}_qa_report*.json" 2>/dev/null)
            [ -z "$list" ] && list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_QA_*.md" 2>/dev/null)
            [ -z "$list" ] && [ "$mode" = "loose" ] && list=$(find "$WECHAT_ROOT/output/state" -maxdepth 1 -name "*_qa_report*.json" 2>/dev/null)
            [ -z "$list" ] && [ "$mode" = "loose" ] && list=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_QA_*.md" 2>/dev/null)
            ;;
    esac

    # GATE-09: DATE 非空时先按日期过滤候选列表，再取最新（避免只过滤 head 后的单条）
    if [ -n "$list" ] && [ -n "$DATE" ]; then
        local filtered
        filtered=$(printf '%s\n' "$list" | grep -F "_${DATE}")
        [ -n "$filtered" ] && list="$filtered"
    fi

    printf '%s\n' "$list" | sort -r | head -1
}

# GATE-01: 从 QA 报告中提取 FALSIFIED 计数，兼容多种格式
qa_falsified_count() {
    local f="$1"
    local n=""

    # 新管线：verifier.py judge 产出 JSON，summary.falsified 即 FALSIFIED 计数
    if [[ "$f" == *.json ]]; then
        n=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('summary',{}).get('falsified',''))" "$f" 2>/dev/null)
        if [ -n "$n" ]; then echo "$n"; return; fi
        # 备选：直接 grep JSON 字段
        n=$(grep -oE '"falsified"\s*:\s*[0-9]+' "$f" 2>/dev/null | head -1 | grep -oE '[0-9]+' | head -1)
        if [ -n "$n" ]; then echo "$n"; return; fi
        echo ""
        return
    fi

    # 旧 markdown 报告：汇总表行 "| 🚫 FALSIFIED | <n> | <pct>% |"
    n=$(grep -Eo '\|\s*🫧?\s*🚫?\s*FALSIFIED\s*\|\s*[0-9]+\s*\|' "$f" 2>/dev/null | head -1 | grep -Eo '[0-9]+' | head -1)
    if [ -n "$n" ]; then echo "$n"; return; fi
    # 备选1：标题 "#### 🚫 FALSIFIED (0项)"
    n=$(grep -Eo 'FALSIFIED\s*\(\s*[0-9]+\s*项' "$f" 2>/dev/null | head -1 | grep -Eo '[0-9]+' | head -1)
    if [ -n "$n" ]; then echo "$n"; return; fi
    # 备选2：旧格式 "FALSIFIED: 0" / "FALSIFIED：0"
    n=$(grep -Eo 'FALSIFIED[：:]\s*[0-9]+' "$f" 2>/dev/null | head -1 | grep -Eo '[0-9]+' | head -1)
    if [ -n "$n" ]; then echo "$n"; return; fi
    # 备选3："0 项 FALSIFIED" / "X 项 FALSIFIED"
    n=$(grep -Eo '[0-9]+\s*项\s*FALSIFIED' "$f" 2>/dev/null | head -1 | grep -Eo '[0-9]+' | head -1)
    if [ -n "$n" ]; then echo "$n"; return; fi
    echo ""
}

# === 门禁函数 ===

gate_check() {
    local phase="$1"
    local missing=()
    local f=""

    case "$phase" in
        "0") ;; # 无前置
        "1")
            f=$(resolve_checkpoint "0-competitor")
            [ -n "$f" ] && [ -s "$f" ] || missing+=("competitor-style (竞品五维蒸馏)")
            ;;
        "2")
            f=$(resolve_checkpoint "1-brief")
            [ -n "$f" ] && [ -s "$f" ] || missing+=("brief (研究简报)")
            ;;
        "3")
            f=$(resolve_checkpoint "2-analysis")
            [ -n "$f" ] && [ -s "$f" ] || missing+=("analysis (godtier 13层分析)")
            ;;
        "3.5")
            f=$(resolve_checkpoint "3-article")
            [ -n "$f" ] && [ -s "$f" ] || missing+=("persona文章")
            ;;
        "4")
            f=$(resolve_checkpoint "3.5-qa")
            [ -n "$f" ] && [ -s "$f" ] || missing+=("QA报告")
            ;;
        *)
            echo "❌ 未知阶段: $phase (有效: 0 1 2 3 3.5 4)"
            exit 1
            ;;
    esac

    if [ ${#missing[@]} -gt 0 ]; then
        echo "🚫 门禁阻断 — 前置 checkpoint 缺失:"
        for m in "${missing[@]}"; do echo "   ❌ $m"; done
        echo "   这是硬阻断——不可跳过。请先完成前一阶段。"
        exit 2
    fi
    echo "✅ 门禁通过"
}

gate_verify() {
    local phase="$1"
    local f=""
    local size
    local layers
    local title_line title title_len
    local fc

    case "$phase" in
        "0")
            f=$(resolve_checkpoint "0-competitor")
            [ -z "$f" ] && { echo "❌ competitor-style 文件缺失"; exit 3; }
            size=$(wc -c < "$f")
            # 基于历史竞品文件最低 2859B，设置 2000B 为安全下限
            [ "$size" -lt 2000 ] && { echo "❌ < 2KB ($size bytes)"; exit 3; }
            grep -qE "维度1|维度2|维度3|维度4|维度5|五维" "$f" || { echo "❌ 五维不完整"; exit 3; }
            # GATE-03 同源：情感温度评估，兼容加粗与多种写法（X/10）
            grep -qE "[0-9]+\s*/\s*10" "$f" || { echo "❌ 缺少竞对情感温度评估 (X/10)"; exit 3; }
            echo "✅ Phase 0 验证通过 (${size} bytes)"
            ;;
        "1")
            f=$(resolve_checkpoint "1-brief")
            [ -z "$f" ] && { echo "❌ brief 文件缺失"; exit 3; }
            size=$(wc -c < "$f")
            # 基于历史简报最低 3215B，设置 1500B 为安全下限
            [ "$size" -lt 1500 ] && { echo "❌ < 1.5KB ($size bytes)"; exit 3; }
            echo "✅ Phase 1 验证通过 (${size} bytes)"
            ;;
        "2")
            f=$(resolve_checkpoint "2-analysis")
            [ -z "$f" ] && { echo "❌ analysis 文件缺失"; exit 3; }
            size=$(wc -c < "$f")
            # 基于 CLAUDE.md 深度长文标准 (15000汉字 × 3 bytes/char ≈ 45000 bytes)
            # 可配置：WECHAT_MIN_BYTES env（draft 模式可降至 12000）
            local min_bytes="${WECHAT_MIN_BYTES:-45000}"
            [ "$size" -lt "$min_bytes" ] && { echo "❌ < ${min_bytes}B ($size bytes, 不足 godtier 分析深度下限；如为草稿可 WECHAT_MIN_BYTES=12000)"; exit 3; }
            layers=$(grep -c "^## L" "$f" || true)
            [ "$layers" -lt 10 ] && { echo "❌ 仅${layers}层(需≥10)"; exit 3; }
            echo "✅ Phase 2 验证通过 (${size} bytes, ${layers}层)"
            ;;
        "3")
            f=$(resolve_checkpoint "3-article")
            [ -z "$f" ] && { echo "❌ 文章文件缺失"; exit 3; }
            size=$(wc -c < "$f")
            # 基于 CLAUDE.md 深度长文标准: 15000汉字 × 3 bytes/char ≈ 45000 bytes
            local min_bytes3="${WECHAT_MIN_BYTES:-45000}"
            [ "$size" -lt "$min_bytes3" ] && { echo "❌ < ${min_bytes3}B (约15000汉字，未达 CLAUDE.md 深度长文下限；如为草稿可 WECHAT_MIN_BYTES=12000)"; exit 3; }
            grep -q "SOUL+STYLE+PERSONA" "$f" || { echo "❌ 缺persona注入标记(metadata)；需在文章frontmatter中包含"; exit 3; }
            # GATE-03: 摘要检查兼容 markdown 加粗格式（**摘要**: / 摘要: / > 摘要:）
            grep -q "摘要" "$f" || { echo "❌ 缺摘要(公众号显示必需)"; exit 3; }
            # GATE-06/07: 取首个 markdown 标题行（非 frontmatter），printf 去末尾换行
            title_line=$(grep -m1 '^# ' "$f" || true)
            title="${title_line#\# }"
            title_len=$(printf '%s' "$title" | wc -m)
            [ "$title_len" -lt 8 ] && { echo "❌ 标题过短(<8字, 公众号列表页无辨识度)"; exit 3; }
            [ "$title_len" -gt 35 ] && echo "⚠️  标题过长(>35字, 公众号推送中被截断)"
            grep -qE "你只需要|只要我们还" "$f" && echo "⚠️  检测到可能反模式结尾"
            # W-02/W-06/QAH-03：确定性风格/结尾/逻辑一致性 advisory 检查（只告警不阻断）
            # WM-GATE-01 (audit-2026-07-05-001)：f 来自 resolve_checkpoint 的 find，
            # find 根是绝对路径 "$WECHAT_ROOT/$ARTICLE_DIR" → 输出已是绝对路径，
            # 旧 `"$WECHAT_ROOT/$f"` 双前缀得到不存在的路径，python FileNotFoundError，
            # 三个 checker 静默不告警即放行。改用 $f 本身（已绝对）。
            local full="$f"
            for checker in style_fingerprint ending_detector structural_consistency_checker; do
                local script="$WECHAT_ROOT/scripts/$checker.py"
                if [ -f "$script" ]; then
                    local out rc
                    set +e
                    out=$(python3 "$script" "$full" 2>&1)
                    rc=$?
                    set -e
                    if [ $rc -eq 1 ]; then
                        echo "⚠️  $checker: BLOCK（详见 --tool $checker）"
                    elif [ $rc -eq 2 ]; then
                        echo "⚠️  $checker: WARN"
                    elif [ $rc -ne 0 ]; then
                        # 兜底：rc 不在 {0,1,2}（如路径不存在/异常退出）必须告警，禁止静默放行
                        echo "⚠️  $checker: 异常退出(rc=$rc)，请人工复核：${out:+${out:0:120}}"
                    fi
                fi
            done
            echo "✅ Phase 3 验证通过 (${size} bytes)"
            ;;
        "3.5")
            f=$(resolve_checkpoint "3.5-qa")
            [ -z "$f" ] && { echo "❌ QA报告缺失"; exit 3; }
            # GATE-01: 用 qa_falsified_count 解析实际格式，而非固定正则
            fc=$(qa_falsified_count "$f")
            if [ -z "$fc" ]; then
                echo "❌ 无法解析QA报告中的FALSIFIED计数（格式不识别）: $(basename "$f")"
                exit 3
            fi
            if [ "$fc" -ne 0 ]; then
                echo "❌ QA未通过(剩余 ${fc} 项未修复FALSIFIED)"
                exit 3
            fi
            echo "✅ Phase 3.5 验证通过 (FALSIFIED=0)"
            ;;
        "4")
            echo "✅ Phase 4 验证通过 (git commit + push 需手动确认)"
            ;;
        *)
            echo "❌ 未知阶段: $phase (有效: 0 1 2 3 3.5 4)"
            exit 1
            ;;
    esac
}

gate_status() {
    echo ""
    echo "═══════════════════════════════════════════════"
    echo "  微信管线状态  ${TOPIC:+(topic: ${TOPIC})}${DATE:+ (date: ${DATE})}"
    echo "═══════════════════════════════════════════════"
    echo ""
    local keys=("0-competitor:Phase 0 竞品蒸馏" "1-brief:Phase 1 研究简报" "2-analysis:Phase 2 godtier分析" "3-article:Phase 3 persona重写" "3.5-qa:Phase 3.5 QA门禁")
    for entry in "${keys[@]}"; do
        local key="${entry%%:*}"
        local label="${entry##*:}"
        f=$(resolve_checkpoint "$key" "loose")
        if [ -n "$f" ] && [ -s "$f" ]; then
            size=$(wc -c < "$f" 2>/dev/null || echo 0)
            echo "  ✅ $label ($(echo $size | tr -d ' ')B) — $(basename "$f")"
        else
            echo "  ⬜ $label"
        fi
    done
    echo ""
}

# === 主入口 ===

case "$ACTION" in
    "check")
        [ -z "$PHASE" ] && { echo "❌ 缺少 phase 参数"; exit 1; }
        gate_check "$PHASE"
        ;;
    "verify")
        [ -z "$PHASE" ] && { echo "❌ 缺少 phase 参数"; exit 1; }
        # GATE-04: check/verify 严格模式要求 TOPIC，避免跨 topic 误判
        if [ -z "$TOPIC" ]; then
            echo "⚠️  未指定 topic，verify 在严格模式下可能无法定位产物。建议: bash pipeline-gate.sh verify $PHASE <topic>"
        fi
        gate_verify "$PHASE"
        ;;
    "status")
        gate_status
        ;;
    *)
        echo "用法: pipeline-gate.sh {check|verify|status} {phase} {topic} {date}"
        echo ""
        echo "  check {phase} [topic] [date]  — 检查前置 checkpoint，不通过则阻断"
        echo "  verify {phase} {topic} [date] — 验证当前阶段产出质量"
        echo "  status [topic] [date]         — 显示管线状态面板"
        echo ""
        echo "  阶段: 0(竞品) 1(简报) 2(godtier) 3(persona) 3.5(QA) 4(输出)"
        echo "  topic: 选题 slug（verify 强烈建议显式传入，避免跨选题误判）"
        echo "  date : 可选，YYYY-MM-DD，传入则只匹配该日期产物；默认取最新"
        echo ""
        echo "  示例:"
        echo "    bash pipeline-gate.sh check 2 gaokao-major-choice 2026-06-24"
        echo "    bash pipeline-gate.sh verify 3.5 gaokao-major-choice 2026-06-25"
        echo "    bash pipeline-gate.sh status"
        exit 0
        ;;
esac
