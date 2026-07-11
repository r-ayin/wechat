#!/usr/bin/env python3
"""
热点扫描器 v3.0 — LLM 驱动的真实内容评分

v2.0 → v3.0 核心转变:
  v2.0: 关键词字符串匹配 → 伪五维评分（"争议" in text → +2分）
  v3.0: DeepSeek 读摘要原文 → 真实内容评分（基于事实判断，非模板匹配）

v3.0 变更:
  ① consume 命令新增 --use-llm 模式（默认开启）：DeepSeek 对每条摘要做真实评分
  ② 保留 --no-llm 回退：纯本地关键词匹配（无 API key 时使用）
  ③ 移除常青池依赖：日报只展示当天搜索到的真实内容
  ④ 移除硬编码角度模板：角度由 LLM 从摘要中提取，不从预设模板选

用法:
  python hot-scanner.py scan              # 构建查询列表（输出到 stdout/JSON）
  python hot-scanner.py consume results.json     # 消费 WebSearch 结果 → 评分选题
  python hot-scanner.py watch             # 列出监控关键词
"""

import json
import sys
import io
import re
import os
import concurrent.futures as cf
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# 跨平台编码
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_SCRIPT_DIR = Path(__file__).resolve().parent
_HOT_WATCH = _SCRIPT_DIR / "hot-watch.json"

# =========================================================================
# 五支柱关键词映射 (用于构建搜索查询 + 支柱分类)
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
        "房价 调控 新政", "房租 上涨", "物业费 涨价 争议",
        "社保 改革", "消费降级 趋势", "城中村 改造",
        "通勤 时间 数据", "房贷利率",
    ],
}

# =========================================================================
# 事件触发关键词 (发现实时热点信号)
# =========================================================================

EVENT_TRIGGERS = {
    "劳动与阶级": [
        "人大代表 建议 工时", "两会 提案 劳动者", "政协委员 加班",
        "打工人 反对 热搜", "评论区 吵 上班时间",
        "裁员 抗议", "罢工 维权", "骑手 事故 平台",
        "最低工资 上调 争议", "灵活就业 新政",
    ],
    "技术与权力": [
        "AI 取代 工作 争议", "算法 歧视 投诉", "数据泄露 大规模",
        "人脸识别 争议 热搜", "平台 封号 维权",
        "自动驾驶 事故 责任 判决", "AI 生成 诈骗 案例",
    ],
    "心理与规训": [
        "抑郁症 热搜 孩子", "青少年 心理 危机 事件",
        "心理咨询 骗局 曝光", "精神科 误诊 故事",
        "考试 压力 自杀", "校园 心理筛查 争议",
    ],
    "教育与阶层": [
        "高考 改革 争议", "学历 贬值 热搜", "大学生 就业 难 热搜",
        "考研 报名 下降 上涨", "学区房 暴跌 暴涨",
        "职业教育 家长 反对", "中考分流 争议",
    ],
    "城市与生存": [
        "房价 降 不买 等", "房租 涨 打工人 热搜",
        "消费降级 年轻人 热搜", "社保 涨 负担",
        "城中村 改造 租客 安置", "通勤 极端 案例",
    ],
}


# =========================================================================
# DeepSeek LLM 评分 (v3.0 核心)
# =========================================================================

