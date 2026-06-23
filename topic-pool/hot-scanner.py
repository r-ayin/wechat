#!/usr/bin/env python3
"""
热点扫描器 v1.0 — 多信源实时热点发现 + 选题评分 + 选题池注入

扫描策略:
  ① 关键词搜索 — WebSearch 扫描 watch_list 关键词的最新动态
  ② 跨平台热榜 — 知乎/微博/百度热榜 (WebFetch)
  ③ 竞品监测 — T1 对标账号新内容监控
  ④ 信号评分 — 热点质量 × 支柱匹配 × 时效性

用法:
  python hot-scanner.py scan              # 扫描所有信源, 输出新选题
  python hot-scanner.py scan --pillar 劳动  # 仅扫描指定支柱
  python hot-scanner.py scan --output pool.json  # 输出到选题池
  python hot-scanner.py report            # 生成热点简报
  python hot-scanner.py watch             # 列出当前监控关键词

依赖: requests, json (标准库)
"""

import json
import sys
import io
from datetime import datetime, timezone
from pathlib import Path

# 跨平台编码
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_SCRIPT_DIR = Path(__file__).resolve().parent
_HOT_WATCH = _SCRIPT_DIR / "hot-watch.json"
_EVERGREEN_POOL = _SCRIPT_DIR / "evergreen-pool.json"

# =========================================================================
# 支柱关键词映射
# =========================================================================

PILLAR_KEYWORDS = {
    "劳动与阶级": [
        "最低工资 调整", "加班 劳动仲裁", "灵活就业 权益",
        "新就业形态 立法", "过劳死 工伤认定", "外卖骑手 权益",
        "网约车 司机 收入", "平台经济 劳动关系", "AI替代 裁员",
    ],
    "技术与权力": [
        "人脸识别 隐私 处罚", "AI 监管 新规", "算法 大数据杀熟",
        "社会信用体系 进展", "AI数据标注 工人", "深度伪造 诈骗",
        "数据安全 个人信息保护", "AI伦理 争议", "自动驾驶 事故 责任",
    ],
    "心理与规训": [
        "青少年心理健康 政策", "抑郁症 诊断 数据", "ADHD 诊断 上升",
        "心理咨询 行业 监管", "精神科药物 滥用", "校园心理筛查",
    ],
    "教育与阶层": [
        "高考改革 新政策", "双减 效果 评估", "职业教育 改革",
        "考研 报名人数", "学区房 政策", "学历贬值 就业",
        "中考分流", "大学生就业率",
    ],
    "城市与生存": [
        "房价 调控 新政", "房租 上涨", "最低工资 调整",
        "社保 改革", "消费降级 趋势", "城中村 改造",
        "通勤 时间 数据", "房贷利率",
    ],
}

# =========================================================================
# 扫描引擎
# =========================================================================

def build_search_queries(pillar: str = None) -> list[dict]:
    """从关键词表构建搜索查询列表

    Args:
        pillar: 限定支柱（None = 全部）

    Returns:
        [{"pillar": "劳动与阶级", "query": "...", "source": "keyword"}]
    """
    queries = []
    pillars = [pillar] if pillar else PILLAR_KEYWORDS.keys()

    for p in pillars:
        keywords = PILLAR_KEYWORDS.get(p, [])
        for kw in keywords:
            queries.append({
                "pillar": p,
                "query": kw,
                "source": "keyword_watch",
            })

    # 也扫描跨平台热榜关键词
    cross_platform = [
        ("知乎热榜 今日", "cross"),
        ("微博热搜 今日 社会", "cross"),
        ("抖音热点 本周 社会", "cross"),
    ]
    for q, src in cross_platform:
        queries.append({
            "pillar": "cross",
            "query": q,
            "source": "hotlist",
        })

    return queries


# =========================================================================
# 信号评分
# =========================================================================

