#!/usr/bin/env python3
"""style_evolution.py — 发布反馈闭环：style_feedback -> STYLE.md 增量进化

PD-01 CLI 子命令：
  record <slug> --reads N --read-through F --shares N --comments N --comment_sentiment score
      记录一篇发布反馈到 output/state/style_feedback.jsonl（一行一个 JSON）

  evolve
      读所有 feedback，按 read_through_rate 与 comment_sentiment 给文章分好坏
      (>median 好)，关联每篇文章的风格指纹（读 output/state/{slug}_fingerprint.json），
      对"好"文章的风格指标与 STYLE.md 基线做加权微调建议（增量 +-10%），
      输出 evolve_suggestion.json，不自动改 STYLE.md（人工确认）。exit 0。

数据结构 StyleFeedback:
  {article_slug, publish_date, reads, read_through_rate, shares, comments, comment_sentiment}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

# 项目根 = 脚本所在目录的上一级
_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _ROOT / "output" / "state"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

# 反馈数据文件
_FEEDBACK_FILE = _STATE_DIR / "style_feedback.jsonl"
# 进化建议输出
_SUGGESTION_FILE = _STATE_DIR / "evolve_suggestion.json"
# STYLE.md 基线
_STYLE_MD = _ROOT / "persona" / "STYLE.md"


# =========================================================================
# record 子命令：记录发布反馈
# =========================================================================

def cmd_record(args: argparse.Namespace) -> int:
    """记录一篇文章的发布反馈到 style_feedback.jsonl"""
    feedback = {
        "article_slug": args.slug,
        "publish_date": args.publish_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "reads": args.reads,
        "read_through_rate": args.read_through,
        "shares": args.shares,
        "comments": args.comments,
        "comment_sentiment": args.comment_sentiment,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    # 校验 read_through_rate 在 [0, 1] 范围
    if not (0.0 <= feedback["read_through_rate"] <= 1.0):
        print(json.dumps({"error": "read_through_rate 应在 0.0~1.0 之间",
                          "got": feedback["read_through_rate"]},
                         ensure_ascii=False, indent=2))
        return 1

    # 校验 comment_sentiment 在 [-1, 1] 范围
    if not (-1.0 <= feedback["comment_sentiment"] <= 1.0):
        print(json.dumps({"error": "comment_sentiment 应在 -1.0~1.0 之间",
                          "got": feedback["comment_sentiment"]},
                         ensure_ascii=False, indent=2))
        return 1

    # 追加写入 JSONL
    with open(_FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(feedback, ensure_ascii=False) + "\n")

    print(json.dumps({
        "status": "recorded",
        "feedback": feedback,
        "file": str(_FEEDBACK_FILE),
    }, ensure_ascii=False, indent=2))
    return 0


# =========================================================================
# evolve 子命令：基于反馈数据生成风格微调建议
# =========================================================================

def _load_feedbacks() -> list[dict]:
    """从 style_feedback.jsonl 加载所有反馈记录"""
    if not _FEEDBACK_FILE.exists():
        return []
    records = []
    with open(_FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                # 跳过损坏行，打印警告到 stderr
                print(f"[警告] style_feedback.jsonl 第 {line_no} 行 JSON 解析失败，跳过",
                      file=sys.stderr)
    return records


def _load_fingerprint(slug: str) -> dict | None:
    """加载文章风格指纹 JSON（output/state/{slug}_fingerprint.json）"""
    fp_path = _STATE_DIR / f"{slug}_fingerprint.json"
    if not fp_path.exists():
        return None
    try:
        with open(fp_path, "r", encoding="utf-8") as f:
            return json.loads(f.read())
    except (json.JSONDecodeError, OSError):
        return None


def _parse_style_baseline() -> dict:
    """从 STYLE.md 中解析可量化的基线指标

    提取的指标：
    - short_ratio: 短句占比
    - mid_ratio: 中句占比
    - long_ratio: 长句占比
    - avg_paragraph_length: 平均段落长度（字）
    - emotion_temperature: 情感温度 (0-10)
    - anti_ai_score: 反AI特征评分 (0-10)
    """
    baseline = {}
    if not _STYLE_MD.exists():
        return baseline

    text = _STYLE_MD.read_text(encoding="utf-8")

    # 提取句长比 (短<15:中15-40:长>40)
    # 格式示例：1922/8673 : 3321/8673 : 3430/8673
    ratio_match = re.search(
        r'句长比.*?(\d+)/(\d+)\s*:\s*(\d+)/(\d+)\s*:\s*(\d+)/(\d+)',
        text
    )
    if ratio_match:
        total = int(ratio_match.group(2))
        if total > 0:
            baseline["short_ratio"] = round(int(ratio_match.group(1)) / total, 4)
            baseline["mid_ratio"] = round(int(ratio_match.group(3)) / total, 4)
            baseline["long_ratio"] = round(int(ratio_match.group(5)) / total, 4)

    # 短句占比百分比格式：短句占比22.2%
    short_pct = re.search(r'短句占比\s*([\d.]+)%', text)
    if short_pct and "short_ratio" not in baseline:
        baseline["short_ratio"] = round(float(short_pct.group(1)) / 100, 4)

    mid_pct = re.search(r'中句\s*([\d.]+)%', text)
    if mid_pct and "mid_ratio" not in baseline:
        baseline["mid_ratio"] = round(float(mid_pct.group(1)) / 100, 4)

    long_pct = re.search(r'长句\s*([\d.]+)%', text)
    if long_pct and "long_ratio" not in baseline:
        baseline["long_ratio"] = round(float(long_pct.group(1)) / 100, 4)

    # 平均段落长度
    para_len = re.search(r'平均段落长度.*?(\d+)\s*字', text)
    if para_len:
        baseline["avg_paragraph_length"] = int(para_len.group(1))

    # 情感温度
    emotion = re.search(r'情感温度.*?(\d+)\s*/\s*10', text)
    if emotion:
        baseline["emotion_temperature"] = int(emotion.group(1))

    # 反AI特征评分
    anti_ai = re.search(r'反AI特征.*?(\d+)\s*/\s*10', text)
    if anti_ai:
        baseline["anti_ai_score"] = int(anti_ai.group(1))

    # 段落数
    para_count = re.search(r'段落数.*?(\d+)', text)
    if para_count:
        baseline["paragraph_count"] = int(para_count.group(1))

    # 分析句数
    sent_count = re.search(r'分析句数.*?(\d+)', text)
    if sent_count:
        baseline["sentence_count"] = int(sent_count.group(1))

    return baseline


def _classify_articles(feedbacks: list[dict]) -> tuple[list[dict], list[dict]]:
    """按 read_through_rate 与 comment_sentiment 的中位数将文章分好坏

    好文章 = read_through_rate > median 且 comment_sentiment > median
    坏文章 = 其余
    """
    if len(feedbacks) < 2:
        # 不足两条时无法计算中位数分组，全部算"好"
        return feedbacks, []

    rtr_values = [f["read_through_rate"] for f in feedbacks]
    cs_values = [f["comment_sentiment"] for f in feedbacks]

    rtr_med = median(rtr_values)
    cs_med = median(cs_values)

    good = []
    bad = []
    for fb in feedbacks:
        if fb["read_through_rate"] > rtr_med and fb["comment_sentiment"] > cs_med:
            good.append(fb)
        else:
            bad.append(fb)

    # 如果全部都高于中位数（数据完全相同），退化为全好
    if not good:
        good = feedbacks

    return good, bad


def _aggregate_fingerprints(slugs: list[str]) -> dict:
    """聚合多篇文章的风格指纹，对数值型字段取平均"""
    fingerprints = []
    missing = []
    for slug in slugs:
        fp = _load_fingerprint(slug)
        if fp is not None:
            fingerprints.append(fp)
        else:
            missing.append(slug)

    if not fingerprints:
        return {"_missing": missing, "_count": 0}

    # 收集所有数值字段并求平均
    numeric_keys = set()
    for fp in fingerprints:
        for k, v in fp.items():
            if isinstance(v, (int, float)) and not k.startswith("_"):
                numeric_keys.add(k)

    aggregated = {}
    for key in sorted(numeric_keys):
        values = [fp[key] for fp in fingerprints if key in fp and isinstance(fp[key], (int, float))]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)

    aggregated["_count"] = len(fingerprints)
    aggregated["_missing"] = missing
    return aggregated


def _compute_suggestions(good_agg: dict, baseline: dict) -> list[dict]:
    """对比好文章的聚合指纹与 STYLE.md 基线，生成增量微调建议

    微调幅度限制在 +-10% 以内（增量进化，避免剧烈偏移）
    """
    suggestions = []

    # 收集两侧共有的数值字段
    shared_keys = set()
    for k in good_agg:
        if k.startswith("_"):
            continue
        if k in baseline and isinstance(good_agg[k], (int, float)) and isinstance(baseline[k], (int, float)):
            shared_keys.add(k)

    for key in sorted(shared_keys):
        current = baseline[key]
        target = good_agg[key]

        if current == 0:
            # 避免除零；若基线为 0 但好文章有值，建议设为该值
            if target != 0:
                suggestions.append({
                    "metric": key,
                    "baseline": current,
                    "good_avg": round(target, 4),
                    "suggested": round(target, 4),
                    "delta_pct": None,
                    "note": "基线为 0，建议直接采用好文章均值",
                })
            continue

        delta = target - current
        delta_pct = delta / abs(current)

        # 限制微调幅度在 +-10%
        capped_pct = max(-0.10, min(0.10, delta_pct))
        suggested = round(current * (1 + capped_pct), 4)

        # 只有差异超过 1% 才输出建议
        if abs(delta_pct) < 0.01:
            continue

        suggestions.append({
            "metric": key,
            "baseline": current,
            "good_avg": round(target, 4),
            "suggested": suggested,
            "delta_pct": round(capped_pct * 100, 2),
            "raw_delta_pct": round(delta_pct * 100, 2),
            "note": f"{'上调' if capped_pct > 0 else '下调'} {abs(round(capped_pct * 100, 2))}%"
                    + (f"（原始偏差 {round(delta_pct * 100, 2)}%，已限幅 +-10%）"
                       if abs(delta_pct) > 0.10 else ""),
        })

    return suggestions


def cmd_evolve(args: argparse.Namespace) -> int:
    """读所有 feedback 并生成风格进化建议"""
    feedbacks = _load_feedbacks()
    if not feedbacks:
        result = {
            "status": "no_data",
            "message": "未找到反馈数据，请先使用 record 子命令记录发布反馈",
            "feedback_file": str(_FEEDBACK_FILE),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 1. 按 read_through_rate 与 comment_sentiment 分好坏
    good, bad = _classify_articles(feedbacks)

    # 2. 加载好文章的风格指纹并聚合
    good_slugs = [f["article_slug"] for f in good]
    bad_slugs = [f["article_slug"] for f in bad]
    good_agg = _aggregate_fingerprints(good_slugs)
    bad_agg = _aggregate_fingerprints(bad_slugs)

    # 3. 解析 STYLE.md 基线
    baseline = _parse_style_baseline()

    # 4. 生成微调建议（增量 +-10%）
    suggestions = _compute_suggestions(good_agg, baseline)

    # 5. 组装输出
    rtr_values = [f["read_through_rate"] for f in feedbacks]
    cs_values = [f["comment_sentiment"] for f in feedbacks]
    rtr_med = median(rtr_values) if len(rtr_values) >= 2 else (rtr_values[0] if rtr_values else 0)
    cs_med = median(cs_values) if len(cs_values) >= 2 else (cs_values[0] if cs_values else 0)

    result = {
        "status": "ok",
        "total_articles": len(feedbacks),
        "classification": {
            "good_count": len(good),
            "bad_count": len(bad),
            "thresholds": {
                "read_through_rate_median": round(rtr_med, 4),
                "comment_sentiment_median": round(cs_med, 4),
            },
            "good_slugs": good_slugs,
            "bad_slugs": bad_slugs,
        },
        "fingerprint_coverage": {
            "good_loaded": good_agg.get("_count", 0),
            "good_missing": good_agg.get("_missing", []),
            "bad_loaded": bad_agg.get("_count", 0),
            "bad_missing": bad_agg.get("_missing", []),
        },
        "baseline": baseline,
        "good_aggregate": {k: v for k, v in good_agg.items() if not k.startswith("_")},
        "suggestions": suggestions,
        "note": "建议仅供人工确认，不自动修改 STYLE.md。增量微调幅度限制在 +-10%。",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # 写入 evolve_suggestion.json
    with open(_SUGGESTION_FILE, "w", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    # 同时输出到 stdout
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# =========================================================================
# CLI 入口
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="发布反馈闭环：style_feedback -> STYLE.md 增量进化"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # --- record 子命令 ---
    p_record = subparsers.add_parser(
        "record",
        help="记录一篇文章的发布反馈到 style_feedback.jsonl"
    )
    p_record.add_argument("slug", help="文章 slug 标识符")
    p_record.add_argument("--reads", type=int, required=True, help="阅读数")
    p_record.add_argument("--read-through", type=float, required=True,
                          help="完读率 (0.0~1.0)")
    p_record.add_argument("--shares", type=int, required=True, help="分享数")
    p_record.add_argument("--comments", type=int, required=True, help="评论数")
    p_record.add_argument("--comment_sentiment", type=float, required=True,
                          help="评论情感得分 (-1.0~1.0)")
    p_record.add_argument("--publish-date", type=str, default=None,
                          help="发布日期 (YYYY-MM-DD)，默认今天")

    # --- evolve 子命令 ---
    p_evolve = subparsers.add_parser(
        "evolve",
        help="读取反馈数据，生成 STYLE.md 增量进化建议"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "record":
        sys.exit(cmd_record(args))
    elif args.command == "evolve":
        sys.exit(cmd_evolve(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