_LLM_SYSTEM = (
    "你是一名资深中文热点选题编辑。给你一个搜索查询词和搜索引擎抓回的网页摘要，"
    "你要判断这条内容作为微信公众号深度长文选题的价值。\n\n"
    "请严格基于摘要中的实际内容评分，不要猜测摘要中没有提到的信息。\n\n"
    "输出 JSON 对象，键如下：\n"
    "- headline: 10-25字真实热点标题（含具体事件/人物/数字，不要复制查询词）\n"
    "- digest: 60-120字事实摘要（含摘要中出现的具体事实）\n"
    "- angle: 一句话切入角度（从摘要内容推导，不要用模板套话）\n"
    "- pillar: 归属支柱（劳动与阶级/技术与权力/心理与规训/教育与阶层/城市与生存/未分类）\n"
    "- has_event: bool（是否有具体新闻事件）\n"
    "- has_controversy: bool（是否有对立/争议）\n"
    "- has_data: bool（是否有具体数据/数字）\n"
    "- relevance: 0-10 float（与当下社会热点的相关度，基于摘要内容判断）\n"
    "- depth: 0-10 float（能做深度分析的潜力，基于摘要中信息的丰富度）\n"
    "- novelty: 0-10 float（新颖/反直觉程度，基于摘要是否提供了意外视角）\n"
    "- narrative: 0-10 float（个人叙事空间，基于摘要中是否有具体人物/故事）\n"
    "- total: 0-10 float（综合评分 = relevance×0.3 + depth×0.25 + novelty×0.25 + narrative×0.2）\n\n"
    "如果摘要没有明确新闻事件或实质内容，headline 填 '(无明确热点)'，total 给低分。\n"
    "严格只输出一个 JSON 对象，不要 markdown 代码块，不要额外解释。"
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_LLM_TIMEOUT = 90
_LLM_MAX_TOKENS = 2000


def _llm_parse_json(content: str) -> dict | None:
    """从 LLM 响应中提取 JSON 对象。"""
    content = content.strip()
    m = _JSON_BLOCK_RE.search(content)
    raw = m.group(1) if m else content
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def _llm_score_one(query: str, summary: str, api_key: str, base_url: str,
                   model: str) -> dict | None:
    """调用 DeepSeek 对单条摘要做真实内容评分。"""
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": f"查询词: {query}\n搜索摘要:\n{summary[:1500]}"},
        ],
        "max_tokens": _LLM_MAX_TOKENS,
        "temperature": 0.3,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_LLM_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"  ⚠️ LLM 调用失败 [{query!r}]: {e}", file=sys.stderr)
        return None

    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        print(f"  ⚠️ LLM 响应结构异常 [{query!r}]", file=sys.stderr)
        return None

    obj = _llm_parse_json(content)
    if not obj:
        print(f"  ⚠️ LLM JSON 解析失败 [{query!r}]", file=sys.stderr)
        return None

    headline = (obj.get("headline") or "").strip()
    if not headline or headline in ("(无明确热点)", "（无明确热点）",
                                     "(无明确事件)", "（无明确事件）"):
        return None

    # 钳制分数到 0-10
    for key in ("relevance", "depth", "novelty", "narrative", "total"):
        val = obj.get(key, 0)
        try:
            obj[key] = max(0.0, min(10.0, float(val)))
        except (TypeError, ValueError):
            obj[key] = 0.0

    return obj


def llm_consume(search_results: dict, api_key: str, base_url: str,
                model: str, concurrency: int = 3,
                min_score: float = 0.0) -> list[dict]:
    """LLM 驱动的 consume：对每条搜索结果调用 DeepSeek 做真实评分。"""
    work = [(q, s) for q, s in search_results.items()
            if s and len(s.strip()) >= 30]

    print(f"  🔄 LLM 评分: {len(work)} 条 (model={model}, concurrency={concurrency})",
          file=sys.stderr)

    topics = []
    failed = 0
    no_event = 0

    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_llm_score_one, q, s, api_key, base_url, model): q
            for q, s in work
        }
        for fut in cf.as_completed(futures):
            q = futures[fut]
            try:
                res = fut.result()
            except Exception as e:
                print(f"  ⚠️ 线程异常 [{q!r}]: {e}", file=sys.stderr)
                failed += 1
                continue
            if res is None:
                no_event += 1
                continue

            topic = {
                "title": res.get("headline", q)[:60],
                "digest": (res.get("digest") or "")[:300],
                "angle": (res.get("angle") or "")[:200],
                "pillar": res.get("pillar", "未分类"),
                "source": "websearch",
                "scan_mode": "keyword",
                "query": q,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "has_event": bool(res.get("has_event")),
                "has_controversy": bool(res.get("has_controversy")),
                "has_data": bool(res.get("has_data")),
                # v3.0 四维评分（替代旧五维）
                "relevance": round(res.get("relevance", 0), 1),
                "depth": round(res.get("depth", 0), 1),
                "novelty": round(res.get("novelty", 0), 1),
                "narrative": round(res.get("narrative", 0), 1),
                "total": round(res.get("total", 0), 1),
            }
            topics.append(topic)

    topics.sort(key=lambda t: t.get("total", 0), reverse=True)
    qualified = [t for t in topics if t.get("total", 0) >= min_score]

    print(f"  ✅ LLM 评分完成: {len(topics)} 有效, "
          f"{no_event} 无热点跳过, {failed} 失败", file=sys.stderr)

    return qualified


# =========================================================================
# 本地回退评分 (无 LLM 时使用，仅做基本过滤)
# =========================================================================

