#!/usr/bin/env python3
"""ending_detector.py 单测 — 覆盖结尾截取/反模式短语/结构性矛盾/简单答案/综合判定。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ending_detector import (
    _get_ending,
    _detect_anti_pattern_phrases,
    _detect_structural_contradiction,
    _detect_simple_answer,
)

import pytest


# ── _get_ending ──────────────────────────────────────────────

class TestGetEnding:
    def test_short_text_returns_full(self):
        assert _get_ending("短文", 500) == "短文"

    def test_long_text_returns_tail(self):
        text = "A" * 300 + "B" * 500
        result = _get_ending(text, 500)
        assert len(result) == 500
        assert result == "B" * 500

    def test_exact_boundary(self):
        text = "x" * 500
        assert _get_ending(text, 500) == text

    def test_custom_char_count(self):
        text = "0123456789"
        assert _get_ending(text, 3) == "789"


# ── _detect_anti_pattern_phrases ─────────────────────────────

class TestAntiPatternPhrases:
    def test_no_match(self):
        assert _detect_anti_pattern_phrases("这是一段合理的结尾文本。") == []

    def test_single_match(self):
        hits = _detect_anti_pattern_phrases("你只需要更努力一点就好了。")
        assert "你只需要" in hits

    def test_multiple_matches(self):
        hits = _detect_anti_pattern_phrases("加油，相信自己，调整心态。")
        assert len(hits) >= 3
        assert "加油" in hits
        assert "相信" in hits
        assert "调整心态" in hits

    def test_case_insensitive_english(self):
        hits = _detect_anti_pattern_phrases("You should DEPEND YOURSELF on this.")
        assert "depend yourself" in hits

    def test_partial_no_false_positive(self):
        hits = _detect_anti_pattern_phrases("这个系统需要客观的评估。")
        assert "客观" in hits

    def test_empty_ending(self):
        assert _detect_anti_pattern_phrases("") == []


# ── _detect_structural_contradiction ─────────────────────────

class TestStructuralContradiction:
    def test_contradiction_detected(self):
        front = "制度" * 50 + "这是一个系统性问题" + "普通文本" * 200
        ending = "所以你要勇敢地改变自己"
        assert _detect_structural_contradiction(front, ending) is True

    def test_no_structural_keyword(self):
        front = "天气很好，今天阳光明媚。" * 100
        ending = "所以你要勇敢地改变自己"
        assert _detect_structural_contradiction(front, ending) is False

    def test_no_individual_word(self):
        front = "制度" * 50 + "文本" * 200
        ending = "所以我们需要更好的社会保障网络"
        assert _detect_structural_contradiction(front, ending) is False

    def test_structural_keyword_in_latter_70pct(self):
        front = "普通文本" * 200 + "制度"
        ending = "努力改变自己"
        # "制度" is in the last 70%, not front 30%
        assert _detect_structural_contradiction(front, ending) is False

    def test_empty_text(self):
        assert _detect_structural_contradiction("", "") is False


# ── _detect_simple_answer ────────────────────────────────────

class TestSimpleAnswer:
    def test_answer_pattern(self):
        text = "为什么我们不能改变？答案就是资本不允许"
        assert _detect_simple_answer(text) is True

    def test_secret_pattern(self):
        text = "你想知道成功的秘密吗？秘诀就是坚持"
        assert _detect_simple_answer(text) is True

    def test_only_need_pattern(self):
        text = "怎么办？其实只需一点勇气"
        assert _detect_simple_answer(text) is True

    def test_no_question_mark(self):
        text = "答案就是坚持不懈"
        assert _detect_simple_answer(text) is False

    def test_question_too_far(self):
        text = "为什么？" + "啊" * 200 + "答案就是那个"
        assert _detect_simple_answer(text) is False

    def test_clean_ending(self):
        text = "这就是现实。我们能做的，是找到同路人。"
        assert _detect_simple_answer(text) is False


# ── verdict logic (via internal reasoning) ───────────────────

class TestVerdictLogic:
    def test_pass_no_issues(self):
        ending = "这是一段没有任何反模式的合理结尾。没有鸡汤。"
        phrases = _detect_anti_pattern_phrases(ending)
        simple = _detect_simple_answer(ending)
        total = len(phrases) + (1 if simple else 0)
        assert total == 0

    def test_warn_single_phrase(self):
        ending = "从自己做起，改变世界。"
        phrases = _detect_anti_pattern_phrases(ending)
        simple = _detect_simple_answer(ending)
        total = len(phrases) + (1 if simple else 0)
        assert total == 1

    def test_block_multiple_phrases(self):
        ending = "加油，相信自己，努力就会成功。"
        phrases = _detect_anti_pattern_phrases(ending)
        assert len(phrases) >= 2

    def test_block_structural_contradiction(self):
        full = "这是一个制度性的问题，" * 20 + "后续内容" * 100
        ending = "所以你要勇敢地面对"
        assert _detect_structural_contradiction(full, ending) is True
