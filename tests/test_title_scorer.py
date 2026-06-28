#!/usr/bin/env python3
"""title_scorer.py 单测 — 覆盖长度/句式/信息密度/反模式/综合评分。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from title_scorer import (
    _score_length,
    _score_templates,
    _score_info_density,
    _score_anti_patterns,
    score_title,
)


# ── 长度评分 ──────────────────────────────────────────────

def test_length_perfect_range():
    score, issues = _score_length("八字刚好的标题在此")  # 9 chars
    assert score == 30
    assert issues == []


def test_length_20_chars():
    title = "a" * 20
    score, _ = _score_length(title)
    assert score == 30


def test_length_very_short():
    score, issues = _score_length("太短")  # 2 chars < 5
    assert score == 5
    assert any("过短" in i for i in issues)


def test_length_moderately_short():
    score, issues = _score_length("六个字标题")  # 5 chars, >=5 but <8
    assert score == 20
    assert any("偏短" in i for i in issues)


def test_length_moderately_long():
    title = "这是一个二十五个字的标题用来测试偏长扣分逻辑是否正确执行"  # >20, <=35
    n = len(title)
    assert 20 < n <= 35
    score, issues = _score_length(title)
    assert 10 <= score < 30
    assert any("偏长" in i for i in issues)


def test_length_very_long():
    title = "a" * 36  # >35
    score, issues = _score_length(title)
    assert score == 5
    assert any("过长" in i for i in issues)


# ── 句式模板 ──────────────────────────────────────────────

def test_template_not_a_but_b():
    _, matched = _score_templates("婚姻不是围城而是零件")
    assert "不是A是B" in matched


def test_template_colon():
    _, matched = _score_templates("AI富士康：4分钱一个框")
    assert "冒号二元对照" in matched


def test_template_quote():
    _, matched = _score_templates("当「躺平」成为一种抵抗")
    assert "引号反讽" in matched


def test_template_identity_prefix():
    _, matched = _score_templates("那些被遗忘的人")
    assert "身份词前置" in matched


def test_template_number_suspense():
    _, matched = _score_templates("3亿人背后的真相")
    assert "数字悬念" in matched


def test_template_question():
    _, matched = _score_templates("文凭为什么失灵了？")
    assert "问句" in matched


def test_template_bonus_capped():
    title = "我们3亿人不是韭菜而是「工具」：为什么？"
    score, matched = _score_templates(title)
    assert score <= 20


def test_template_no_match():
    score, matched = _score_templates("平淡无奇的标题")
    assert score == 0
    assert matched == []


# ── 信息密度 ──────────────────────────────────────────────

def test_info_number_with_unit():
    score, matched = _score_info_density("1270万毕业生的困境")
    assert score > 0
    assert "含具体数字" in matched


def test_info_proper_noun():
    score, matched = _score_info_density("AI时代的信息差")
    assert "含专有名词" in matched


def test_info_both():
    score, matched = _score_info_density("AI替代了996万个岗位")
    assert score == 10  # capped at 10
    assert len(matched) == 2


def test_info_none():
    score, matched = _score_info_density("平凡的日子")
    assert score == 0
    assert matched == []


# ── 反模式 ────────────────────────────────────────────────

def test_anti_chicken_soup():
    score, issues = _score_anti_patterns("你只需要勇敢一点")
    assert score < 0
    assert len(issues) == 2


def test_anti_single():
    score, issues = _score_anti_patterns("治愈系的标题")
    assert score == -10
    assert any("治愈" in i for i in issues)


def test_anti_clean():
    score, issues = _score_anti_patterns("省籍彩票：高考判分")
    assert score == 0
    assert issues == []


# ── 综合评分 ──────────────────────────────────────────────

def test_score_title_good():
    result = score_title("1270万毕业生：学历倒挂时代，文凭为什么失灵了？")
    assert result["score"] >= 60
    assert "title" in result
    assert isinstance(result["templates"], list)
    assert isinstance(result["issues"], list)


def test_score_title_bad():
    result = score_title("加油")
    assert result["score"] < 50


def test_score_title_clamped():
    result = score_title("你只需要勇敢一点相信自己加油努力就会美好温暖治愈正能量坚持就是胜利")
    assert result["score"] >= 0


def test_score_title_empty():
    result = score_title("")
    assert result["score"] >= 0
    assert result["score"] <= 100


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