def _local_fallback_score(query: str, summary: str) -> dict:
    """无 LLM 时的本地回退：只做基本的事件/争议/数据检测，不做伪评分。"""
    summary_lower = summary.lower() if summary else ""
    has_event = any(kw in summary_lower for kw in [
        "提案", "建议", "发布", "宣布", "判决", "最新",
        "称", "表示", "报道", "数据显示",
    ])
    has_controversy = any(kw in summary_lower for kw in [
        "争议", "反对", "质疑", "批评", "不满", "争议不断",
        "吵", "矛盾", "反弹", "两极分化",
    ])
    has_data = bool(re.search(r'\d+[万亿%]', summary_lower))

    # 简单总分：有事件+争议+数据各加分，不做伪维度
    total = 3.0
    if has_event:
        total += 2.0
    if has_controversy:
        total += 2.0
    if has_data:
        total += 1.5

    return {
        "title": query,
        "angle": "",
        "pillar": "未分类",
        "source": "websearch",
        "scan_mode": "keyword",
        "query": query,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "has_event": has_event,
        "has_controversy": has_controversy,
        "has_data": has_data,
        "relevance": total,
        "depth": 0,
        "novelty": 0,
        "narrative": 0,
        "total": round(min(total, 10), 1),
    }


# =========================================================================
# 查询构建
# =========================================================================

def _load_watch_list() -> list[dict]:
    if not _HOT_WATCH.exists():
        return []
    try:
        data = json.loads(_HOT_WATCH.read_text(encoding='utf-8'))
        return data.get("watch_list", [])
    except (json.JSONDecodeError, OSError):
        return []


def _merged_pillar_keywords() -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for source in (PILLAR_KEYWORDS, EVENT_TRIGGERS):
        for pillar, keywords in source.items():
            merged.setdefault(pillar, []).extend(keywords)
    return merged


def build_search_queries(pillar: str = None, mode: str = "hybrid") -> list[dict]:
    """构建搜索查询列表。"""
    queries = []
    pillars = [pillar] if pillar else list(PILLAR_KEYWORDS.keys())

    if mode in ("hybrid", "keyword"):
        for p in pillars:
            for kw in PILLAR_KEYWORDS.get(p, []):
                queries.append({
                    "pillar": p, "query": kw,
                    "source": "keyword_watch", "mode": "keyword",
                })

    if mode in ("hybrid", "event"):
        for p in pillars:
            for t in EVENT_TRIGGERS.get(p, []):
                queries.append({
                    "pillar": p, "query": t,
                    "source": "event_trigger", "mode": "event",
                })

    for w in _load_watch_list():
        wp = w.get("pillar")
        if pillar and wp != pillar:
            continue
        queries.append({
            "pillar": wp or "cross", "query": w.get("keyword", ""),
            "source": "watch_list", "mode": "keyword",
            "frequency": w.get("frequency", "weekly"),
        })

    cross_hotlist = [
        ("知乎热榜 今日 社会 热点", "hotlist", "社会热点"),
        ("微博热搜 今日 争议 话题", "hotlist", "社会争议"),
        ("百度热搜 今日 社会 新闻", "hotlist", "社会热点"),
    ]
    for q, src, cat in cross_hotlist:
        queries.append({
            "pillar": "cross", "query": q,
            "source": src, "mode": "hotlist", "category": cat,
        })

    return _dedup_queries(queries)


