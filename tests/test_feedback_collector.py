"""tests for feedback_collector.py — _compute_reward / _load_rewards / _append_reward / cmd_report"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import feedback_collector as fc


class TestComputeReward(unittest.TestCase):

    def test_all_zero(self):
        r = fc._compute_reward(read_through=0.0, shares=0, reads=0, sentiment=-1.0)
        self.assertAlmostEqual(r, 0.0, places=4)

    def test_all_max(self):
        r = fc._compute_reward(read_through=1.0, shares=100, reads=100, sentiment=1.0)
        self.assertAlmostEqual(r, 1.0, places=4)

    def test_mid_values(self):
        r = fc._compute_reward(read_through=0.5, shares=50, reads=100, sentiment=0.0)
        # 0.4*0.5 + 0.3*0.5 + 0.3*0.5 = 0.2 + 0.15 + 0.15 = 0.5
        self.assertAlmostEqual(r, 0.5, places=4)

    def test_share_rate_capped_at_1(self):
        r = fc._compute_reward(read_through=0.0, shares=200, reads=100, sentiment=-1.0)
        # share_rate = min(200/100, 1) = 1.0; sentiment_norm = 0
        # 0.4*0 + 0.3*1.0 + 0.3*0 = 0.3
        self.assertAlmostEqual(r, 0.3, places=4)

    def test_reads_zero_no_division_error(self):
        r = fc._compute_reward(read_through=1.0, shares=5, reads=0, sentiment=1.0)
        # share_rate = min(5/1, 1) = 1.0; sentiment_norm = 1.0
        # 0.4 + 0.3 + 0.3 = 1.0
        self.assertAlmostEqual(r, 1.0, places=4)

    def test_negative_sentiment(self):
        r = fc._compute_reward(read_through=1.0, shares=0, reads=100, sentiment=-0.5)
        # sentiment_norm = (-0.5+1)/2 = 0.25
        # 0.4*1 + 0.3*0 + 0.3*0.25 = 0.4 + 0 + 0.075 = 0.475
        self.assertAlmostEqual(r, 0.475, places=4)

    def test_result_is_rounded_to_4_decimals(self):
        r = fc._compute_reward(read_through=0.3333, shares=1, reads=3, sentiment=0.1)
        self.assertEqual(r, round(r, 4))


class TestAppendAndLoadRewards(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
        self._tmp.close()
        self._orig_file = fc._REWARD_FILE
        fc._REWARD_FILE = Path(self._tmp.name)

    def tearDown(self):
        fc._REWARD_FILE = self._orig_file
        Path(self._tmp.name).unlink(missing_ok=True)

    def test_load_empty_file(self):
        Path(self._tmp.name).write_text("")
        self.assertEqual(fc._load_rewards(), [])

    def test_load_nonexistent_file(self):
        Path(self._tmp.name).unlink()
        self.assertEqual(fc._load_rewards(), [])

    def test_append_then_load(self):
        Path(self._tmp.name).write_text("")
        fc._append_reward("slug-a", 0.75, {"reads": 100})
        records = fc._load_rewards()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["slug"], "slug-a")
        self.assertAlmostEqual(records[0]["reward"], 0.75)
        self.assertIn("recorded_at", records[0])

    def test_append_multiple(self):
        Path(self._tmp.name).write_text("")
        fc._append_reward("a", 0.1, {})
        fc._append_reward("b", 0.2, {})
        fc._append_reward("c", 0.3, {})
        records = fc._load_rewards()
        self.assertEqual(len(records), 3)
        self.assertEqual([r["slug"] for r in records], ["a", "b", "c"])

    def test_load_skips_malformed_json(self):
        Path(self._tmp.name).write_text(
            '{"slug":"good","reward":0.5}\nNOT_JSON\n{"slug":"also_good","reward":0.8}\n'
        )
        records = fc._load_rewards()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["slug"], "good")
        self.assertEqual(records[1]["slug"], "also_good")

    def test_load_skips_blank_lines(self):
        Path(self._tmp.name).write_text(
            '{"slug":"x","reward":0.1}\n\n\n{"slug":"y","reward":0.2}\n'
        )
        records = fc._load_rewards()
        self.assertEqual(len(records), 2)


class TestCmdReport(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False, mode="w")
        self._tmp.close()
        self._orig_file = fc._REWARD_FILE
        fc._REWARD_FILE = Path(self._tmp.name)

    def tearDown(self):
        fc._REWARD_FILE = self._orig_file
        Path(self._tmp.name).unlink(missing_ok=True)

    def _run_report(self):
        ns = argparse.Namespace()
        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rc = fc.cmd_report(ns)
        return rc, json.loads(buf.getvalue())

    def test_no_data(self):
        Path(self._tmp.name).write_text("")
        rc, out = self._run_report()
        self.assertEqual(rc, 0)
        self.assertEqual(out["status"], "no_data")

    def test_single_record(self):
        rec = {"slug": "alpha", "reward": 0.6, "detail": {}, "recorded_at": "2026-01-01T00:00:00+00:00"}
        Path(self._tmp.name).write_text(json.dumps(rec) + "\n")
        rc, out = self._run_report()
        self.assertEqual(rc, 0)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["total_topics"], 1)
        self.assertEqual(out["ranking"][0]["slug"], "alpha")

    def test_ranking_descending_order(self):
        recs = [
            {"slug": "low", "reward": 0.2, "detail": {}, "recorded_at": "t1"},
            {"slug": "high", "reward": 0.9, "detail": {}, "recorded_at": "t2"},
            {"slug": "mid", "reward": 0.5, "detail": {}, "recorded_at": "t3"},
        ]
        Path(self._tmp.name).write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        rc, out = self._run_report()
        self.assertEqual(rc, 0)
        slugs = [r["slug"] for r in out["ranking"]]
        self.assertEqual(slugs, ["high", "mid", "low"])

    def test_same_slug_keeps_latest(self):
        recs = [
            {"slug": "topic-1", "reward": 0.3, "detail": {"v": 1}, "recorded_at": "t1"},
            {"slug": "topic-1", "reward": 0.8, "detail": {"v": 2}, "recorded_at": "t2"},
        ]
        Path(self._tmp.name).write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        rc, out = self._run_report()
        self.assertEqual(rc, 0)
        self.assertEqual(out["total_topics"], 1)
        self.assertEqual(out["total_records"], 2)
        self.assertAlmostEqual(out["ranking"][0]["reward"], 0.8)

    def test_rank_numbers_are_sequential(self):
        recs = [
            {"slug": f"s{i}", "reward": i * 0.1, "detail": {}, "recorded_at": f"t{i}"}
            for i in range(5)
        ]
        Path(self._tmp.name).write_text("\n".join(json.dumps(r) for r in recs) + "\n")
        rc, out = self._run_report()
        ranks = [r["rank"] for r in out["ranking"]]
        self.assertEqual(ranks, [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
