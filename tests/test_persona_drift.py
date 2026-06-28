"""Tests for persona_drift.py — pure stats functions."""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from persona_drift import (
    _mean,
    _std,
    _cv,
    _METRIC_NAMES,
    compute_stats,
    find_outliers,
    collect_files,
)

import pytest
import tempfile
import os


# ── _mean ──

class TestMean:
    def test_empty(self):
        assert _mean([]) == 0.0

    def test_single(self):
        assert _mean([5.0]) == 5.0

    def test_integers(self):
        assert _mean([1, 2, 3]) == 2.0

    def test_floats(self):
        assert abs(_mean([0.1, 0.2, 0.3]) - 0.2) < 1e-9

    def test_negative(self):
        assert _mean([-2, 0, 2]) == 0.0

    def test_all_same(self):
        assert _mean([7, 7, 7, 7]) == 7.0


# ── _std ──

class TestStd:
    def test_empty(self):
        assert _std([], 0.0) == 0.0

    def test_single_value(self):
        assert _std([5.0], 5.0) == 0.0

    def test_all_same(self):
        assert _std([3, 3, 3], 3.0) == 0.0

    def test_basic(self):
        values = [2, 4, 4, 4, 5, 5, 7, 9]
        m = _mean(values)
        s = _std(values, m)
        assert abs(s - 2.0) < 0.01

    def test_two_values(self):
        values = [0, 10]
        m = _mean(values)
        s = _std(values, m)
        assert abs(s - 5.0) < 1e-9

    def test_known_population_std(self):
        values = [1, 2, 3, 4, 5]
        m = 3.0
        expected = math.sqrt(sum((v - m) ** 2 for v in values) / 5)
        assert abs(_std(values, m) - expected) < 1e-9


# ── _cv ──

class TestCv:
    def test_zero_mean_zero_std(self):
        assert _cv(0.0, 0.0) == 0.0

    def test_zero_mean_nonzero_std(self):
        assert _cv(0.0, 1.0) == float("inf")

    def test_normal(self):
        assert abs(_cv(2.0, 1.0) - 0.5) < 1e-9

    def test_negative_mean(self):
        assert abs(_cv(-4.0, 2.0) - 0.5) < 1e-9

    def test_large_cv(self):
        assert abs(_cv(1.0, 3.0) - 3.0) < 1e-9


# ── compute_stats ──

def _make_article(slug, values):
    vector = dict(zip(_METRIC_NAMES, values))
    return {"slug": slug, "vector": vector}


class TestComputeStats:
    def test_single_article(self):
        arts = [_make_article("a", [0.5, 0.3, 0.2, 0.01, 0.02, 50, 0.1])]
        stats = compute_stats(arts)
        assert len(stats) == len(_METRIC_NAMES)
        for m in _METRIC_NAMES:
            assert stats[m]["std"] == 0.0

    def test_two_articles_mean(self):
        arts = [
            _make_article("a", [0.2, 0.5, 0.3, 0.0, 0.0, 100, 0.0]),
            _make_article("b", [0.4, 0.3, 0.3, 0.0, 0.0, 200, 0.0]),
        ]
        stats = compute_stats(arts)
        assert abs(stats["sentence_ratio_short"]["mean"] - 0.3) < 1e-6
        assert abs(stats["avg_paragraph_chars"]["mean"] - 150) < 1e-6

    def test_cv_flags_drift(self):
        arts = [
            _make_article("a", [0.1, 0.5, 0.4, 0.0, 0.0, 50, 0.0]),
            _make_article("b", [0.9, 0.05, 0.05, 0.0, 0.0, 50, 0.0]),
        ]
        stats = compute_stats(arts)
        assert stats["sentence_ratio_short"]["cv"] > 0.3

    def test_identical_articles_zero_cv(self):
        v = [0.3, 0.4, 0.3, 0.01, 0.02, 80, 0.05]
        arts = [_make_article("a", v), _make_article("b", v)]
        stats = compute_stats(arts)
        for m in _METRIC_NAMES:
            assert stats[m]["cv"] == 0.0

    def test_rounding(self):
        arts = [
            _make_article("a", [1/3, 0, 0, 0, 0, 0, 0]),
            _make_article("b", [2/3, 0, 0, 0, 0, 0, 0]),
        ]
        stats = compute_stats(arts)
        assert stats["sentence_ratio_short"]["mean"] == round(0.5, 6)