def _dedup_queries(queries: list[dict], threshold: float = 0.6) -> list[dict]:
    def tok(s: str) -> set:
        return set(s.split())
    deduped: list[dict] = []
    for q in queries:
        qt = tok(q["query"])
        is_dup = False
        for i, kept in enumerate(deduped):
            kt = tok(kept["query"])
            if not qt or not kt:
                continue
            union = qt | kt
            jaccard = len(qt & kt) / len(union) if union else 0
            if jaccard >= threshold:
                if len(q["query"]) > len(kept["query"]):
                    deduped[i] = q
                is_dup = True
                break
        if not is_dup:
            deduped.append(q)
    return deduped


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="热点扫描器 v3.0 — LLM 驱动的真实内容评分")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- scan ---
    scan = sub.add_parser("scan", help="构建搜索查询列表")
    scan.add_argument("--pillar", default=None)
    scan.add_argument("--mode", default="hybrid",
                      choices=["hybrid", "keyword", "event"])
    scan.add_argument("--output", default=None)

    # --- consume ---
    consume = sub.add_parser("consume", help="消费 WebSearch 结果 → LLM 评分选题")
    consume.add_argument("results_json", help="WebSearch 结果 JSON 路径")
    consume.add_argument("--output", default=None)
    consume.add_argument("--min-score", type=float, default=0.0,
                         help="最低总评分阈值（默认 0，保留全部）")
    consume.add_argument("--no-llm", action="store_true",
                         help="禁用 LLM，使用本地回退评分")
    consume.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "deepseek-v4-flash"))
    consume.add_argument("--llm-base-url", default=os.environ.get(
        "LLM_BASE_URL", "https://api.deepseek.com"))
    consume.add_argument("--concurrency", type=int, default=3)

    # --- watch ---
    _watch = sub.add_parser("watch", help="列出监控关键词")

    args = parser.parse_args()

    # ================================================================
    # COMMAND: scan
    # ================================================================
    if args.command == "scan":
        queries = build_search_queries(args.pillar, args.mode)

        print(f"{'='*60}")
        print(f"📡 热点扫描 v3.0")
        print(f"   查询总数: {len(queries)}")
        print(f"   限定支柱: {args.pillar or '全部'}")
        print(f"{'='*60}")
        print()

        by_pillar = {}
        for q in queries:
            if q["mode"] == "hotlist":
                by_pillar.setdefault("🌐 热榜检测", []).append(q)
            else:
                by_pillar.setdefault(q["pillar"], []).append(q)

        for pillar, qs in by_pillar.items():
            print(f"## {pillar} ({len(qs)} 查询)")
            for q in qs[:8]:
                tag = {"keyword": "🔍", "event": "⚡", "hotlist": "🌐"}.get(
                    q.get("mode", ""), "  ")
                print(f"  {tag} {q['query']}")
            if len(qs) > 8:
                print(f"  ... 还有 {len(qs) - 8} 条")
            print()

        if args.output:
            output_path = Path(args.output)
            output_path.write_text(
                json.dumps(queries, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            print(f"[OK] {len(queries)} 条查询已写入 {args.output}")

    # ================================================================
    # COMMAND: consume
    # ================================================================
    elif args.command == "consume":
        with open(args.results_json, 'r', encoding='utf-8') as f:
            search_results = json.load(f)

        use_llm = not args.no_llm
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()

        if use_llm and not api_key:
            print("  ⚠️ DEEPSEEK_API_KEY 未设置，回退到本地评分", file=sys.stderr)
            use_llm = False

        if use_llm:
            qualified = llm_consume(
                search_results, api_key, args.llm_base_url,
                args.llm_model, args.concurrency, args.min_score)
        else:
            # 本地回退
            topics = []
            for query, summary in search_results.items():
                if not summary or len(summary.strip()) < 30:
                    continue
                topic = _local_fallback_score(query, summary)
                topics.append(topic)
            topics.sort(key=lambda t: t.get("total", 0), reverse=True)
            qualified = [t for t in topics if t.get("total", 0) >= args.min_score]

        print(f"{'='*60}")
        print(f"消费 WebSearch 结果 — {'LLM' if use_llm else '本地'} 评分")
        print(f"{'='*60}")
        print(f"  输入: {len(search_results)} 查询 → {len(qualified)} 选题")
        print(f"  通过阈值 ({args.min_score}): {len(qualified)} 选题")
        print()

        for i, t in enumerate(qualified[:15]):
            tag = "🔥" if t["total"] >= 7.5 else "📌" if t["total"] >= 6.0 else "🟢"
            print(f"  {i+1}. {tag} [{t.get('pillar','?')}] {t['title'][:60]}")
            print(f"      总分: {t['total']} | "
                  f"相关:{t.get('relevance','?')} "
                  f"深度:{t.get('depth','?')} "
                  f"新颖:{t.get('novelty','?')} "
                  f"叙事:{t.get('narrative','?')}")
            if t.get("digest"):
                print(f"      {t['digest'][:100]}...")
            print()

        if args.output:
            output_path = Path(args.output)
            existing = []
            if output_path.exists():
                existing = json.loads(output_path.read_text(encoding='utf-8'))
            existing_titles = {t.get("title") for t in existing if isinstance(t, dict)}
            new_topics = [t for t in qualified if t["title"] not in existing_titles]
            merged = existing + new_topics
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2, default=str),
                encoding='utf-8'
            )
            print(f"[OK] {len(new_topics)} 个新选题已注入 {args.output}")

    # ================================================================
    # COMMAND: watch
    # ================================================================
    elif args.command == "watch":
        print("=" * 60)
        print("📡 热点监控 v3.0")
        print("=" * 60)
        print()

        print("🔍 支柱关键词:")
        for pillar, keywords in PILLAR_KEYWORDS.items():
            print(f"\n## {pillar}")
            for kw in keywords:
                print(f"  - {kw}")

        print("\n" + "=" * 40)
        print("⚡ 事件触发词:")
        for pillar, triggers in EVENT_TRIGGERS.items():
            print(f"\n## {pillar}")
            for t in triggers:
                print(f"  ⚡ {t}")

        if _HOT_WATCH.exists():
            watch_data = json.loads(_HOT_WATCH.read_text(encoding='utf-8'))
            watch_list = watch_data.get("watch_list", [])
            if watch_list:
                print(f"\n📋 专项监控 ({len(watch_list)} 项)")
                for w in watch_list:
                    print(f"  - [{w['pillar']}] {w['keyword']} (频率: {w['frequency']})")


if __name__ == "__main__":
    main()
