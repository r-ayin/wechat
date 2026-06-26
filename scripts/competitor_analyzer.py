#!/usr/bin/env python3
"""competitor_analyzer.py — P0-OPT-02 竞品结构 NLP 分析

对单篇竞品文章做确定性指标计算，输出五维 JSON：
  - structure:         总字数 / 段落数 / 各段字数 / 小标题数
  - sentence_length:   短中长比例 + 平均句长
  - evidence_density:  数字 / 人物 / 事件 / 引用 密度（每千字）
  - url_density:       URL 计数 / 千字
  - analyzed_at:       分析时间戳

证据密度复用 script-verifier/claim_extractor.py 的四类提取函数。

用法：
  python competitor_analyzer.py <competitor_article.md> [--json]

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 项目根 & 引入 claim_extractor
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "script-verifier"))

from claim_extractor import (  # noqa: E402
    extract_data_claims,
    extract_person_claims,
    extract_event_claims,
    extract_quote_claims,
)


# ---------------------------------------------------------------------------
# 1. 结构分析
# ---------------------------------------------------------------------------

def _analyze_structure(text: str) -> dict:
    """总字数 / 段落数（空行分段）/ 各段字数分布 / 小标题数（以 # 或数字开头）"""
    # 总字数（去除空白后的字符数）
    total_chars = len(re.sub(r'\s', '', text))

    # 段落：以空行分隔（连续两个换行）
    raw_paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]
    paragraph_count = len(paragraphs)

    # 各段字数（去除空白）
    paragraph_char_counts = [len(re.sub(r'\s', '', p)) for p in paragraphs]

    # 小标题检测：以 # 开头 或 以 数字/数字. 开头的行
    heading_re = re.compile(r'^\s*(?:#{1,6}\s|(?:\d+[\.\、）\)])\s)', re.MULTILINE)
    heading_count = len(heading_re.findall(text))

    return {
        "total_chars": total_chars,
        "paragraph_count": paragraph_count,
        "paragraph_char_counts": paragraph_char_counts,
        "heading_count": heading_count,
    }


# ---------------------------------------------------------------------------
# 2. 句长分布
# ---------------------------------------------------------------------------

# 切句：中文句号、问号、感叹号、省略号以及英文对应标点
_SENTENCE_SPLIT_RE = re.compile(r'[。！？!?……]+')


def _split_sentences(text: str) -> list[str]:
    """将全文切分为句子列表（过滤空句子）。

    切句规则：按中文标点「。！？」和英文「! ?」以及省略号分割。
    """
    parts = _SENTENCE_SPLIT_RE.split(text)
    sentences = []
    for s in parts:
        # 去除空白和换行
        cleaned = re.sub(r'\s+', '', s).strip()
        if cleaned:
            sentences.append(cleaned)
    return sentences


def _analyze_sentence_length(text: str) -> dict:
    """句长分布：短(<=15) / 中(16-40) / 长(>40) 比例 + 平均句长"""
    sentences = _split_sentences(text)
    if not sentences:
        return {
            "sentence_count": 0,
            "avg_length": 0.0,
            "short_ratio": 0.0,
            "medium_ratio": 0.0,
            "long_ratio": 0.0,
            "short_count": 0,
            "medium_count": 0,
            "long_count": 0,
        }

    lengths = [len(s) for s in sentences]
    total = len(lengths)
    avg = sum(lengths) / total

    short = sum(1 for l in lengths if l <= 15)
    medium = sum(1 for l in lengths if 16 <= l <= 40)
    long_ = sum(1 for l in lengths if l > 40)

    return {
        "sentence_count": total,
        "avg_length": round(avg, 1),
        "short_ratio": round(short / total, 3),
        "medium_ratio": round(medium / total, 3),
        "long_ratio": round(long_ / total, 3),
        "short_count": short,
        "medium_count": medium,
        "long_count": long_,
    }


# ---------------------------------------------------------------------------
# 3. 证据密度（复用 claim_extractor）
# ---------------------------------------------------------------------------

def _analyze_evidence_density(text: str) -> dict:
    """每千字：数字密度 / 人物密度 / 事件密度 / 引用密度"""
    total_chars = len(re.sub(r'\s', '', text))
    if total_chars == 0:
        return {
            "data_density_per_1k": 0.0,
            "person_density_per_1k": 0.0,
            "event_density_per_1k": 0.0,
            "quote_density_per_1k": 0.0,
            "data_count": 0,
            "person_count": 0,
            "event_count": 0,
            "quote_count": 0,
        }

    kilo = total_chars / 1000.0

    data_claims = extract_data_claims(text)
    person_claims = extract_person_claims(text)
    event_claims = extract_event_claims(text)
    quote_claims = extract_quote_claims(text)

    return {
        "data_density_per_1k": round(len(data_claims) / kilo, 2),
        "person_density_per_1k": round(len(person_claims) / kilo, 2),
        "event_density_per_1k": round(len(event_claims) / kilo, 2),
        "quote_density_per_1k": round(len(quote_claims) / kilo, 2),
        "data_count": len(data_claims),
        "person_count": len(person_claims),
        "event_count": len(event_claims),
        "quote_count": len(quote_claims),
    }


# ---------------------------------------------------------------------------
# 4. URL 密度
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r'https?://')


def _analyze_url_density(text: str) -> dict:
    """URL 计数 / 千字"""
    total_chars = len(re.sub(r'\s', '', text))
    url_count = len(_URL_RE.findall(text))

    if total_chars == 0:
        return {"url_count": 0, "url_density_per_1k": 0.0}

    kilo = total_chars / 1000.0
    return {
        "url_count": url_count,
        "url_density_per_1k": round(url_count / kilo, 2),
    }


# ---------------------------------------------------------------------------
# 主编排
# ---------------------------------------------------------------------------

def analyze(text: str) -> dict:
    """对竞品文章全文做五维分析，返回 JSON-ready dict"""
    return {
        "structure": _analyze_structure(text),
        "sentence_length": _analyze_sentence_length(text),
        "evidence_density": _analyze_evidence_density(text),
        "url_density": _analyze_url_density(text),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="P0-OPT-02 竞品结构 NLP 分析 — 对单篇竞品文章计算确定性指标",
    )
    parser.add_argument(
        "article",
        help="竞品文章 Markdown 文件路径",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="输出纯 JSON（默认也是 JSON）",
    )
    args = parser.parse_args()

    article_path = Path(args.article)
    if not article_path.exists():
        print(f"错误：文件不存在 — {article_path}", file=sys.stderr)
        sys.exit(1)

    text = article_path.read_text(encoding="utf-8")
    result = analyze(text)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
