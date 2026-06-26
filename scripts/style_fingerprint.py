#!/usr/bin/env python3
"""
W-02 风格一致性量化检测 — 对文章正文计算风格指纹，与基线对比。

CLI:
    python style_fingerprint.py <article.md> [--baseline persona/STYLE.md] [--json]

指标：
  1. 句长分布（短<15 / 中15-40 / 长>40）
  2. 括号密度
  3. 破折号密度
  4. 段落平均字数
  5. 设问句频率
  6. 平淡段检测（连续3句以上无括号/破折号/设问）

退出码：0=通过, 2=告警(soft), 1=阻断(hard)
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

# 项目根
_ROOT = Path(__file__).resolve().parent.parent

# =========================================================================
# 硬编码默认基线（来自 STYLE.md 96篇文章统计）
# =========================================================================
DEFAULT_BASELINE = {
    "sentence_ratio_short": 0.222,   # 短句占比（<15字）
    "sentence_ratio_mid": 0.383,     # 中句占比（15-40字）
    "sentence_ratio_long": 0.395,    # 长句占比（>40字）
    "bracket_density": 0.012,        # 括号密度（括号总数/汉字数）
    "dash_density": 0.0017,          # 破折号密度（破折号总数/汉字数）
    "avg_paragraph_chars": 272,      # 段落平均字数
}

# 阻断级指标（偏离>80%直接 block）
_BLOCK_METRICS = {"sentence_ratio_short", "sentence_ratio_mid", "sentence_ratio_long",
                  "bracket_density", "dash_density"}


# =========================================================================
# 文本预处理
# =========================================================================

def _strip_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter（--- ... ---）和首行标题（# 开头）。"""
    # 去掉 YAML frontmatter
    text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.DOTALL)
    # 去掉首行标题行（# 开头，可能有多个 #）
    lines = text.split('\n')
    cleaned: list[str] = []
    title_stripped = False
    for line in lines:
        if not title_stripped and re.match(r'^#{1,6}\s+', line):
            title_stripped = True
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def _count_chinese(text: str) -> int:
    """统计汉字数量。"""
    return len(re.findall(r'[一-鿿]', text))


# =========================================================================
# 切句
# =========================================================================

def _split_sentences(text: str) -> list[str]:
    """按 [。！？] 切句，返回非空句子列表。"""
    parts = re.split(r'[。！？]', text)
    return [s.strip() for s in parts if s.strip()]


# =========================================================================
# 指标计算
# =========================================================================

def _sentence_length_distribution(sentences: list[str]) -> dict[str, float]:
    """计算短/中/长句比例。按汉字数分类。"""
    if not sentences:
        return {"short": 0.0, "mid": 0.0, "long": 0.0}

    short = mid = long_ = 0
    for s in sentences:
        cn = _count_chinese(s)
        if cn < 15:
            short += 1
        elif cn <= 40:
            mid += 1
        else:
            long_ += 1

    total = len(sentences)
    return {
        "short": round(short / total, 4),
        "mid": round(mid / total, 4),
        "long": round(long_ / total, 4),
    }


def _bracket_density(text: str, cn_count: int) -> float:
    """括号密度：()（）[]【】总数 / 汉字数。"""
    if cn_count == 0:
        return 0.0
    bracket_count = len(re.findall(r'[()（）\[\]【】]', text))
    return round(bracket_count / cn_count, 6)


def _dash_density(text: str, cn_count: int) -> float:
    """破折号密度：——/—/- 总数 / 汉字数。先匹配 ——，再匹配单独 —，再匹配 -。"""
    if cn_count == 0:
        return 0.0
    # 统计破折号总数：—— 算1个，单独 — 算1个，- 算1个
    count = 0
    count += len(re.findall(r'——', text))
    # 去掉 —— 后统计单独的 —
    text_no_double = re.sub(r'——', '', text)
    count += len(re.findall(r'—', text_no_double))
    # 统计半角破折号 -（排除 frontmatter 的 ---、列表标记等场景，只统计汉字间的 -）
    count += len(re.findall(r'(?<=[一-鿿])-(?=[一-鿿])', text_no_double))
    return round(count / cn_count, 6)


def _avg_paragraph_chars(text: str) -> float:
    """段落平均字数（按汉字计）。段落以空行分隔。"""
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if not paragraphs:
        return 0.0
    total_cn = sum(_count_chinese(p) for p in paragraphs)
    return round(total_cn / len(paragraphs), 1)


