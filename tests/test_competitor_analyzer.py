#!/usr/bin/env python3
"""competitor_analyzer.py 单测 — 覆盖结构分析/句长分布/URL密度/证据密度/主编排。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "script-verifier"))

from competitor_analyzer import (
    _analyze_structure,
    _split_sentences,
    _analyze_sentence_length,
    _analyze_url_density,
    _analyze_evidence_density,
    analyze,
)

import pytest


# ── _analyze_structure ───────────────────────────────────────


class TestAnalyzeStructure:
    def test_empty(self):
        r = _analyze_structure("")
        assert r["total_chars"] == 0
        assert r["paragraph_count"] == 0
        assert r["paragraph_char_counts"] == []
        assert r["heading_count"] == 0

    def test_single_paragraph(self):
        r = _analyze_structure("这是一段话，没有空行分隔。")
        assert r["total_chars"] == 13
        assert r["paragraph_count"] == 1
        assert r["paragraph_char_counts"] == [13]

    def test_multiple_paragraphs(self):
        text = "第一段内容。\n\n第二段内容。\n\n第三段。"
        r = _analyze_structure(text)
        assert r["paragraph_count"] == 3
        assert len(r["paragraph_char_counts"]) == 3

    def test_heading_hash(self):
        text = "# 标题一\n\n正文\n\n## 标题二\n\n正文"
        r = _analyze_structure(text)
        assert r["heading_count"] == 2

    def test_heading_numbered(self):
        text = "1. 第一章\n2. 第二章\n3、 第三章\n4） 第四章"
        r = _analyze_structure(text)
        assert r["heading_count"] == 4

    def test_chars_exclude_whitespace(self):
        text = "a b c\n d"
        r = _analyze_structure(text)
        assert r["total_chars"] == 4


# ── _split_sentences ─────────────────────────────────────────


class TestSplitSentences:
    def test_chinese_period(self):
        sents = _split_sentences("第一句。第二句。")
        assert len(sents) == 2

    def test_mixed_punctuation(self):
        sents = _split_sentences("你好！怎么了？没事。")
        assert len(sents) == 3

    def test_english_punctuation(self):
        sents = _split_sentences("Hello! How are you? Fine.")
        assert len(sents) == 3

    def test_empty(self):
        assert _split_sentences("") == []

    def test_ellipsis(self):
        sents = _split_sentences("真的吗……是的。")
        assert len(sents) == 2

    def test_whitespace_only(self):
        assert _split_sentences("   \n\n  ") == []


# ── _analyze_sentence_length ─────────────────────────────────


class TestAnalyzeSentenceLength:
    def test_empty(self):
        r = _analyze_sentence_length("")
        assert r["sentence_count"] == 0
        assert r["avg_length"] == 0.0

    def test_all_short(self):
        text = "短句。很短。也短。"
        r = _analyze_sentence_length(text)
        assert r["sentence_count"] == 3
        assert r["short_count"] == 3
        assert r["short_ratio"] == 1.0
        assert r["medium_count"] == 0
        assert r["long_count"] == 0

    def test_medium_sentence(self):
        text = "这是一个中等长度的句子大约有二十个字左右吧。"
        r = _analyze_sentence_length(text)
        assert r["sentence_count"] == 1
        assert r["medium_count"] == 1

    def test_long_sentence(self):
        text = "这是一个非常非常非常长的句子它包含了很多很多的字符超过了四十个字的标准所以应该被归类为长句子这是为了测试长句子的检测功能。"
        r = _analyze_sentence_length(text)
        assert r["sentence_count"] == 1
        assert r["long_count"] == 1

    def test_ratios_sum_to_one(self):
        text = "短。这个句子中等长度大约二十多个字。" + "这是一个非常非常非常长的句子它包含了很多很多的字符超过了四十个字的标准所以应该被归类为长句。"
        r = _analyze_sentence_length(text)
        total_ratio = r["short_ratio"] + r["medium_ratio"] + r["long_ratio"]
        assert abs(total_ratio - 1.0) < 0.01

    def test_avg_length(self):
        text = "十个字的句子哦。二十个字的句子嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯。"
        r = _analyze_sentence_length(text)
        assert r["avg_length"] > 0


# ── _analyze_url_density ─────────────────────────────────────


class TestAnalyzeUrlDensity:
    def test_no_urls(self):
        r = _analyze_url_density("没有链接的文本。")
        assert r["url_count"] == 0
        assert r["url_density_per_1k"] == 0.0

    def test_one_url(self):
        r = _analyze_url_density("参考 https://example.com 这个链接。")
        assert r["url_count"] == 1
        assert r["url_density_per_1k"] > 0

    def test_multiple_urls(self):
        text = "链接1 https://a.com 链接2 http://b.com 完。"
        r = _analyze_url_density(text)
        assert r["url_count"] == 2

    def test_empty(self):
        r = _analyze_url_density("")
        assert r["url_count"] == 0
        assert r["url_density_per_1k"] == 0.0

    def test_density_scales(self):
        short = "短 https://x.com 完。"
        long_text = "长" * 500 + " https://x.com 完。"
        r_short = _analyze_url_density(short)
        r_long = _analyze_url_density(long_text)
        assert r_short["url_density_per_1k"] > r_long["url_density_per_1k"]


# ── _analyze_evidence_density ────────────────────────────────


class TestAnalyzeEvidenceDensity:
    def test_empty(self):
        r = _analyze_evidence_density("")
        assert r["data_count"] == 0
        assert r["person_count"] == 0
        assert r["event_count"] == 0
        assert r["quote_count"] == 0

    def test_has_numbers(self):
        text = "2024年中国GDP增长了5.2%，全球排名第一。总额达到126万亿元。"
        r = _analyze_evidence_density(text)
        assert r["data_count"] > 0
        assert r["data_density_per_1k"] > 0

    def test_density_keys_present(self):
        r = _analyze_evidence_density("简单文本。")
        expected_keys = {
            "data_density_per_1k", "person_density_per_1k",
            "event_density_per_1k", "quote_density_per_1k",
            "data_count", "person_count", "event_count", "quote_count",
        }
        assert set(r.keys()) == expected_keys


# ── analyze (主编排) ─────────────────────────────────────────


class TestAnalyze:
    def test_returns_all_dimensions(self):
        r = analyze("测试文本。第二段。\n\n第三段。")
        assert "structure" in r
        assert "sentence_length" in r
        assert "evidence_density" in r
        assert "url_density" in r
        assert "analyzed_at" in r

    def test_analyzed_at_is_iso(self):
        r = analyze("任意文本。")
        assert "T" in r["analyzed_at"]

    def test_structure_correct(self):
        text = "# 标题\n\n第一段内容。\n\n第二段内容。"
        r = analyze(text)
        assert r["structure"]["paragraph_count"] == 3
        assert r["structure"]["heading_count"] == 1