def score_signal(topic: dict) -> float:
    """对热点信号进行多维度评分

    维度:
      - 受众痛点 (0-10): 影响多少人、影响多深
      - 信息差程度 (0-10): 普通人知道多少 vs 应该知道多少
      - 争议性 (0-10): 是否存在对立观点/讨论空间
      - 时效性 (0-10): 现在是讨论的最佳时机吗
    """
    pillar = topic.get("pillar", "未分类")

    # 基础分: 劳动和城市议题天然高痛点
    base_scores = {
        "劳动与阶级": (9, 8, 8),
        "技术与权力": (8, 9, 8),
        "心理与规训": (7, 8, 9),
        "教育与阶层": (9, 8, 8),
        "城市与生存": (9, 7, 7),
    }
    pain, info_gap, controversy = base_scores.get(pillar, (6, 6, 6))

    # 时效性: 话题含"新""最新""2026"加分
    timeliness = 7
    title = topic.get("title", "") + topic.get("angle", "")
    time_keywords = ["新规", "最新", "刚刚", "发布", "通过", "实施", "生效", "2026"]
    if any(kw in title for kw in time_keywords):
        timeliness = 9

    # 综合评分
    score = (pain * 0.3 + info_gap * 0.3 + controversy * 0.2 + timeliness * 0.2)
    return round(score, 1)


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="热点扫描器 v1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    scan = sub.add_parser("scan", help="扫描热点选题")
    scan.add_argument("--pillar", default=None, help="限定支柱")
    scan.add_argument("--output", default=None, help="输出JSON路径 (追加模式)")
    scan.add_argument("--max-results", type=int, default=10, help="最大结果数")

    # watch
    _watch = sub.add_parser("watch", help="列出监控关键词")

    # consume: 消费 WebSearch 结果, 生成选题建议
    consume = sub.add_parser("consume", help="消费 WebSearch 结果, 输出评分选题")
    consume.add_argument("results_json", help="WebSearch 结果 JSON: {query: summary}")
    consume.add_argument("--output", default=None, help="输出到选题池 JSON")
    consume.add_argument("--min-score", type=float, default=6.0, help="最低评分阈值")

    # report
    _report = sub.add_parser("report", help="生成热点简报")

    args = parser.parse_args()

    if args.command == "scan":
        queries = build_search_queries(args.pillar)

        print(f"=== 热点扫描: {len(queries)} 条查询 ===")
        print(f"   限定支柱: {args.pillar or '全部'}")
        print(f"   扫描时间: {datetime.now(timezone.utc).isoformat()}")
        print()

        # 按支柱分组显示查询
        by_pillar = {}
        for q in queries:
            by_pillar.setdefault(q["pillar"], []).append(q)

        results = []
        for pillar, qs in by_pillar.items():
            print(f"## {pillar} ({len(qs)} 查询)")
            for q in qs[:5]:  # 每支柱显示前5条
                print(f"  - {q['query']}")
                topic = {
                    "pillar": pillar,
                    "query": q["query"],
                    "source": q["source"],
                    "score": score_signal({"pillar": pillar, "title": q["query"]}),
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                }
                results.append(topic)
            if len(qs) > 5:
                print(f"  ... 还有 {len(qs)-5} 条")
            print()

        # 按评分排序
        results.sort(key=lambda r: r["score"], reverse=True)
        top = results[:args.max_results]

        print(f"=== TOP {len(top)} 候选选题 ===")
        for i, r in enumerate(top):
            print(f"  {i+1}. [{r['pillar']}] {r['query']} (评分: {r['score']})")

        if args.output:
            output_path = Path(args.output)
            existing = []
            if output_path.exists():
                existing = json.loads(output_path.read_text(encoding='utf-8'))

            # 去重追加
            existing_queries = {t.get("query") for t in existing if isinstance(t, dict)}
            new_topics = [r for r in top if r["query"] not in existing_queries]

            merged = existing + new_topics
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            print(f"\n[OK] {len(new_topics)} 个新选题已写入 {args.output}")

    elif args.command == "consume":
        with open(args.results_json, 'r', encoding='utf-8') as f:
            search_results = json.load(f)

        topics = []
        for query, summary in search_results.items():
            if not summary or len(summary.strip()) < 30:
                continue

            # 支柱匹配
            matched_pillar = "未分类"
            for pillar, keywords in PILLAR_KEYWORDS.items():
                if any(kw in query for kw in keywords):
                    matched_pillar = pillar
                    break

            topic = {
                "query": query,
                "summary": summary[:200],
                "pillar": matched_pillar,
                "score": score_signal({"pillar": matched_pillar, "title": query}),
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }
            topics.append(topic)

        topics.sort(key=lambda t: t["score"], reverse=True)
        qualified = [t for t in topics if t["score"] >= args.min_score]

        print(f"=== 消费 WebSearch 结果 ===")
        print(f"  输入: {len(search_results)} 查询 → {len(topics)} 有效结果")
        print(f"  通过阈值 ({args.min_score}): {len(qualified)} 选题")
        print()

        for i, t in enumerate(qualified[:15]):
            print(f"  {i+1}. [{t['pillar']}] {t['query']} (评分: {t['score']})")
            print(f"     {t['summary'][:120]}...")
            print()

        if args.output:
            output_path = Path(args.output)
            existing = []
            if output_path.exists():
                existing = json.loads(output_path.read_text(encoding='utf-8'))

            existing_queries = {t.get("query") for t in existing if isinstance(t, dict)}
            new_topics = [t for t in qualified if t["query"] not in existing_queries]

            merged = existing + new_topics
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            print(f"[OK] {len(new_topics)} 个新选题已注入 {args.output}")

    elif args.command == "watch":
        print("=== 当前监控关键词 ===\n")
        for pillar, keywords in PILLAR_KEYWORDS.items():
            print(f"## {pillar}")
            for kw in keywords:
                print(f"  - {kw}")
            print()

        # 也读取 hot-watch.json
        if _HOT_WATCH.exists():
            watch_data = json.loads(_HOT_WATCH.read_text(encoding='utf-8'))
            watch_list = watch_data.get("watch_list", [])
            if watch_list:
                print(f"## 专项监控 ({len(watch_list)} 项)")
                for w in watch_list:
                    print(f"  - [{w['pillar']}] {w['keyword']} (频率: {w['frequency']})")

    elif args.command == "report":
        print("=== 热点简报 ===")
        print(f"生成时间: {datetime.now(timezone.utc).isoformat()}")
        print()

        # 热点信号统计
        if _HOT_WATCH.exists():
            watch_data = json.loads(_HOT_WATCH.read_text(encoding='utf-8'))
            signals = watch_data.get("active_signals", [])
            covered = [s for s in signals if s.get("status") == "covered"]
            pending = [s for s in signals if s.get("status") != "covered"]

            print(f"## 信号追踪")
            print(f"  已覆盖: {len(covered)}")
            print(f"  待覆盖: {len(pending)}")
            if pending:
                for s in pending:
                    print(f"    - {s.get('event', s.get('id'))}")
            print()

        # 选题池统计
        if _EVERGREEN_POOL.exists():
            pool = json.loads(_EVERGREEN_POOL.read_text(encoding='utf-8'))
            topics = pool.get("topics", [])
            ready = [t for t in topics if t.get("status") == "ready"]
            by_pillar = {}
            for t in ready:
                by_pillar.setdefault(t["pillar"], []).append(t)

            print(f"## 选题池 ({len(ready)} ready)")
            for pillar, ts in by_pillar.items():
                print(f"  {pillar}: {len(ts)} 篇")
                for t in ts:
                    print(f"    - [{t['id']}] {t['title']} (评分: {t.get('priority_score', '?')})")


if __name__ == "__main__":
    main()