def _question_sentence_ratio(sentences: list[str], text: str) -> float:
    """设问句频率：以？结尾句子占比。
    因为切句是按 [。！？] 切的，？结尾的句子不会直接保留？号。
    所以改为在原文中按？切句后统计。
    """
    if not sentences:
        return 0.0
    # 统计原文中以？结尾的句子数
    question_count = len(re.findall(r'[？?]', text))
    total_endings = len(re.findall(r'[。！？!?.]', text))
    if total_endings == 0:
        return 0.0
    return round(question_count / total_endings, 4)


def _detect_bland_paragraphs(text: str) -> list[dict]:
    """平淡段检测：连续3句以上无括号/破折号/设问的段落。"""
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    bland_list: list[dict] = []
    for i, para in enumerate(paragraphs):
        sentences = _split_sentences(para)
        if len(sentences) < 3:
            continue
        # 检查是否连续3句以上无括号/破折号/设问
        consecutive_bland = 0
        max_consecutive = 0
        for s in sentences:
            has_bracket = bool(re.search(r'[()（）\[\]【】]', s))
            has_dash = bool(re.search(r'[——\-—]', s))
            has_question = bool(re.search(r'[？?]', s))
            if not has_bracket and not has_dash and not has_question:
                consecutive_bland += 1
                max_consecutive = max(max_consecutive, consecutive_bland)
            else:
                consecutive_bland = 0
        if max_consecutive >= 3:
            bland_list.append({
                "paragraph_index": i,
                "consecutive_bland_sentences": max_consecutive,
                "preview": para[:80] + ("..." if len(para) > 80 else ""),
            })

    return bland_list


# =========================================================================
# 基线解析
# =========================================================================

def _parse_baseline_from_style(style_path: str) -> dict[str, float]:
    """从 STYLE.md 解析基线数值。"""
    text = Path(style_path).read_text(encoding="utf-8")
    baseline = dict(DEFAULT_BASELINE)

    # 句长比例：匹配 "1922/8673 : 3321/8673 : 3430/8673" 样式
    m = re.search(r'句长比.*?(\d+)/(\d+)\s*:\s*(\d+)/(\d+)\s*:\s*(\d+)/(\d+)', text)
    if m:
        short_n, short_t = int(m.group(1)), int(m.group(2))
        mid_n, mid_t = int(m.group(3)), int(m.group(4))
        long_n, long_t = int(m.group(5)), int(m.group(6))
        baseline["sentence_ratio_short"] = round(short_n / short_t, 4) if short_t else 0
        baseline["sentence_ratio_mid"] = round(mid_n / mid_t, 4) if mid_t else 0
        baseline["sentence_ratio_long"] = round(long_n / long_t, 4) if long_t else 0

    # 段落平均长度
    m = re.search(r'平均段落长度.*?(\d+)\s*字', text)
    if m:
        baseline["avg_paragraph_chars"] = float(m.group(1))

    # 括号密度：从括号总数和句数推算（4200括号 / 8673句 × 平均句长约40字 ≈ 0.012）
    m_bracket = re.search(r'括号.*?(\d+)', text)
    m_sentences = re.search(r'分析句数.*?(\d+)', text)
    if m_bracket and m_sentences:
        bracket_count = int(m_bracket.group(1))
        sentence_count = int(m_sentences.group(1))
        # 从96篇文章的统计中估算总汉字数（句数×平均句长）
        # 使用句长分布加权：短句~8字，中句~27字，长句~55字
        estimated_cn = (
            baseline["sentence_ratio_short"] * 8
            + baseline["sentence_ratio_mid"] * 27
            + baseline["sentence_ratio_long"] * 55
        ) * sentence_count
        if estimated_cn > 0:
            baseline["bracket_density"] = round(bracket_count / estimated_cn, 6)

    # 破折号密度
    m_dash = re.search(r'破折号.*?(\d+)', text)
    if m_dash and m_sentences:
        dash_count = int(m_dash.group(1))
        sentence_count = int(m_sentences.group(1))
        estimated_cn = (
            baseline["sentence_ratio_short"] * 8
            + baseline["sentence_ratio_mid"] * 27
            + baseline["sentence_ratio_long"] * 55
        ) * sentence_count
        if estimated_cn > 0:
            baseline["dash_density"] = round(dash_count / estimated_cn, 6)

    return baseline


# =========================================================================
# 偏离计算与判定
# =========================================================================

