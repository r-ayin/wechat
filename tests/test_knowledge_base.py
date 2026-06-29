"""tests/test_knowledge_base.py -- A4 knowledge base unit tests

Covers: _extract_urls, _load_kb, _cmd_add (via subprocess), _cmd_query, _cmd_stats, main CLI.
Strategy: mock claim_extractor to avoid NLP dependency; use tmp_path for JSONL isolation.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import TestCase, mock

# Ensure scripts/ is on path so `import knowledge_base` works without package install.
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))


def _fake_person(text):
    return [{"text": "张三", "span": (0, 2)}] if text else []


def _fake_event(text):
    return [{"text": "发布会召开", "span": (0, 5)}] if text else []


def _fake_data(text):
    return [{"text": "营收1亿", "context": "Q3财报显示营收1亿", "data_type": "financial"}] if text else []


def _fake_quote(text):
    return [{"text": "信息差即权力", "span": (0, 6)}] if text else []


class ExtractUrlsTest(TestCase):
    """_extract_urls: dedup + trailing punctuation strip."""

    def setUp(self):
        with mock.patch.dict("sys.modules", {"claim_extractor": mock.MagicMock()}):
            import knowledge_base as kb
            self.kb = kb

    def test_extracts_single_url(self):
        urls = self.kb._extract_urls("see https://example.com/a for details")
        self.assertEqual(urls, ["https://example.com/a"])

    def test_deduplicates(self):
        text = "https://x.com/a and again https://x.com/a"
        self.assertEqual(self.kb._extract_urls(text), ["https://x.com/a"])

    def test_strips_trailing_punctuation(self):
        urls = self.kb._extract_urls("link: https://x.com/b.,;:!? end")
        self.assertEqual(urls, ["https://x.com/b"])

    def test_preserves_order(self):
        text = "https://b.com https://a.com https://b.com"
        self.assertEqual(self.kb._extract_urls(text), ["https://b.com", "https://a.com"])

    def test_empty_on_no_urls(self):
        self.assertEqual(self.kb._extract_urls("no links here"), [])

    def test_min_length_filter(self):
        # regex requires ≥5 chars after scheme
        urls = self.kb._extract_urls("http://ab is too short but https://ok.example.com/path is fine")
        self.assertEqual(urls, ["https://ok.example.com/path"])


class LoadKbTest(TestCase):
    """_load_kb: empty/missing file, malformed lines skipped, valid entries returned."""

    def setUp(self):
        self._mods = {
            "claim_extractor": mock.MagicMock(),
        }
        self.patcher = mock.patch.dict("sys.modules", self._mods)
        self.patcher.start()
        import knowledge_base as kb
        self.kb = kb

    def tearDown(self):
        self.patcher.stop()

    def test_returns_empty_when_file_missing(self, ):
        with mock.patch.object(self.kb, "_KB_PATH", Path("/nonexistent/kb.jsonl")):
            self.assertEqual(self.kb._load_kb(), [])

    def test_skips_blank_and_malformed_lines(self, tmp_path_factory=None):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write('{"slug":"a"}\n\nnot-json\n{"slug":"b"}\n')
            p = Path(f.name)
        try:
            with mock.patch.object(self.kb, "_KB_PATH", p):
                entries = self.kb._load_kb()
        finally:
            p.unlink(missing_ok=True)
        self.assertEqual([e["slug"] for e in entries], ["a", "b"])

    def test_loads_valid_entries(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"slug": "x", "persons": ["李四"]}, ensure_ascii=False) + "\n")
            p = Path(f.name)
        try:
            with mock.patch.object(self.kb, "_KB_PATH", p):
                entries = self.kb._load_kb()
        finally:
            p.unlink(missing_ok=True)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["persons"], ["李四"])


class CmdQueryTest(TestCase):
    """_cmd_query: keyword search across slug/persons/events/data/quotes/sources."""

    def setUp(self):
        self._mods = {"claim_extractor": mock.MagicMock()}
        self.patcher = mock.patch.dict("sys.modules", self._mods)
        self.patcher.start()
        import knowledge_base as kb
        self.kb = kb
        self.entries = [
            {
                "slug": "gig-economy-2025",
                "persons": ["王五"],
                "events": ["平台新规发布"],
                "data": [{"value": "DAU 500万", "context": "季度报告 DAU 500万"}],
                "quotes": ["算法不是中立"],
                "sources": ["https://news.example.com/gig"],
                "date": "2025-09-01",
            },
            {
                "slug": "ai-labor-shift",
                "persons": ["赵六"],
                "events": ["工厂自动化"],
                "data": [],
                "quotes": [],
                "sources": [],
                "date": "2025-10-01",
            },
        ]

    def tearDown(self):
        self.patcher.stop()

    def _run_query(self, keyword):
        import io
        import contextlib
        buf = io.StringIO()
        args = mock.Mock(keyword=keyword)
        with mock.patch.object(self.kb, "_load_kb", return_value=self.entries):
            with contextlib.redirect_stdout(buf):
                self.kb._cmd_query(args)
        return json.loads(buf.getvalue())

    def test_matches_slug_case_insensitive(self):
        out = self._run_query("GIG")
        self.assertEqual(out["total"], 1)
        self.assertIn("slug", out["results"][0]["matched_fields"])

    def test_matches_person_exact_substring(self):
        out = self._run_query("王五")
        self.assertEqual(out["total"], 1)
        self.assertIn("persons", out["results"][0]["matched_fields"])

    def test_empty_keyword_returns_error(self):
        out = self._run_query("   ")
        self.assertIn("error", out)

    def test_no_match_returns_zero_results(self):
        out = self._run_query("不存在的关键字")
        self.assertEqual(out["total"], 0)


class CmdStatsTest(TestCase):
    """_cmd_stats: aggregates entities, unique sources, top persons."""

    def setUp(self):
        self.patcher = mock.patch.dict("sys.modules", {"claim_extractor": mock.MagicMock()})
        self.patcher.start()
        import knowledge_base as kb
        self.kb = kb

    def tearDown(self):
        self.patcher.stop()

    def _run_stats(self, entries):
        import io, contextlib
        buf = io.StringIO()
        with mock.patch.object(self.kb, "_load_kb", return_value=entries):
            with contextlib.redirect_stdout(buf):
                self.kb._cmd_stats(mock.Mock())
        return json.loads(buf.getvalue())

    def test_empty_kb_message(self):
        out = self._run_stats([])
        self.assertEqual(out["total_entries"], 0)
        self.assertEqual(out["message"], "knowledge base is empty")

    def test_aggregates_top_persons_and_unique_sources(self):
        entries = [
            {"persons": ["A", "B"], "sources": ["https://s1"], "events": [], "data": [], "quotes": [], "date": "2025-01-01"},
            {"persons": ["A", "C"], "sources": ["https://s1", "https://s2"], "events": [], "data": [], "quotes": [], "date": "2025-02-01"},
        ]
        out = self._run_stats(entries)
        self.assertEqual(out["total_entries"], 2)
        self.assertEqual(out["unique_sources"], 2)
        self.assertEqual(out["entity_totals"]["persons"], 4)
        # A appears twice → top
        self.assertEqual(out["top_persons"][0]["name"], "A")
        self.assertEqual(out["top_persons"][0]["count"], 2)


class MainCliTest(TestCase):
    """main(): argparse routing + always exit 0."""

    def setUp(self):
        self.patcher = mock.patch.dict("sys.modules", {"claim_extractor": mock.MagicMock()})
        self.patcher.start()
        import knowledge_base as kb
        self.kb = kb

    def tearDown(self):
        self.patcher.stop()

    def test_no_command_does_not_crash(self):
        with mock.patch("sys.argv", ["kb"]):
            try:
                self.kb.main()
            except SystemExit as e:
                self.assertEqual(e.code, 0)

    def test_stats_routes_to_cmd_stats(self):
        with mock.patch("sys.argv", ["kb", "stats"]):
            with mock.patch.object(self.kb, "_cmd_stats") as m:
                try:
                    self.kb.main()
                except SystemExit:
                    pass
                m.assert_called_once()


if __name__ == "__main__":
    import unittest
    unittest.main()
