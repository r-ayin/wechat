#!/usr/bin/env python3
"""metrics_panel.py — A5 可观测性面板

扫描 output/state/ 下的管线状态文件，汇总输出：
  - 各 topic 的 phase 进度（completed/pending/failed）
  - 选题到发布耗时（state.created_at → 4.work completed marked_at）
  - QA 迭代次数（state.retries）
  - 各 phase 通过率
  - 已发布文章的 reads/read_through 均值

CLI:
  python metrics_panel.py [topic] [--date D]

输出 JSON + 可读文本面板。纯工具脚本，始终 exit 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

# ---------------------------------------------------------------------------
# 项目根 & 路径常量
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _ROOT / "output" / "state"

# Phase 顺序定义，与 pipeline.py 保持一致
PHASE_ORDER = ["0", "1", "2", "3", "3.5", "4"]


# =========================================================================
# 数据加载
# =========================================================================

def _load_state_files(topic_filter: str | None = None,
                      date_filter: str | None = None) -> list[dict]:
    """扫描 output/state/{slug}_{date}.json 状态文件，返回解析后的 state 列表。

    过滤规则：
    - topic_filter 非空时，只保留 slug 匹配的文件（支持 slug 或原始 topic）
    - date_filter 非空时，只保留日期匹配的文件
    """
    if not _STATE_DIR.exists():
        return []

    states = []
    for p in sorted(_STATE_DIR.glob("*.json")):
        # 跳过非状态文件（如 qa_plan.json、qa_results.json 等）
        name = p.stem  # e.g. "my-topic_2026-06-26"
        # 状态文件格式: {slug}_{YYYY-MM-DD}.json
        # 至少需要包含下划线且最后部分是日期格式
        parts = name.rsplit("_", 1)
        if len(parts) != 2:
            continue
        slug_part, date_part = parts
        # 简单校验日期格式（YYYY-MM-DD）
        if len(date_part) != 10 or date_part[4] != "-" or date_part[7] != "-":
            continue

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # 必须包含 steps 字段才算有效状态文件
        if "steps" not in data:
            continue

        # 过滤
        file_slug = data.get("slug", slug_part)
        file_date = data.get("date", date_part)
        if topic_filter and topic_filter not in (file_slug, data.get("topic", "")):
            continue
        if date_filter and file_date != date_filter:
            continue

        states.append(data)
    return states


def _load_style_feedback() -> list[dict]:
    """加载 output/state/style_feedback.jsonl，返回记录列表"""
    fb_file = _STATE_DIR / "style_feedback.jsonl"
    if not fb_file.exists():
        return []
    records = []
    with open(fb_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_topic_rewards() -> list[dict]:
    """加载 output/state/topic_reward.jsonl，返回记录列表"""
    rw_file = _STATE_DIR / "topic_reward.jsonl"
    if not rw_file.exists():
        return []
    records = []
    with open(rw_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


# =========================================================================
# 指标计算
# =========================================================================

def _compute_phase_progress(states: list[dict]) -> dict:
    """各 topic 的 phase 进度统计（completed/pending/failed/skipped）"""
    result = {}
    for state in states:
        slug = state.get("slug", "unknown")
        date = state.get("date", "unknown")
        key = f"{slug}_{date}"
        phases = {}
        for phase in PHASE_ORDER:
            phase_steps = [s for s in state.get("steps", []) if s.get("phase") == phase]
            if not phase_steps:
                continue
            statuses = [s.get("status", "unknown") for s in phase_steps]
            if all(st == "completed" for st in statuses):
                phase_status = "completed"
            elif any(st == "failed" for st in statuses):
                phase_status = "failed"
            elif all(st == "skipped" for st in statuses):
                phase_status = "skipped"
            elif any(st == "pending" for st in statuses):
                phase_status = "pending"
            else:
                phase_status = "in_progress"
            phases[phase] = {
                "status": phase_status,
                "total": len(phase_steps),
                "completed": sum(1 for st in statuses if st == "completed"),
                "pending": sum(1 for st in statuses if st == "pending"),
                "failed": sum(1 for st in statuses if st == "failed"),
            }
        result[key] = {
            "slug": slug,
            "topic": state.get("topic", slug),
            "date": date,
            "mode": state.get("mode", "unknown"),
            "phases": phases,
        }
    return result


def _compute_lead_time(states: list[dict]) -> list[dict]:
    """选题到发布耗时：state.created_at → 4.work completed marked_at

    仅对 Phase 4 work 步骤已 completed 的 state 计算。
    """
    lead_times = []
    for state in states:
        slug = state.get("slug", "unknown")
        date = state.get("date", "unknown")
        created_at = state.get("created_at")
        if not created_at:
            continue

        # 查找 4.work 步骤的 marked_at
        phase4_work = next(
            (s for s in state.get("steps", [])
             if s.get("id") == "4.work" and s.get("status") == "completed"),
            None
        )
        if not phase4_work or not phase4_work.get("marked_at"):
            continue

        try:
            t_start = datetime.fromisoformat(created_at)
            t_end = datetime.fromisoformat(phase4_work["marked_at"])
            duration_seconds = (t_end - t_start).total_seconds()
            duration_hours = round(duration_seconds / 3600, 2)
        except (ValueError, TypeError):
            continue

        lead_times.append({
            "slug": slug,
            "date": date,
            "created_at": created_at,
            "completed_at": phase4_work["marked_at"],
            "duration_hours": duration_hours,
        })
    return lead_times


def _compute_qa_retries(states: list[dict]) -> list[dict]:
    """QA 迭代次数统计（state.retries）"""
    retries_list = []
    for state in states:
        slug = state.get("slug", "unknown")
        date = state.get("date", "unknown")
        retries = state.get("retries", 0)
        retries_list.append({
            "slug": slug,
            "date": date,
            "retries": retries,
        })
    return retries_list


def _compute_phase_pass_rate(states: list[dict]) -> dict:
    """各 phase 通过率：已完成 / (已完成 + 失败)"""
    # 按 phase 聚合
    phase_stats: dict[str, dict[str, int]] = {}
    for phase in PHASE_ORDER:
        phase_stats[phase] = {"completed": 0, "failed": 0, "total": 0}

    for state in states:
        for phase in PHASE_ORDER:
            phase_steps = [s for s in state.get("steps", []) if s.get("phase") == phase]
            if not phase_steps:
                continue
            statuses = [s.get("status", "unknown") for s in phase_steps]
            # 该 phase 在此 state 中算一次
            phase_stats[phase]["total"] += 1
            if all(st == "completed" for st in statuses):
                phase_stats[phase]["completed"] += 1
            elif any(st == "failed" for st in statuses):
                phase_stats[phase]["failed"] += 1

    result = {}
    for phase, stats in phase_stats.items():
        decided = stats["completed"] + stats["failed"]
        pass_rate = round(stats["completed"] / decided, 4) if decided > 0 else None
        result[phase] = {
            "completed": stats["completed"],
            "failed": stats["failed"],
            "total": stats["total"],
            "pass_rate": pass_rate,
        }
    return result


def _compute_publish_metrics(rewards: list[dict],
                             feedback: list[dict]) -> dict:
    """已发布文章的 reads/read_through 均值

    优先从 topic_reward.jsonl 取数据（含 detail.reads / detail.read_through）；
    若无则从 style_feedback.jsonl 取。
    """
    reads_list: list[int] = []
    read_through_list: list[float] = []

    # 从 rewards 提取
    for rec in rewards:
        detail = rec.get("detail", {})
        if "reads" in detail:
            reads_list.append(detail["reads"])
        if "read_through" in detail:
            read_through_list.append(detail["read_through"])

    # 若 rewards 为空，从 feedback 补充
    if not reads_list and not read_through_list:
        for rec in feedback:
            if "reads" in rec:
                reads_list.append(rec["reads"])
            if "read_through" in rec:
                read_through_list.append(rec["read_through"])

    return {
        "article_count": max(len(reads_list), len(read_through_list)),
        "avg_reads": round(mean(reads_list), 2) if reads_list else None,
        "avg_read_through": round(mean(read_through_list), 4) if read_through_list else None,
    }


# =========================================================================
# 面板输出
# =========================================================================

def _build_panel(states: list[dict], rewards: list[dict],
                 feedback: list[dict]) -> dict:
    """构建完整面板数据"""
    phase_progress = _compute_phase_progress(states)
    lead_times = _compute_lead_time(states)
    qa_retries = _compute_qa_retries(states)
    phase_pass_rate = _compute_phase_pass_rate(states)
    publish_metrics = _compute_publish_metrics(rewards, feedback)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_topics": len(states),
        "phase_progress": phase_progress,
        "lead_time": {
            "items": lead_times,
            "avg_hours": round(mean(lt["duration_hours"] for lt in lead_times), 2)
            if lead_times else None,
        },
        "qa_retries": {
            "items": qa_retries,
            "avg_retries": round(mean(r["retries"] for r in qa_retries), 2)
            if qa_retries else None,
        },
        "phase_pass_rate": phase_pass_rate,
        "publish_metrics": publish_metrics,
    }


def _render_text_panel(panel: dict) -> str:
    """将面板数据渲染为可读文本"""
    lines = []
    lines.append("=" * 64)
    lines.append("  A5 可观测性面板")
    lines.append(f"  生成时间: {panel['generated_at']}")
    lines.append(f"  统计 topic 数: {panel['total_topics']}")
    lines.append("=" * 64)

    # 1) 各 topic 的 phase 进度
    lines.append("")
    lines.append("--- Phase 进度 ---")
    progress = panel.get("phase_progress", {})
    if not progress:
        lines.append("  (无状态文件)")
    for key, info in progress.items():
        lines.append(f"  [{info['slug']}] {info['date']}  mode={info['mode']}")
        for phase, pdata in info.get("phases", {}).items():
            status_icon = {"completed": "+", "failed": "X", "pending": ".",
                           "skipped": "-", "in_progress": "~"}.get(pdata["status"], "?")
            lines.append(
                f"    Phase {phase}: [{status_icon}] {pdata['status']}"
                f"  ({pdata['completed']}/{pdata['total']} done"
                f", {pdata['failed']} failed, {pdata['pending']} pending)"
            )

    # 2) 选题到发布耗时
    lines.append("")
    lines.append("--- 选题到发布耗时 ---")
    lt = panel.get("lead_time", {})
    if not lt.get("items"):
        lines.append("  (无已完成发布)")
    else:
        for item in lt["items"]:
            lines.append(
                f"  {item['slug']} ({item['date']}): {item['duration_hours']}h"
            )
        lines.append(f"  平均耗时: {lt['avg_hours']}h")

    # 3) QA 迭代次数
    lines.append("")
    lines.append("--- QA 迭代次数 ---")
    qa = panel.get("qa_retries", {})
    if not qa.get("items"):
        lines.append("  (无数据)")
    else:
        for item in qa["items"]:
            lines.append(f"  {item['slug']} ({item['date']}): {item['retries']} 轮")
        lines.append(f"  平均迭代: {qa['avg_retries']} 轮")

    # 4) 各 phase 通过率
    lines.append("")
    lines.append("--- Phase 通过率 ---")
    ppr = panel.get("phase_pass_rate", {})
    for phase in PHASE_ORDER:
        if phase not in ppr:
            continue
        data = ppr[phase]
        rate_str = f"{data['pass_rate'] * 100:.1f}%" if data["pass_rate"] is not None else "N/A"
        lines.append(
            f"  Phase {phase}: {rate_str}"
            f"  (通过={data['completed']}, 失败={data['failed']}, 总计={data['total']})"
        )

    # 5) 已发布文章效果
    lines.append("")
    lines.append("--- 已发布文章效果 ---")
    pm = panel.get("publish_metrics", {})
    if pm.get("article_count", 0) == 0:
        lines.append("  (无发布反馈数据)")
    else:
        lines.append(f"  文章数: {pm['article_count']}")
        avg_r = pm.get("avg_reads")
        lines.append(f"  平均阅读数: {avg_r if avg_r is not None else 'N/A'}")
        avg_rt = pm.get("avg_read_through")
        lines.append(
            f"  平均完读率: {avg_rt * 100:.1f}%" if avg_rt is not None
            else "  平均完读率: N/A"
        )

    lines.append("")
    lines.append("=" * 64)
    return "\n".join(lines)


# =========================================================================
# CLI 入口
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="A5 可观测性面板 — 微信管线全局指标汇总"
    )
    parser.add_argument(
        "topic", nargs="?", default=None,
        help="可选：只看指定 topic/slug 的指标"
    )
    parser.add_argument(
        "--date", default=None,
        help="可选：只看指定日期 (YYYY-MM-DD) 的指标"
    )
    args = parser.parse_args()

    # 加载数据
    states = _load_state_files(topic_filter=args.topic, date_filter=args.date)
    rewards = _load_topic_rewards()
    feedback = _load_style_feedback()

    # 构建面板
    panel = _build_panel(states, rewards, feedback)

    # 输出 JSON
    print(json.dumps(panel, ensure_ascii=False, indent=2))

    # 输出可读文本面板（到 stderr，不影响 JSON stdout 解析）
    text = _render_text_panel(panel)
    print(text, file=sys.stderr)


if __name__ == "__main__":
    main()
