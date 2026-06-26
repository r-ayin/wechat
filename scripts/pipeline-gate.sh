#!/bin/bash
# pipeline-gate.sh — 微信管线强制执行门禁 v1.0
# 用法: bash pipeline-gate.sh {check|verify|status} {phase} {topic} {date}
# 每个阶段启动前必须先过门禁。不过门禁 = 管线拒绝执行。
# 这不是建议，是硬编码阻断。

# 门禁阈值来源:
# Phase 0/1: 基于历史产出文件大小分布的下限
# Phase 2: 基于 CLAUDE.md 定义的字数标准 (15000 汉字 × 3 bytes/char ≈ 45000 bytes)
# Phase 3: 同上
# 标题长度: 微信公众号显示约束 (短标题无辨识度，长标题被截断)

set -euo pipefail

TOPIC="${3:-}"
DATE="${4:-$(date +%Y-%m-%d)}"
RESEARCH_DIR="output/research"
ARTICLE_DIR="output/wechat_articles"
WECHAT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 确保输出目录存在
mkdir -p "$WECHAT_ROOT/$RESEARCH_DIR" "$WECHAT_ROOT/$ARTICLE_DIR/hot" "$WECHAT_ROOT/$ARTICLE_DIR/evergreen"

# === checkpoint 文件解析（用 find 匹配，容忍日期和标题差异） ===
resolve_checkpoint() {
    local key="$1"
    local found=""

    case "$key" in
        "0-competitor")
            found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_competitor-style_*.md" 2>/dev/null | sort -r | head -1)
            [ -z "$found" ] && found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_competitor-style_*.md" 2>/dev/null | head -1)
            ;;
        "1-brief")
            found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_brief_*.md" 2>/dev/null | sort -r | head -1)
            [ -z "$found" ] && found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_brief_*.md" 2>/dev/null | head -1)
            ;;
        "2-analysis")
            found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_analysis_*.md" 2>/dev/null | sort -r | head -1)
            [ -z "$found" ] && found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_analysis_*.md" 2>/dev/null | head -1)
            ;;
        "3-article")
            found=$(find "$WECHAT_ROOT/$ARTICLE_DIR" -maxdepth 3 -name "${TOPIC}_*.md" 2>/dev/null | sort -r | head -1)
            [ -z "$found" ] && found=$(find "$WECHAT_ROOT/$ARTICLE_DIR" -maxdepth 3 -name "*.md" -path "*20[0-9][0-9]*" 2>/dev/null | head -1)
            ;;
        "3.5-qa")
            found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "${TOPIC}_QA_*.md" 2>/dev/null | sort -r | head -1)
            [ -z "$found" ] && found=$(find "$WECHAT_ROOT/$RESEARCH_DIR" -maxdepth 1 -name "*_QA_*.md" 2>/dev/null | head -1)
            ;;
    esac
    echo "$found"
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

    case "$phase" in
        "0")
            f=$(resolve_checkpoint "0-competitor")
            [ -z "$f" ] && { echo "❌ competitor-style 文件缺失"; exit 3; }
            local size=$(wc -c < "$f")
            # 基于历史竞品文件最低 2859B，设置 2000B 为安全下限
            [ "$size" -lt 2000 ] && { echo "❌ < 2KB ($size bytes)"; exit 3; }
            grep -qE "维度1|维度2|维度3|维度4|维度5|五维" "$f" || { echo "❌ 五维不完整"; exit 3; }
            grep -qE "[0-9]+\s*/\s*10" "$f" || { echo "❌ 缺少竞对情感温度评估 (X/10)"; exit 3; }
            echo "✅ Phase 0 验证通过 (${size} bytes)"
            ;;
        "1")
            f=$(resolve_checkpoint "1-brief")
            [ -z "$f" ] && { echo "❌ brief 文件缺失"; exit 3; }
            local size=$(wc -c < "$f")
            # 基于历史简报最低 3215B，设置 1500B 为安全下限
            [ "$size" -lt 1500 ] && { echo "❌ < 1.5KB ($size bytes)"; exit 3; }
            echo "✅ Phase 1 验证通过 (${size} bytes)"
            ;;
        "2")
            f=$(resolve_checkpoint "2-analysis")
            [ -z "$f" ] && { echo "❌ analysis 文件缺失"; exit 3; }
            local size=$(wc -c < "$f")
            # 基于 CLAUDE.md 深度长文标准 (15000汉字 × 3 bytes/char ≈ 45000 bytes)
            [ "$size" -lt 45000 ] && { echo "❌ < 45KB ($size bytes, 不足 godtier 分析深度下限)"; exit 3; }
            local layers=$(grep -c "^## L" "$f" || true)
            [ "$layers" -lt 10 ] && { echo "❌ 仅${layers}层(需≥10)"; exit 3; }
            echo "✅ Phase 2 验证通过 (${size} bytes, ${layers}层)"
            ;;
        "3")
            f=$(resolve_checkpoint "3-article")
            [ -z "$f" ] && { echo "❌ 文章文件缺失"; exit 3; }
            local size=$(wc -c < "$f")
            # 基于 CLAUDE.md 深度长文标准: 15000汉字 × 3 bytes/char ≈ 45000 bytes
            [ "$size" -lt 45000 ] && { echo "❌ < 45KB (约15000汉字，未达 CLAUDE.md 深度长文下限)"; exit 3; }
            grep -q "SOUL+STYLE+PERSONA" "$f" || { echo "❌ 缺persona注入标记(metadata)；需在文章frontmatter中包含"; exit 3; }
            grep -qE "摘要:" "$f" || { echo "❌ 缺摘要(公众号显示必需)"; exit 3; }
            # 微信公众号显示约束: 短标题无辨识度，长标题被截断
            local title_len=$(head -1 "$f" | sed 's/^# //' | wc -m)
            [ "$title_len" -lt 8 ] && { echo "❌ 标题过短(<8字, 公众号列表页无辨识度)"; exit 3; }
            [ "$title_len" -gt 35 ] && echo "⚠️  标题过长(>35字, 公众号推送中被截断)"
            grep -qE "你只需要|只要我们还" "$f" && echo "⚠️  检测到可能反模式结尾"
            echo "✅ Phase 3 验证通过 (${size} bytes)"
            ;;
        "3.5")
            f=$(resolve_checkpoint "3.5-qa")
            [ -z "$f" ] && { echo "❌ QA报告缺失"; exit 3; }
            [ "$(grep -cE 'FALSIFIED:\s*0\b' "$f" || true)" -gt 0 ] 2>/dev/null || { echo "❌ QA未通过(有未修复FALSIFIED)"; exit 3; }
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
    echo "  微信管线状态"
    echo "═══════════════════════════════════════════════"
    echo ""
    local keys=("0-competitor:Phase 0 竞品蒸馏" "1-brief:Phase 1 研究简报" "2-analysis:Phase 2 godtier分析" "3-article:Phase 3 persona重写" "3.5-qa:Phase 3.5 QA门禁")
    for entry in "${keys[@]}"; do
        local key="${entry%%:*}"
        local label="${entry##*:}"
        f=$(resolve_checkpoint "$key")
        if [ -n "$f" ] && [ -s "$f" ]; then
            local size=$(wc -c < "$f" 2>/dev/null || echo 0)
            echo "  ✅ $label ($(echo $size | tr -d ' ')B)"
        else
            echo "  ⬜ $label"
        fi
    done
    echo ""
}

# === 主入口 ===

case "${1:-}" in
    "check")
        gate_check "${2:-}"
        ;;
    "verify")
        gate_verify "${2:-}"
        ;;
    "status")
        gate_status
        ;;
    *)
        echo "用法: pipeline-gate.sh {check|verify|status} {phase} {topic} {date}"
        echo ""
        echo "  check {phase}  — 检查前置 checkpoint，不通过则阻断"
        echo "  verify {phase} — 验证当前阶段产出质量"
        echo "  status         — 显示管线状态面板"
        echo ""
        echo "  阶段: 0(竞品) 1(选题) 2(godtier) 3(persona) 3.5(QA) 4(输出)"
        echo ""
        echo "  示例:"
        echo "    bash pipeline-gate.sh check 2 gaokao-major-choice 2026-06-24"
        echo "    bash pipeline-gate.sh verify 3 gaokao-major-choice 2026-06-24"
        echo "    bash pipeline-gate.sh status"
        exit 0
        ;;
esac
