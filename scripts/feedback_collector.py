#!/usr/bin/env python3
"""feedback_collector.py — A1 跨阶段反馈闭环入口

post-publish 数据回传管线入口。CLI 子命令：

  ingest <slug> --reads N --read-through F --shares N --comments N --sentiment F
      1) 调 style_evolution.record 记录反馈到 style_feedback.jsonl
      2) 计算综合 reward = 0.4*read_through + 0.3*share_rate + 0.3*sentiment
         追加写入 output/state/topic_reward.jsonl（供选题池 UCB 排序）

  report
      汇总 topic_reward.jsonl，按 reward 降序输出各选题排序，
      供 hot-scanner 选题池排序参考

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 项目根 & 路径常量
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _ROOT / "output" / "state"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

# topic_reward 数据文件（JSONL 格式，每行一条 {slug, reward, ...}）
_REWARD_FILE = _STATE_DIR / "topic_reward.jsonl"

# 引入 style_evolution 的 record 功能
sys.path.insert(0, str(_ROOT / "scripts"))


# =========================================================================
# 工具函数
# =========================================================================

def _compute_reward(read_through: float, shares: int, reads: int,
                    sentiment: float) -> float:
    """计算综合 reward 分数，供选题池 UCB 排序

    公式：reward = 0.4 * read_through + 0.3 * share_rate + 0.3 * sentiment
    - read_through: 完读率 [0, 1]
    - share_rate: 分享率 = shares / max(reads, 1)（归一化到 [0, 1]，上限截断）
    - sentiment: 情感得分 [-1, 1]，映射到 [0, 1] 后参与计算
    """
    # 分享率：shares / reads，截断到 [0, 1]
    share_rate = min(shares / max(reads, 1), 1.0)
    # 情感得分从 [-1, 1] 映射到 [0, 1]
    sentiment_norm = (sentiment + 1.0) / 2.0
    reward = 0.4 * read_through + 0.3 * share_rate + 0.3 * sentiment_norm
    return round(reward, 4)


def _sanitize_slug(raw: str) -> str:
    """清洗 CLI 传入的 slug，防止 JSONL log injection / 下游解析破坏。

    - 剥离换行/回车/tab（JSONL 一行一记录，嵌入换行会伪造新记录）
    - 剥离其他 C0/C1 控制字符（U+0000-U+001F, U+007F-U+009F）
    - 截断到 200 字符，避免单条 record 撑爆下游 buffer
    - 空串兜底为 'unknown'
    """
    import re
    # 一步剥掉所有控制字符（含 \n\r\t），保留可打印 Unicode
    cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw or "")
    cleaned = cleaned.strip()[:200]
    return cleaned or "unknown"


def _append_reward(slug: str, reward: float, detail: dict) -> None:
    """追加一条 reward 记录到 topic_reward.jsonl"""
    safe_slug = _sanitize_slug(slug)
    record = {
        "slug": safe_slug,
        "reward": reward,
        "detail": detail,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(_REWARD_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_rewards() -> list[dict]:
    """从 topic_reward.jsonl 加载所有 reward 记录"""
    if not _REWARD_FILE.exists():
        return []
    records = []
    with open(_REWARD_FILE, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[警告] topic_reward.jsonl 第 {line_no} 行 JSON 解析失败，跳过",
                      file=sys.stderr)
    return records


# =========================================================================
# ingest 子命令：数据回传 + reward 计算
# =========================================================================

def cmd_ingest(args: argparse.Namespace) -> int:
    """接收 post-publish 数据，记录反馈并计算 reward"""

    # --- 1) 调 style_evolution.record 记录到 style_feedback.jsonl ---
    # 构造与 style_evolution.cmd_record 兼容的 Namespace
    import style_evolution  # noqa: E402  延迟导入，避免顶层循环依赖

    record_ns = argparse.Namespace(
        slug=args.slug,
        reads=args.reads,
        read_through=args.read_through,
        shares=args.shares,
        comments=args.comments,
        comment_sentiment=args.sentiment,
        publish_date=None,
    )
    rc = style_evolution.cmd_record(record_ns)
    if rc != 0:
        # style_evolution.record 已打印错误信息
        return rc

    # --- 2) 计算综合 reward 并追加到 topic_reward.jsonl ---
    share_rate = min(args.shares / max(args.reads, 1), 1.0)
    sentiment_norm = (args.sentiment + 1.0) / 2.0
    reward = _compute_reward(
        read_through=args.read_through,
        shares=args.shares,
        reads=args.reads,
        sentiment=args.sentiment,
    )

    detail = {
        "reads": args.reads,
        "read_through": args.read_through,
        "shares": args.shares,
        "comments": args.comments,
        "sentiment": args.sentiment,
        "share_rate": round(share_rate, 4),
        "sentiment_norm": round(sentiment_norm, 4),
    }
    _append_reward(args.slug, reward, detail)

    # 输出结果
    result = {
        "status": "ingested",
        "slug": args.slug,
        "reward": reward,
        "formula": "0.4*read_through + 0.3*share_rate + 0.3*sentiment_norm",
        "components": {
            "read_through": args.read_through,
            "share_rate": round(share_rate, 4),
            "sentiment_norm": round(sentiment_norm, 4),
        },
        "reward_file": str(_REWARD_FILE),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# =========================================================================
# report 子命令：汇总 reward 排序
# =========================================================================

def cmd_report(args: argparse.Namespace) -> int:
    """汇总 topic_reward.jsonl，按 reward 降序输出各选题排序"""
    records = _load_rewards()

    if not records:
        result = {
            "status": "no_data",
            "message": "未找到 reward 数据，请先使用 ingest 子命令录入发布反馈",
            "reward_file": str(_REWARD_FILE),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 按 slug 聚合（同一选题可能有多条记录，取最新一条的 reward）
    slug_latest: dict[str, dict] = {}
    for rec in records:
        slug = rec.get("slug", "unknown")
        # 保留最新记录（后出现的覆盖前面的）
        slug_latest[slug] = rec

    # 按 reward 降序排序
    sorted_slugs = sorted(
        slug_latest.values(),
        key=lambda r: r.get("reward", 0),
        reverse=True,
    )

    # 构造排序输出
    ranking = []
    for rank, rec in enumerate(sorted_slugs, 1):
        ranking.append({
            "rank": rank,
            "slug": rec.get("slug"),
            "reward": rec.get("reward"),
            "detail": rec.get("detail"),
            "recorded_at": rec.get("recorded_at"),
        })

    result = {
        "status": "ok",
        "total_topics": len(ranking),
        "total_records": len(records),
        "ranking": ranking,
        "note": "按 reward 降序排列，供 hot-scanner 选题池 UCB 排序参考",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# =========================================================================
# CLI 入口
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="A1 跨阶段反馈闭环入口 — post-publish 数据回传管线"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # --- ingest 子命令 ---
    p_ingest = subparsers.add_parser(
        "ingest",
        help="录入 post-publish 反馈数据，记录到 style_feedback 并计算 reward",
    )
    p_ingest.add_argument("slug", help="文章/选题 slug 标识符")
    p_ingest.add_argument("--reads", type=int, required=True,
                          help="阅读数")
    p_ingest.add_argument("--read-through", type=float, required=True,
                          help="完读率 (0.0~1.0)")
    p_ingest.add_argument("--shares", type=int, required=True,
                          help="分享数")
    p_ingest.add_argument("--comments", type=int, required=True,
                          help="评论数")
    p_ingest.add_argument("--sentiment", type=float, required=True,
                          help="情感得分 (-1.0~1.0)")

    # --- report 子命令 ---
    subparsers.add_parser(
        "report",
        help="汇总 topic_reward.jsonl，输出各选题 reward 排序",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "ingest":
        sys.exit(cmd_ingest(args))
    elif args.command == "report":
        sys.exit(cmd_report(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