# ── find_outliers ──

class TestFindOutliers:
    def test_no_outliers_identical(self):
        v = [0.3, 0.4, 0.3, 0.01, 0.02, 80, 0.05]
        arts = [_make_article("a", v), _make_article("b", v)]
        stats = compute_stats(arts)
        assert find_outliers(arts, stats) == []

    def test_outlier_detected(self):
        base = [0.3, 0.4, 0.3, 0.01, 0.02, 80, 0.05]
        arts = [_make_article(f"n{i}", base) for i in range(9)]
        arts.append(_make_article("outlier", [0.3, 0.4, 0.3, 0.01, 0.02, 800, 0.05]))
        stats = compute_stats(arts)
        outliers = find_outliers(arts, stats)
        slugs = [o["slug"] for o in outliers]
        assert "outlier" in slugs
        assert all(o["metric"] == "avg_paragraph_chars" for o in outliers if o["slug"] == "outlier")

    def test_outlier_has_required_fields(self):
        base = [0.1, 0.5, 0.4, 0.0, 0.0, 50, 0.0]
        arts = [_make_article(f"n{i}", base) for i in range(9)]
        arts.append(_make_article("x", [0.1, 0.5, 0.4, 0.0, 0.0, 500, 0.0]))
        stats = compute_stats(arts)
        outliers = find_outliers(arts, stats)
        assert len(outliers) > 0
        o = outliers[0]
        assert "slug" in o
        assert "metric" in o
        assert "metric_label" in o
        assert "value" in o
        assert "mean" in o
        assert "deviation_sigma" in o
        assert o["deviation_sigma"] > 2.0

    def test_no_outlier_within_2sigma(self):
        arts = [
            _make_article("a", [0.3, 0.4, 0.3, 0.01, 0.02, 80, 0.05]),
            _make_article("b", [0.31, 0.39, 0.30, 0.011, 0.021, 82, 0.051]),
            _make_article("c", [0.29, 0.41, 0.30, 0.009, 0.019, 78, 0.049]),
        ]
        stats = compute_stats(arts)
        outliers = find_outliers(arts, stats)
        assert outliers == []

    def test_multiple_metrics_outlier(self):
        base = [0.3, 0.4, 0.3, 0.01, 0.02, 80, 0.05]
        arts = [_make_article(f"n{i}", base) for i in range(9)]
        arts.append(_make_article("wild", [0.95, 0.4, 0.3, 0.01, 0.02, 800, 0.05]))
        stats = compute_stats(arts)
        outliers = find_outliers(arts, stats)
        wild_metrics = {o["metric"] for o in outliers if o["slug"] == "wild"}
        assert len(wild_metrics) >= 2


# ── collect_files ──

class TestCollectFiles:
    def test_directory(self, tmp_path):
        (tmp_path / "a.md").write_text("# A")
        (tmp_path / "b.md").write_text("# B")
        (tmp_path / "c.txt").write_text("not md")
        files = collect_files(str(tmp_path))
        assert len(files) == 2
        assert all(f.suffix == ".md" for f in files)

    def test_single_file(self, tmp_path):
        f = tmp_path / "single.md"
        f.write_text("# Single")
        files = collect_files(str(f))
        assert len(files) == 1

    def test_empty_directory(self, tmp_path):
        files = collect_files(str(tmp_path))
        assert files == []

    def test_nonexistent_path(self):
        files = collect_files("/tmp/nonexistent_persona_drift_test_xyz")
        assert files == []
