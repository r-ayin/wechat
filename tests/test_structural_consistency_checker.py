#!/usr/bin/env python3
"""structural_consistency_checker.py 单测 — 覆盖词频统计/维度分类/诚实结尾/理论引用/综合分析。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from structural_consistency_checker import (
    _count_words,
    classify_dimension,
    check_honest_ending,
    compute_theory_ratio,
    analyze,
    STRUCTURAL_WORDS,
    INDIVIDUAL_WORDS,
)

import pytest


# ── _count_words ─────────────────────────────────────────────

class TestCountWords:
    def test_empty_text(self):
        assert _count_words("", STRUCTURAL_WORDS) == 0

    def test_no_matches(self):
        assert _count_words("今天天气真好", STRUCTURAL_WORDS) == 0

    def test_single_match(self):
        assert _count_words("这是制度的问题", ["制度"]) == 1

    def test_multiple_distinct_matches(self):
        assert _count_words("制度和体制都有问题", ["制度", "体制"]) == 2

    def test_repeated_word(self):
        assert _count_words("制度制度制度", ["制度"]) == 3

    def test_overlapping_words_counted_independently(self):
        assert _count_words("改变自己的自己", ["自己", "改变自己"]) == 3


# ── classify_dimension ───────────────────────────────────────

class TestClassifyDimension:
    def test_empty_text_returns_mixed(self):
        dim, s, i = classify_dimension("")
        assert dim == "mixed"
        assert s == 0 and i == 0

    def test_pure_structural(self):
        text = "制度 体制 结构 系统 资本 阶层 政策 产业 规训 权力"
        dim, s, i = classify_dimension(text)
        assert dim == "structural"
        assert s == 10 and i == 0

    def test_pure_individual(self):
        text = "个人 自己 努力 心态 选择 勇气 觉醒 改变自己 坚持 信念"
        dim, s, i = classify_dimension(text)
        assert dim == "individual"
        assert i > 0

    def test_mixed_balanced(self):
        # s=4, i=3 → ratio=4/7≈0.57 → mixed (0.4 ≤ r ≤ 0.6)
        text = "制度问题需要个人努力，体制改革靠自己选择，结构调整系统需要心态"
        dim, s, i = classify_dimension(text)
        assert dim == "mixed"

    def test_structural_threshold_boundary(self):
        # s_ratio > 0.6 → structural; exactly 0.6 → mixed
        text = "制度 体制 结构 " + "个人 自己"
        dim, s, i = classify_dimension(text)
        assert s == 3 and i == 2
        assert s / (s + i) == 0.6
        assert dim == "mixed"

    def test_structural_just_above_threshold(self):
        text = "制度 体制 结构 系统 " + "个人 自己"
        dim, s, i = classify_dimension(text)
        assert s == 4 and i == 2
        assert dim == "structural"

    def test_individual_just_below_04(self):
        text = "个人 自己 努力 心态 " + "制度"
        dim, s, i = classify_dimension(text)
        assert s / (s + i) < 0.4
        assert dim == "individual"


# ── check_honest_ending ──────────────────────────────────────

class TestCheckHonestEnding:
    def test_no_keywords_returns_true(self):
        assert check_honest_ending("这段结尾什么都没有") is True

    def test_honest_words_only(self):
        assert check_honest_ending("没有简单答案，这不容易") is True

    def test_simple_answer_only(self):
        assert check_honest_ending("答案很简单，秘诀就是只需做到") is False

    def test_honest_beats_simple(self):
        assert check_honest_ending("没有简单答案也不容易，但答案就在眼前") is True

    def test_simple_only_no_honest(self):
        # code returns False only when simple>0 AND honest==0
        assert check_honest_ending("答案秘诀只需只要你做到轻松") is False

    def test_equal_counts_returns_true(self):
        assert check_honest_ending("没有简单答案，但答案在这里") is True


# ── compute_theory_ratio ─────────────────────────────────────

class TestComputeTheoryRatio:
    def test_empty_text(self):
        assert compute_theory_ratio("") == 0.0

    def test_no_theory(self):
        assert compute_theory_ratio("今天天气真好。明天也不错。") == 0.0

    def test_book_title_detected(self):
        ratio = compute_theory_ratio("正如《资本论》所说。普通句子。")
        assert ratio == pytest.approx(0.5)

    def test_expert_forward_attribution(self):
        ratio = compute_theory_ratio("经济学家张三认为这是问题。普通句子。")
        assert ratio == pytest.approx(0.5)

    def test_expert_reverse_attribution(self):
        ratio = compute_theory_ratio("张三教授说这很重要。普通句子。")
        assert ratio == pytest.approx(0.5)

    def test_mixed_sentences(self):
        text = "今天天气好。《论语》说仁。王五博士认为对。另一句。"
        ratio = compute_theory_ratio(text)
        assert ratio == pytest.approx(0.5)

    def test_all_theory(self):
        text = "《资本论》说。经济学家张三认为。"
        ratio = compute_theory_ratio(text)
        assert ratio == pytest.approx(1.0)


# ── analyze (综合判定) ───────────────────────────────────────

class TestAnalyze:
    def test_pass_consistent_structural(self):
        front = "制度 体制 结构 系统 资本 阶层 政策 " * 10
        back = "制度 体制 结构 系统 资本 没有简单答案 " * 5
        text = front + "中间内容" * 50 + back
        result = analyze(text)
        assert result["verdict"] == "pass"
        assert result["contradiction"] is False

    def test_block_contradiction(self):
        front = "制度 体制 结构 系统 资本 阶层 政策 产业 权力 " * 20
        mid = "中间" * 200
        back = "个人 自己 努力 心态 选择 勇气 觉醒 坚持 信念 " * 10
        text = front + mid + back
        result = analyze(text)
        assert result["contradiction"] is True
        assert result["verdict"] == "block"

    def test_warn_high_theory_ratio(self):
        sentences = "《某书》说了。" * 5 + "普通句子。" * 3
        result = analyze(sentences)
        if not result["contradiction"]:
            if result["theory_ratio"] > 0.2:
                assert result["verdict"] in ("warn", "block")

    def test_warn_dishonest_ending(self):
        front = "普通内容" * 100
        back = "答案秘诀只需只要你做到" * 5
        text = front + back
        result = analyze(text)
        assert result["honest_ending"] is False
        if not result["contradiction"]:
            assert result["verdict"] in ("warn", "block")

    def test_result_structure(self):
        result = analyze("测试文本" * 100)
        assert "thesis_dim" in result
        assert "ending_dim" in result
        assert "contradiction" in result
        assert "honest_ending" in result
        assert "theory_ratio" in result
        assert "verdict" in result
        assert "details" in result
        assert result["verdict"] in ("pass", "warn", "block")