def _compute_deviation(value: float, baseline_val: float) -> float:
    """计算偏离百分比（绝对值）。基线为0时特殊处理。"""
    if baseline_val == 0:
        return 100.0 if value != 0 else 0.0
    return round(abs(value - baseline_val) / baseline_val * 100, 1)


def _judge(metrics: dict, baseline: dict) -> tuple[str, list[str]]:
    """
    判定逻辑：
    - 任一指标偏离>50% → issues 加一项
    - 偏离>80% 且为句长/括号/破折号 → block
    - 30-80% → warn
    - 否则 pass
    """
    issues: list[str] = []
    has_block = False
    has_warn = False

    metric_names = {
        "sentence_ratio_short": "短句占比",
        "sentence_ratio_mid": "中句占比",
        "sentence_ratio_long": "长句占比",
        "bracket_density": "括号密度",
        "dash_density": "破折号密度",
        "avg_paragraph_chars": "段落平均字数",
    }

    deviations: dict[str, float] = {}

    for key in baseline:
        if key not in metrics:
            continue
        dev = _compute_deviation(metrics[key], baseline[key])
        deviations[key] = dev
        name = metric_names.get(key, key)

        if dev > 80 and key in _BLOCK_METRICS:
            has_block = True
            issues.append(f"[BLOCK] {name}: 偏离基线 {dev}%（值={metrics[key]}, 基线={baseline[key]}）")
        elif dev > 50:
            has_warn = True
            issues.append(f"[WARN] {name}: 偏离基线 {dev}%（值={metrics[key]}, 基线={baseline[key]}）")
        elif dev > 30:
            has_warn = True
            issues.append(f"[WARN] {name}: 偏离基线 {dev}%（值={metrics[key]}, 基线={baseline[key]}）")

    if has_block:
        verdict = "block"
    elif has_warn:
        verdict = "warn"
    else:
        verdict = "pass"

    return verdict, issues, deviations  # type: ignore[return-value]


# =========================================================================
# 主函数
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="W-02 风格一致性量化检测 — 计算文章风格指纹并与基线对比"
    )
    parser.add_argument("article", help="待检测的文章 Markdown 文件路径")
    parser.add_argument("--baseline", default=None,
                        help="基线文件路径（persona/STYLE.md），不提供则使用硬编码默认值")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="以 JSON 格式输出结果")
    args = parser.parse_args()

    # 读取文章
    article_path = Path(args.article)
    if not article_path.exists():
        print(f"错误：文件不存在 {article_path}", file=sys.stderr)
        sys.exit(1)
    raw_text = article_path.read_text(encoding="utf-8")

    # 预处理：去掉 frontmatter 和标题行
    text = _strip_frontmatter(raw_text)

    # 基线
    if args.baseline:
        baseline = _parse_baseline_from_style(args.baseline)
    else:
        baseline = dict(DEFAULT_BASELINE)

    # 计算指标
    cn_count = _count_chinese(text)
    sentences = _split_sentences(text)

    sent_dist = _sentence_length_distribution(sentences)
    b_density = _bracket_density(text, cn_count)
    d_density = _dash_density(text, cn_count)
    avg_para = _avg_paragraph_chars(text)
    q_ratio = _question_sentence_ratio(sentences, text)
    bland_paras = _detect_bland_paragraphs(text)

    metrics = {
        "sentence_ratio_short": sent_dist["short"],
        "sentence_ratio_mid": sent_dist["mid"],
        "sentence_ratio_long": sent_dist["long"],
        "bracket_density": b_density,
        "dash_density": d_density,
        "avg_paragraph_chars": avg_para,
        "question_sentence_ratio": q_ratio,
        "bland_paragraph_count": len(bland_paras),
        "total_sentences": len(sentences),
        "total_chinese_chars": cn_count,
    }

    # 判定
    verdict, issues, deviations = _judge(metrics, baseline)

    # 平淡段信息加入 issues
    if bland_paras:
        issues.append(f"[INFO] 检测到 {len(bland_paras)} 个平淡段（连续3句+无括号/破折号/设问）")

    result = {
        "metrics": metrics,
        "baseline": baseline,
        "deviations": deviations,
        "verdict": verdict,
        "issues": issues,
        "bland_paragraphs": bland_paras,
    }

    # 输出
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 退出码
    if verdict == "block":
        sys.exit(1)
    elif verdict == "warn":
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
