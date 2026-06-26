#!/usr/bin/env python3
"""ending_detector.py — W-06 弱结尾/反模式结尾检测器

取文章最后 500 字作为结尾段，检测三类反模式：
  1. 短语命中 — 15+ 个已知鸡汤/虚假正能量短语
  2. 结构性矛盾 — 全文论点为结构性批判，结尾却给出个体方案
  3. 简单答案 — 用反问铺垫后给出"秘诀就是/答案就是"式伪深刻

CLI:
  python ending_detector.py <article.md> [--json]

退出码：
  0 — pass（无反模式）
  2 — warn（命中 1 个反模式，soft 告警）
  1 — block（命中 ≥2 或存在结构性矛盾，hard 阻断）
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
# 反模式短语表（≥15 个）
# =========================================================================
_ANTI_PATTERN_PHRASES: list[str] = [
    "你只需要",
    "只要我们还",
    "勇敢一点",
    "算清楚",
    "治愈",
    "正能量",
    "客观",
    "正常",
    "depend yourself",
    "加油",
    "坚持",
    "相信",
    "努力就",
    "调整心态",
    "改变自己",
    "从自己做起",
]

# 个体方案词 — 用于结构性矛盾检测
_INDIVIDUAL_SOLUTION_WORDS: list[str] = [
    "勇敢",
    "努力",
    "调整心态",
    "改变自己",
]

# 结构性论点关键词 — 扫描前 30% 文本
_STRUCTURAL_KEYWORDS: list[str] = [
    "制度",
    "结构",
    "系统",
    "资本",
    "阶层",
    "政策",
]

# 简单答案正则 — 结尾含"？...答案就是/其实只需/秘诀就是"
_SIMPLE_ANSWER_RE = re.compile(
    r"？"           # 以中文问号起始
    r"[^？]{0,100}"  # 中间最多 100 字（不含另一个问号）
    r"(?:答案就是|其实只需|秘诀就是)"
)


def _read_article(path: Path) -> str:
    """读取文章全文，返回纯文本字符串。"""
    return path.read_text(encoding="utf-8")


def _get_ending(text: str, char_count: int = 500) -> str:
    """取文章最后 char_count 个字符作为结尾段。"""
    return text[-char_count:] if len(text) > char_count else text


def _detect_anti_pattern_phrases(ending: str) -> list[str]:
    """在结尾段中检测反模式短语，返回命中列表。"""
    hits: list[str] = []
    ending_lower = ending.lower()  # 英文短语忽略大小写
    for phrase in _ANTI_PATTERN_PHRASES:
        if phrase.lower() in ending_lower:
            hits.append(phrase)
    return hits


def _detect_structural_contradiction(full_text: str, ending: str) -> bool:
    """检测"结构问题→个体方案"矛盾。

    条件：
      - 结尾包含至少一个个体方案词
      - 全文前 30% 包含至少一个结构性关键词
    两者同时满足则判定矛盾。
    """
    # 检查结尾是否含个体方案词
    has_individual = any(w in ending for w in _INDIVIDUAL_SOLUTION_WORDS)
    if not has_individual:
        return False

    # 扫描前 30% 文本
    cutoff = max(1, len(full_text) * 30 // 100)
    front = full_text[:cutoff]
    has_structural = any(kw in front for kw in _STRUCTURAL_KEYWORDS)
    return has_structural


def _detect_simple_answer(ending: str) -> bool:
    """检测简单答案模式：结尾含"？...答案就是/其实只需/秘诀就是"。"""
    return bool(_SIMPLE_ANSWER_RE.search(ending))


def analyze(article_path: Path) -> dict:
    """对文章执行全部结尾检测，返回结果字典。"""
    full_text = _read_article(article_path)
    ending = _get_ending(full_text)

    # 三类检测
    anti_patterns = _detect_anti_pattern_phrases(ending)
    structural_contradiction = _detect_structural_contradiction(full_text, ending)
    simple_answer = _detect_simple_answer(ending)

    # 判定 verdict
    # 反模式命中 ≥2 或矛盾 → block
    # 命中 1 → warn
    # 无 → pass
    total_issues = len(anti_patterns) + (1 if simple_answer else 0)
    if total_issues >= 2 or structural_contradiction:
        verdict = "block"
    elif total_issues == 1:
        verdict = "warn"
    else:
        verdict = "pass"

    return {
        "ending_snippet": ending,
        "anti_patterns": anti_patterns,
        "structural_contradiction": structural_contradiction,
        "simple_answer": simple_answer,
        "verdict": verdict,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="W-06 弱结尾/反模式结尾检测器"
    )
    parser.add_argument(
        "article",
        type=str,
        help="待检测的文章 Markdown 文件路径",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="输出 JSON 格式结果（默认即 JSON）",
    )
    args = parser.parse_args()

    article_path = Path(args.article).resolve()
    if not article_path.exists():
        print(f"错误: 文件不存在 — {article_path}", file=sys.stderr)
        sys.exit(1)

    result = analyze(article_path)

    # 输出 JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 退出码：pass→0, warn→2, block→1
    if result["verdict"] == "block":
        sys.exit(1)
    elif result["verdict"] == "warn":
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
