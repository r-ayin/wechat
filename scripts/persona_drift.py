#!/usr/bin/env python3
"""
PD-02 跨文章 persona drift 检测 — 对多篇文章提取风格向量，检测风格漂移。

CLI:
    python persona_drift.py <dir_or_glob> [--json]

对给定目录/glob 的多篇文章，每篇提取 6 维风格向量（复用 style_fingerprint 的指标）：
  1. 句长比 3 维（短句/中句/长句占比）
  2. 括号密度
  3. 破折号密度
  4. 段落平均字数（归一化为以百字为单位）
  5. 设问频率

计算：
  - 各指标跨文章的均值 / 标准差 / 变异系数 CV
  - 离群文章（某指标偏离均值 > 2 sigma）

输出 JSON：
  {
    articles: [{slug, vector}],
    stats: {各指标 mean/std/cv},
    outliers: [{slug, metric, deviation}]
  }

CV > 0.3 的指标视为风格漂移信号。

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from pathlib import Path

# 项目根
_ROOT = Path(__file__).resolve().parent.parent

# 将 scripts 目录加入 sys.path，以便复用 style_fingerprint 的函数
sys.path.insert(0, str(_ROOT / "scripts"))

from style_fingerprint import (
    _strip_frontmatter,
    _count_chinese,
    _split_sentences,
    _sentence_length_distribution,
    _bracket_density,
    _dash_density,
    _avg_paragraph_chars,
    _question_sentence_ratio,
)

# =========================================================================
# 6 维风格向量的指标名称
# =========================================================================

_METRIC_NAMES = [
    "sentence_ratio_short",   # 短句占比
    "sentence_ratio_mid",     # 中句占比
    "sentence_ratio_long",    # 长句占比
    "bracket_density",        # 括号密度
    "dash_density",           # 破折号密度
    "avg_paragraph_chars",    # 段落平均字数
    "question_ratio",         # 设问频率
]

_METRIC_LABELS = {
    "sentence_ratio_short": "短句占比",
    "sentence_ratio_mid": "中句占比",
    "sentence_ratio_long": "长句占比",
    "bracket_density": "括号密度",
    "dash_density": "破折号密度",
    "avg_paragraph_chars": "段落平均字数",
    "question_ratio": "设问频率",
}


# =========================================================================
# 单篇文章风格向量提取
# =========================================================================

def extract_style_vector(file_path: Path) -> dict[str, float]:
    """从单篇 Markdown 文章提取 6 维风格向量。"""
    raw_text = file_path.read_text(encoding="utf-8")
    text = _strip_frontmatter(raw_text)

    cn_count = _count_chinese(text)
    sentences = _split_sentences(text)
    sent_dist = _sentence_length_distribution(sentences)

    return {
        "sentence_ratio_short": sent_dist["short"],
        "sentence_ratio_mid": sent_dist["mid"],
        "sentence_ratio_long": sent_dist["long"],
        "bracket_density": _bracket_density(text, cn_count),
        "dash_density": _dash_density(text, cn_count),
        "avg_paragraph_chars": _avg_paragraph_chars(text),
        "question_ratio": _question_sentence_ratio(sentences, text),
    }


# =========================================================================
# 统计计算
# =========================================================================

def _mean(values: list[float]) -> float:
    """计算均值。"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _std(values: list[float], mean_val: float) -> float:
    """计算总体标准差。"""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _cv(mean_val: float, std_val: float) -> float:
    """计算变异系数 CV = std / |mean|。"""
    if mean_val == 0.0:
        return 0.0 if std_val == 0.0 else float("inf")
    return std_val / abs(mean_val)


def compute_stats(articles: list[dict]) -> dict[str, dict[str, float]]:
    """对所有文章的风格向量，计算各指标的 mean / std / cv。"""
    stats: dict[str, dict[str, float]] = {}
    for metric in _METRIC_NAMES:
        values = [a["vector"][metric] for a in articles]
        m = _mean(values)
        s = _std(values, m)
        c = _cv(m, s)
        stats[metric] = {
            "mean": round(m, 6),
            "std": round(s, 6),
            "cv": round(c, 4),
        }
    return stats


def find_outliers(
    articles: list[dict],
    stats: dict[str, dict[str, float]],
) -> list[dict]:
    """找出离群文章：某指标偏离均值 > 2 sigma。"""
    outliers: list[dict] = []
    for article in articles:
        slug = article["slug"]
        vector = article["vector"]
        for metric in _METRIC_NAMES:
            mean_val = stats[metric]["mean"]
            std_val = stats[metric]["std"]
            if std_val == 0.0:
                continue  # 所有文章该指标相同，无离群
            deviation = abs(vector[metric] - mean_val) / std_val
            if deviation > 2.0:
                outliers.append({
                    "slug": slug,
                    "metric": metric,
                    "metric_label": _METRIC_LABELS.get(metric, metric),
                    "value": vector[metric],
                    "mean": stats[metric]["mean"],
                    "deviation_sigma": round(deviation, 2),
                })
    return outliers


# =========================================================================
# 文件收集
# =========================================================================

def collect_files(path_arg: str) -> list[Path]:
    """根据输入参数收集 Markdown 文件列表。
    支持：
      - 目录路径 → 递归收集 *.md 文件
      - glob 模式 → 展开匹配
      - 单文件路径 → 直接使用
    """
    p = Path(path_arg)
    if p.is_dir():
        # 目录：递归收集所有 .md 文件
        files = sorted(p.rglob("*.md"))
    elif p.is_file():
        files = [p]
    else:
        # 尝试作为 glob 模式
        files = sorted(Path(f) for f in glob.glob(path_arg, recursive=True))
    # 过滤：只保留存在的 .md 文件
    return [f for f in files if f.is_file() and f.suffix.lower() == ".md"]


# =========================================================================
# 主函数
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PD-02 跨文章 persona drift 检测 — 多篇文章风格漂移分析"
    )
    parser.add_argument(
        "path",
        help="目录路径或 glob 模式，指向待分析的 Markdown 文章",
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="以 JSON 格式输出（默认即为 JSON）",
    )
    args = parser.parse_args()

    # 收集文件
    files = collect_files(args.path)
    if not files:
        result = {
            "error": f"未找到 Markdown 文件: {args.path}",
            "articles": [],
            "stats": {},
            "outliers": [],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 逐篇提取风格向量
    articles: list[dict] = []
    for f in files:
        slug = f.stem  # 文件名（不含扩展名）作为 slug
        try:
            vector = extract_style_vector(f)
            articles.append({"slug": slug, "vector": vector})
        except Exception as e:
            # 跳过读取失败的文件，记录错误
            articles.append({
                "slug": slug,
                "vector": {m: 0.0 for m in _METRIC_NAMES},
                "error": str(e),
            })

    # 计算跨文章统计
    stats = compute_stats(articles)

    # 检测离群文章
    outliers = find_outliers(articles, stats)

    # 识别风格漂移信号（CV > 0.3）
    drift_signals: list[str] = []
    for metric, s in stats.items():
        if s["cv"] > 0.3:
            drift_signals.append(
                f"{_METRIC_LABELS.get(metric, metric)}: CV={s['cv']}"
            )

    # 构建输出
    result = {
        "articles": articles,
        "stats": stats,
        "outliers": outliers,
        "drift_signals": drift_signals,
        "summary": {
            "total_articles": len(articles),
            "outlier_count": len(outliers),
            "drifting_metrics": len(drift_signals),
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
