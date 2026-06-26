#!/usr/bin/env python3
"""title_scorer.py — W-04 标题候选评分器

对 Phase 3 子 agent 产出的候选标题进行多维度打分（0-100），
按分数降序输出 JSON，供管线择优选定最终标题。

评分维度：
  - 长度适宜度：8-20 字满分，<8 或 >35 扣分
  - 句式模板识别（加分）：不是A是B / 冒号二元对照 / 引号反讽 /
    身份词前置 / 数字悬念 / 问句
  - 信息密度：含具体数字 / 专有名词加分
  - 反模式扣分：含"你只需要/勇敢一点/治愈/正能量"等鸡汤词

CLI:
  python title_scorer.py --titles '["标题1","标题2",...]' [--json]

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 项目根 = scripts/ 的父目录
_ROOT = Path(__file__).resolve().parent.parent


# =========================================================================
# 评分参数
# =========================================================================

# 长度评分：8-20 字满分区间
_LEN_PERFECT_MIN = 8
_LEN_PERFECT_MAX = 20
_LEN_PENALTY_SHORT = 5   # <5 字严重扣分
_LEN_PENALTY_LONG = 35   # >35 字严重扣分

# 句式模板：名称 → 正则
_TEMPLATES: dict[str, re.Pattern[str]] = {
    "不是A是B": re.compile(r"不是.+[是而].+"),
    "冒号二元对照": re.compile(r".+[：:].+"),
    "引号反讽": re.compile(r"[「「\"""''].+[」」\"""'']"),
    "身份词前置": re.compile(
        r"^(?:我们|那些|一个|每个|所有|中国|当代|年轻|普通|底层|打工)"
    ),
    "数字悬念": re.compile(r"\d+"),
    "问句": re.compile(r"[？?]$"),
}

# 每命中一个模板加分
_TEMPLATE_BONUS = 5

# 信息密度加分
_INFO_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("含具体数字", re.compile(r"\d+(?:[%％万亿千百]|元|年|天|小时|岁)"), 5),
    ("含专有名词", re.compile(
        r"(?:GDP|AI|ChatGPT|OpenAI|互联网|算法|大模型|资本|华尔街"
        r"|美联储|社保|医保|公积金|996|35岁|内卷|躺平)"
    ), 5),
]

# 反模式关键词：命中一个扣分
_ANTI_PATTERNS: list[tuple[str, re.Pattern[str], int]] = [
    ("鸡汤词:你只需要", re.compile(r"你只需要"), -15),
    ("鸡汤词:勇敢一点", re.compile(r"勇敢一点"), -15),
    ("鸡汤词:治愈", re.compile(r"治愈"), -10),
    ("鸡汤词:正能量", re.compile(r"正能量"), -10),
    ("鸡汤词:加油", re.compile(r"加油"), -8),
    ("鸡汤词:相信自己", re.compile(r"相信自己"), -10),
    ("鸡汤词:努力就会", re.compile(r"努力就会"), -10),
    ("鸡汤词:坚持就是", re.compile(r"坚持就是"), -8),
    ("鸡汤词:温暖", re.compile(r"温暖"), -5),
    ("鸡汤词:美好", re.compile(r"美好"), -5),
]


# =========================================================================
# 评分函数
# =========================================================================

def _score_length(title: str) -> tuple[int, list[str]]:
    """长度维度评分，返回 (分数增减, 问题列表)。"""
    n = len(title)
    issues: list[str] = []

    if _LEN_PERFECT_MIN <= n <= _LEN_PERFECT_MAX:
        return 30, issues  # 满分 30

    if n < _LEN_PENALTY_SHORT:
        issues.append(f"标题过短({n}字，建议>=8字)")
        return 5, issues
    elif n < _LEN_PERFECT_MIN:
        issues.append(f"标题偏短({n}字，最佳8-20字)")
        return 20, issues
    elif n <= _LEN_PENALTY_LONG:
        # 20-35 字：逐渐衰减
        penalty = (n - _LEN_PERFECT_MAX) * 1
        issues.append(f"标题偏长({n}字，最佳8-20字)")
        return max(30 - penalty, 10), issues
    else:
        issues.append(f"标题过长({n}字，建议<=35字)")
        return 5, issues


def _score_templates(title: str) -> tuple[int, list[str]]:
    """句式模板识别，返回 (加分, 命中的模板名列表)。"""
    matched: list[str] = []
    for name, pattern in _TEMPLATES.items():
        if pattern.search(title):
            matched.append(name)

    bonus = min(len(matched) * _TEMPLATE_BONUS, 20)  # 上限 20
    return bonus, matched


def _score_info_density(title: str) -> tuple[int, list[str]]:
    """信息密度加分，返回 (加分, 命中描述列表)。"""
    total = 0
    matched: list[str] = []
    for desc, pattern, bonus in _INFO_PATTERNS:
        if pattern.search(title):
            total += bonus
            matched.append(desc)
    return min(total, 10), matched  # 上限 10


def _score_anti_patterns(title: str) -> tuple[int, list[str]]:
    """反模式扣分，返回 (扣分（负数）, 问题描述列表)。"""
    total = 0
    issues: list[str] = []
    for desc, pattern, penalty in _ANTI_PATTERNS:
        if pattern.search(title):
            total += penalty
            issues.append(desc)
    return total, issues


def score_title(title: str) -> dict:
    """对单个标题进行综合评分。

    返回:
        {
            "title": str,
            "score": int (0-100),
            "templates": [...],   # 命中的句式模板
            "issues": [...]       # 扣分原因
        }
    """
    # 基础分 40
    base = 40

    len_score, len_issues = _score_length(title)
    tmpl_score, tmpl_names = _score_templates(title)
    info_score, info_descs = _score_info_density(title)
    anti_score, anti_issues = _score_anti_patterns(title)

    total = base + len_score + tmpl_score + info_score + anti_score

    # 把信息密度命中也记到 templates 中便于查看
    all_templates = tmpl_names + info_descs

    # 汇总问题
    all_issues = len_issues + anti_issues

    # 钳制到 0-100
    total = max(0, min(100, total))

    return {
        "title": title,
        "score": total,
        "templates": all_templates,
        "issues": all_issues,
    }


# =========================================================================
# CLI 入口
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="W-04 标题候选评分器：对候选标题多维度打分（0-100），按分降序输出。"
    )
    parser.add_argument(
        "--titles",
        required=True,
        help='候选标题 JSON 数组，如 \'["标题1","标题2"]\'',
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="输出 JSON 格式（默认开启）",
    )

    args = parser.parse_args()

    # 解析标题列表
    try:
        titles = json.loads(args.titles)
    except json.JSONDecodeError as e:
        print(f"错误：无法解析 --titles 参数为 JSON 数组: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(titles, list):
        print("错误：--titles 必须是 JSON 数组", file=sys.stderr)
        sys.exit(1)

    # 逐个评分
    results = [score_title(t) for t in titles]

    # 按分数降序排序
    results.sort(key=lambda r: r["score"], reverse=True)

    # 输出
    print(json.dumps(results, ensure_ascii=False, indent=2))

    sys.exit(0)


if __name__ == "__main__":
    main()
