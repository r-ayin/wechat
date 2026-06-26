#!/usr/bin/env python3
"""predictive_scanner.py -- HS-OPT-04 预测性选题扫描器

两个子命令：
  calendar  基于 watch_list 的 schedule/frequency 字段 + 内置日历事件，
            输出未来 7 天将触发的选题（提前 72h 标记 rising）
  rising    对 scan-results.json 中 active_signals 按时间序列计算讨论量
            变化率，标记 |斜率|>阈值 且未到峰的为 rising

输出 JSON:
  {
    "predictive_topics": [{topic, trigger_date, reason, priority_boost}, ...],
    "rising": [...]
  }

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 项目根 = scripts/ 的父目录
_ROOT = Path(__file__).resolve().parent.parent

# =========================================================================
# 默认文件路径
# =========================================================================
_DEFAULT_HOT_WATCH = _ROOT / "topic-pool" / "hot-watch.json"
_DEFAULT_SCAN_RESULTS = _ROOT / "topic-pool" / "scan-results.json"

# =========================================================================
# 内置日历事件列表（可后续外置为 JSON 配置）
# 格式：(月, 日, 名称, 关联支柱)
# 日=0 表示该月全月关注（月度事件）
# 日范围用元组 (start_day, end_day)
# =========================================================================
_BUILTIN_CALENDAR: list[dict] = [
    # --- 一月 ---
    {"month": 1, "day": 1, "name": "元旦/新年新规生效", "pillar": "城市与生存"},
    # --- 三月 ---
    {"month": 3, "day": 3, "name": "全国两会开幕", "pillar": "劳动与阶级"},
    {"month": 3, "day": 5, "name": "政府工作报告", "pillar": "劳动与阶级"},
    {"month": 3, "day": 8, "name": "三八妇女节/性别议题", "pillar": "城市与生存"},
    {"month": 3, "day": 15, "name": "315消费者权益日", "pillar": "技术与权力"},
    # --- 五月 ---
    {"month": 5, "day": 1, "name": "五一劳动节/劳动权益", "pillar": "劳动与阶级"},
    {"month": 5, "day": 4, "name": "五四青年节/青年议题", "pillar": "教育与阶层"},
    # --- 六月 ---
    {"month": 6, "day": 1, "name": "六一儿童节/留守儿童", "pillar": "城市与生存"},
    {"month": 6, "day": 7, "name": "高考开始", "pillar": "教育与阶层"},
    {"month": 6, "day": 8, "name": "高考结束", "pillar": "教育与阶层"},
    {"month": 6, "day": 23, "name": "高考出分（各省陆续）", "pillar": "教育与阶层"},
    {"month": 6, "day": 24, "name": "高考出分（各省陆续）", "pillar": "教育与阶层"},
    {"month": 6, "day": 25, "name": "高考出分（各省陆续）", "pillar": "教育与阶层"},
    # --- 七月 ---
    {"month": 7, "day": 1, "name": "7月1日新规生效（年中法规集中施行）", "pillar": "劳动与阶级"},
    {"month": 7, "day": 1, "name": "社保年度基数调整（7月起）", "pillar": "城市与生存"},
    {"month": 7, "day": 1, "name": "公积金年度调整（7月起）", "pillar": "城市与生存"},
    # --- 八月 ---
    {"month": 8, "day": 15, "name": "高校录取通知书发放高峰", "pillar": "教育与阶层"},
    # --- 九月 ---
    {"month": 9, "day": 1, "name": "开学季/教育政策", "pillar": "教育与阶层"},
    {"month": 9, "day": 10, "name": "教师节/教育议题", "pillar": "教育与阶层"},
    # --- 十月 ---
    {"month": 10, "day": 1, "name": "国庆/10月新规生效", "pillar": "城市与生存"},
    {"month": 10, "day": 10, "name": "世界精神卫生日", "pillar": "心理与规训"},
    # --- 十一月 ---
    {"month": 11, "day": 11, "name": "双十一/消费主义批判", "pillar": "技术与权力"},
    # --- 十二月 ---
    {"month": 12, "day": 1, "name": "世界艾滋病日/公共卫生", "pillar": "城市与生存"},
    {"month": 12, "day": 4, "name": "国家宪法日", "pillar": "劳动与阶级"},
]

# =========================================================================
# frequency 到天数的映射（用于 watch_list 的周期性触发判断）
# =========================================================================
_FREQ_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
    "quarterly": 90,
}

# rising 检测阈值：score 变化率（绝对值）超过此值视为 rising
_RISING_SLOPE_THRESHOLD = 0.5


# =========================================================================
# 工具函数
# =========================================================================

def _load_json(path: Path) -> dict | list:
    """加载 JSON 文件，文件不存在时返回空 dict。"""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _today() -> datetime:
    """返回当前日期（零时），方便测试时 mock。"""
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def _date_in_window(month: int, day: int, ref: datetime, window_days: int = 7) -> str | None:
    """检查 (month, day) 对应的年份日期是否在 ref 起未来 window_days 天内。
    若在窗口内，返回 'YYYY-MM-DD' 字符串；否则返回 None。
    会检查当年和次年（处理跨年窗口）。
    """
    for year in (ref.year, ref.year + 1):
        try:
            target = datetime(year, month, day)
        except ValueError:
            # 处理 2月29 等无效日期
            continue
        delta = (target - ref).days
        if 0 <= delta <= window_days:
            return target.strftime("%Y-%m-%d")
    return None


# =========================================================================
# 子命令：calendar
# =========================================================================

def cmd_calendar(hot_watch_path: Path, window_days: int = 7) -> list[dict]:
    """扫描内置日历事件 + watch_list 的 frequency 项，输出未来 window_days 天触发的选题。"""
    today = _today()
    window_end = today + timedelta(days=window_days)
    # 72 小时阈值：3 天内触发的标记 rising
    rising_threshold = timedelta(hours=72)
    results: list[dict] = []

    # --- 1. 内置日历事件 ---
    for evt in _BUILTIN_CALENDAR:
        trigger_str = _date_in_window(evt["month"], evt["day"], today, window_days)
        if trigger_str is not None:
            trigger_date = datetime.strptime(trigger_str, "%Y-%m-%d")
            days_until = (trigger_date - today).days
            is_rising = days_until <= 3  # 72h 内

            entry = {
                "topic": evt["name"],
                "trigger_date": trigger_str,
                "reason": f"内置日历事件（{evt['pillar']}）",
                "priority_boost": 2.0 if is_rising else 1.0,
                "source": "builtin_calendar",
                "pillar": evt["pillar"],
            }
            if is_rising:
                entry["rising"] = True
                entry["rising_reason"] = f"距触发仅 {days_until} 天，进入 72h 预备窗口"
            results.append(entry)

    # --- 2. watch_list 中带 frequency 的项 ---
    data = _load_json(hot_watch_path)
    watch_list = data.get("watch_list", []) if isinstance(data, dict) else []

    for item in watch_list:
        freq = item.get("frequency") or item.get("schedule")
        if not freq:
            continue

        freq_lower = freq.lower().strip()
        cycle_days = _FREQ_DAYS.get(freq_lower)
        if cycle_days is None:
            # 尝试解析 "every N days" 格式
            import re
            m = re.match(r"every\s+(\d+)\s+days?", freq_lower)
            if m:
                cycle_days = int(m.group(1))
            else:
                # 未知频率，按 weekly 处理
                cycle_days = 7

        # 周期性事件：如果 cycle_days <= window_days，则一定在窗口内触发
        # 我们把"下次触发日"设为 today + cycle_days（简化假设：上次触发在今天之前）
        if cycle_days <= window_days:
            trigger_date = today + timedelta(days=min(cycle_days, window_days))
            trigger_str = trigger_date.strftime("%Y-%m-%d")
            days_until = min(cycle_days, window_days)
            is_rising = days_until <= 3

            entry = {
                "topic": item.get("keyword", item.get("id", "未知")),
                "trigger_date": trigger_str,
                "reason": f"watch_list 周期触发（{freq}，{item.get('pillar', '未知')}）: {item.get('expected_event', '')}",
                "priority_boost": 1.5 if is_rising else 0.5,
                "source": "watch_list",
                "pillar": item.get("pillar", ""),
                "watch_id": item.get("id", ""),
                "frequency": freq,
            }
            if is_rising:
                entry["rising"] = True
                entry["rising_reason"] = f"周期 {cycle_days} 天，下次触发在 72h 内"
            results.append(entry)

        # 如果 watch_list 项有 schedule 字段（具体日期）
        schedule = item.get("schedule")
        if schedule and isinstance(schedule, str):
            try:
                sched_date = datetime.strptime(schedule, "%Y-%m-%d")
                delta = (sched_date - today).days
                if 0 <= delta <= window_days:
                    is_rising = delta <= 3
                    entry = {
                        "topic": item.get("keyword", item.get("id", "未知")),
                        "trigger_date": schedule,
                        "reason": f"watch_list 指定日期触发（{item.get('pillar', '未知')}）: {item.get('expected_event', '')}",
                        "priority_boost": 2.0 if is_rising else 1.0,
                        "source": "watch_list_schedule",
                        "pillar": item.get("pillar", ""),
                        "watch_id": item.get("id", ""),
                    }
                    if is_rising:
                        entry["rising"] = True
                        entry["rising_reason"] = f"距指定日期仅 {delta} 天"
                    results.append(entry)
            except ValueError:
                pass

    # 按 priority_boost 降序，trigger_date 升序排列
    results.sort(key=lambda x: (-x["priority_boost"], x["trigger_date"]))
    return results


# =========================================================================
# 子命令：rising
# =========================================================================

def cmd_rising(
    hot_watch_path: Path,
    scan_results_path: Path,
    slope_threshold: float = _RISING_SLOPE_THRESHOLD,
) -> list[dict]:
    """分析 scan-results.json 中的记录，按时间序列计算讨论量/score 变化率。
    标记 |斜率| > 阈值 且 未到峰的为 rising。

    时间序列逻辑：
    - 按 query/title 分组
    - 按 scanned_at 时间排序
    - 计算相邻两次 score 的变化率（斜率 = delta_score / delta_hours）
    - 如果最近一次斜率 > 0 且绝对值 > 阈值 → rising（还没到峰）
    - 如果最近斜率 < 0 → 已过峰，不标记
    """
    scan_data = _load_json(scan_results_path)
    if not isinstance(scan_data, list):
        scan_data = []

    # 同时读 active_signals 作为补充
    hw_data = _load_json(hot_watch_path)
    active_signals = hw_data.get("active_signals", []) if isinstance(hw_data, dict) else []

    # --- 按 query/title 分组 scan_results ---
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)

    for rec in scan_data:
        key = rec.get("query") or rec.get("title") or rec.get("angle", "")
        if not key:
            continue
        groups[key].append(rec)

    results: list[dict] = []

    for key, records in groups.items():
        # 按 scanned_at 排序
        def _parse_time(r: dict) -> datetime:
            ts = r.get("scanned_at", "")
            for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
                try:
                    return datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    pass
            return datetime.min

        records_sorted = sorted(records, key=_parse_time)

        # 至少需要 1 条记录来评估；如果只有 1 条，用 score 本身判断
        if len(records_sorted) == 0:
            continue

        latest = records_sorted[-1]
        latest_score = latest.get("score") or latest.get("total") or 0

        if len(records_sorted) >= 2:
            prev = records_sorted[-2]
            prev_score = prev.get("score") or prev.get("total") or 0

            # 计算时间差（小时）
            t_latest = _parse_time(latest)
            t_prev = _parse_time(prev)
            delta_hours = max((t_latest - t_prev).total_seconds() / 3600, 0.1)

            slope = (latest_score - prev_score) / delta_hours

            # 判断：斜率>0 且 绝对值>阈值 → rising（还没到峰）
            if slope > 0 and abs(slope) >= slope_threshold:
                results.append({
                    "topic": key,
                    "latest_score": latest_score,
                    "prev_score": prev_score,
                    "slope": round(slope, 4),
                    "delta_hours": round(delta_hours, 2),
                    "status": "rising",
                    "pillar": latest.get("pillar", ""),
                    "source": latest.get("source", ""),
                    "scanned_at": latest.get("scanned_at", ""),
                })
        else:
            # 单条记录：高分项也值得关注（score >= 7 视为潜在 rising）
            if latest_score >= 7:
                results.append({
                    "topic": key,
                    "latest_score": latest_score,
                    "prev_score": None,
                    "slope": None,
                    "delta_hours": None,
                    "status": "rising_single_point",
                    "pillar": latest.get("pillar", ""),
                    "source": latest.get("source", ""),
                    "scanned_at": latest.get("scanned_at", ""),
                    "note": "仅一次扫描记录，基于高分推断",
                })

    # 按 latest_score 降序排序
    results.sort(key=lambda x: -(x.get("latest_score") or 0))
    return results


# =========================================================================
# CLI 入口
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="HS-OPT-04 预测性选题扫描器：日历触发 + rising 趋势检测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例：
  # 扫描未来 7 天日历事件 + watch_list 周期触发
  python predictive_scanner.py calendar

  # 检测 rising 趋势
  python predictive_scanner.py rising

  # 同时执行（默认）
  python predictive_scanner.py calendar rising

  # 指定输入文件
  python predictive_scanner.py calendar --hot-watch /path/to/hot-watch.json
""",
    )
    parser.add_argument(
        "commands",
        nargs="*",
        default=["calendar", "rising"],
        choices=["calendar", "rising"],
        help="子命令：calendar（日历触发）、rising（趋势检测）。默认两者都执行",
    )
    parser.add_argument(
        "--hot-watch",
        type=Path,
        default=_DEFAULT_HOT_WATCH,
        help=f"hot-watch.json 路径（默认: {_DEFAULT_HOT_WATCH}）",
    )
    parser.add_argument(
        "--scan-results",
        type=Path,
        default=_DEFAULT_SCAN_RESULTS,
        help=f"scan-results.json 路径（默认: {_DEFAULT_SCAN_RESULTS}）",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=7,
        help="日历扫描窗口天数（默认: 7）",
    )
    parser.add_argument(
        "--slope-threshold",
        type=float,
        default=_RISING_SLOPE_THRESHOLD,
        help=f"rising 斜率阈值（默认: {_RISING_SLOPE_THRESHOLD}）",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    output: dict = {}

    commands = args.commands if args.commands else ["calendar", "rising"]

    if "calendar" in commands:
        output["predictive_topics"] = cmd_calendar(
            hot_watch_path=args.hot_watch,
            window_days=args.window,
        )

    if "rising" in commands:
        output["rising"] = cmd_rising(
            hot_watch_path=args.hot_watch,
            scan_results_path=args.scan_results,
            slope_threshold=args.slope_threshold,
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
