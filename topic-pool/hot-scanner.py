#!/usr/bin/env python3
"""
热点扫描器 v2.0 — 五维爆款评分 + 事件触发 + 争议检测

v2.0 升级要点:
  ① 五维评分: 事件热度 × 反直觉程度 × 个人叙事空间 × 结构分析深度 × 人格匹配度
  ② 事件触发: 扫描微博/知乎/百度热榜，检测"有对立"的事件
  ③ 争议检测: 找评论区在吵什么、什么提案引发了反对声音
  ④ 不再只看关键词——找"活的热点"

v1.0 → v2.0 核心转变:
  v1.0: 静态关键词 → 硬编码评分 → 选题池
  v2.0: 实时事件检测 → 对立/争议识别 → 五维评分 → 爆款潜力排序

用法:
  python hot-scanner.py scan              # 增强扫描: 关键词 + 事件触发
  python hot-scanner.py scan --mode event # 仅事件触发模式
  python hot-scanner.py scan --mode keyword # 仅关键词模式(兼容v1)
  python hot-scanner.py scan --output pool.json  # 输出到选题池
  python hot-scanner.py consume results.json     # 消费 WebSearch 结果
  python hot-scanner.py report            # 热点简报
  python hot-scanner.py watch             # 监控关键词 + 事件触发词
"""

import json
import sys
import io
import re
from datetime import datetime, timezone
from pathlib import Path

# 跨平台编码
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

_SCRIPT_DIR = Path(__file__).resolve().parent
_HOT_WATCH = _SCRIPT_DIR / "hot-watch.json"
_EVERGREEN_POOL = _SCRIPT_DIR / "evergreen-pool.json"

# =========================================================================
# 五支柱关键词映射 (兼容 v1)
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
# 事件触发关键词 v2.0 新增
# =========================================================================
# 这些不是"搜什么选题"，而是"什么信号说明今天有爆款机会"
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
# SOUL.md 核心信念 → 人格匹配度计算
# =========================================================================
# 从 SOUL.md 提取的关键概念及其权重
SOUL_CONCEPTS = {
    "心理问题是社会结构产物": ["社会结构", "权力关系", "文化", "规训", "制度", "系统"],
    "集体行动": ["团结", "集体", "互助", "组织", "一起", "共同"],
    "资本主义批判": ["资本", "剥削", "异化", "无产阶级", "阶级", "剩余价值", "劳动力"],
    "反常识/反主流": ["反常识", "非共识", "真相", "谎言", "你不知道", "面具"],
    "绝望中的行动": ["绝望", "困境", "破局", "出路", "行动", "改变"],
    "真诚/反虚伪": ["虚伪", "谎言", "真相", "表面", "背后", "代价"],
    "个人困境的结构根源": ["一个人", "孤独", "无力", "系统", "结构", "困境"],
}

# 情感温度匹配词 (公众号风格 2/10 冷峻克制)
COOL_TONE_WORDS = ["残酷", "冷静", "数据", "数字", "真相", "结构", "机制",
                    "逻辑", "分析", "背后", "真实", "代价", "博弈"]
WARM_TONE_WORDS = ["温暖", "治愈", "希望", "感动", "美好", "幸福", "爱"]


def calc_persona_fit(title: str, angle: str = "") -> float:
    """计算选题与 SOUL.md 人格的匹配度 (0-10)

    基于 SOUL.md 核心信念的关键词覆盖率 + 情感温度匹配
    """
    text = (title + " " + angle).lower()

    # 核心信念匹配: 每个概念算一分
    concept_hits = 0
    total_concepts = len(SOUL_CONCEPTS)
    for concept, keywords in SOUL_CONCEPTS.items():
        if any(kw in text for kw in keywords):
            concept_hits += 1

    concept_score = (concept_hits / total_concepts) * 5  # 0-5

    # 情感温度匹配: 冷峻克制加分，温暖减分
    cool_hits = sum(1 for w in COOL_TONE_WORDS if w in text)
    warm_hits = sum(1 for w in WARM_TONE_WORDS if w in text)

    if cool_hits > warm_hits:
        tone_score = 3.0 + min(cool_hits * 0.3, 2.0)  # 3-5
    elif warm_hits > cool_hits:
        tone_score = max(0, 2.0 - warm_hits * 0.5)  # 0-2
    else:
        tone_score = 2.5  # 中性

    # 反主流/反常识倾向加分
    counterculture_words = ["反常识", "非共识", "真相", "谎言", "打破", "拒绝",
                            "反抗", "批判", "质疑", "陷阱", "骗局", "不公"]
    counter_hits = sum(1 for w in counterculture_words if w in text)
    counter_score = min(counter_hits * 0.5, 1.0)

    total = concept_score + tone_score + counter_score
    return round(min(total, 10), 1)


# =========================================================================
# v2.0 五维评分系统
# =========================================================================

def score_bomb_potential(topic: dict) -> dict:
    """五维爆款潜力评分

    维度:
      - 事件热度 (0-10): 此刻有多少人在讨论？热搜/提案/争议事件触发？
      - 反直觉程度 (0-10): 结论是否出人意料？有没有对立双方？
      - 个人叙事空间 (0-10): 能不能找到具体人物讲具体故事？
      - 结构分析深度 (0-10): 是否能从个体故事延伸到系统性批判？
      - 人格匹配度 (0-10): 与 SOUL.md 核心信念的重叠度

    Returns:
      包含各维度分和加权总分的 dict
    """
    pillar = topic.get("pillar", "未分类")
    title = topic.get("title", "")
    angle = topic.get("angle", "")
    source = topic.get("source", "")
    text = title + " " + angle

    # --- 1. 事件热度 ---
    heat = 4  # 基础分
    # 如果来自事件触发扫描，说明有实时热度
    if source in ("event", "hotlist"):
        heat = 7
    heat_keywords = ["热搜", "提案", "争议", "反对", "抗议", "曝光",
                     "最新", "突发", "判了", "宣布", "发布", "提案",
                     "两/会", "人大代表", "建议"]
    if any(kw in text for kw in heat_keywords):
        heat += 2
    if "热搜" in text:
        heat += 1
    heat = min(heat, 10)

    # --- 2. 反直觉程度 ---
    counter = 3  # 基础分
    # 有明确对立双方
    counter_keywords = ["为什么", "凭什么", "反对", "争议", "辩论",
                        "割裂", "对立", "吵架", "矛盾", "意外",
                        "不是...而是", "你以为", "真相是"]
    if any(kw in text for kw in counter_keywords):
        counter += 2
    # 出现"打工人反对XX"型反直觉叙事
    backlash_patterns = [
        r"打工人.*反对", r"自己人.*反对", r"受害者.*认同",
        r"为什么.*不.*支持", r"谁在.*反对", r"反对.*最凶",
    ]
    if any(re.search(pat, text) for pat in backlash_patterns):
        counter += 3
    # 标题含问号 - 通常意味着有争议
    if "?" in title or "？" in title or "为什么" in title:
        counter += 1
    counter = min(counter, 10)

    # --- 3. 个人叙事空间 ---
    narrative = 4  # 基础分
    # 可以讲个人故事的题材
    narrative_keywords = ["一个人", "打工人", "年轻人", "工人", "骑手",
                          "北漂", "沪漂", "厂", "出租", "流水线",
                          "故事", "经历", "见过", "身边的"]
    hits = sum(1 for kw in narrative_keywords if kw in text)
    narrative += min(hits * 1.5, 4)
    # 劳动/城市议题天然有叙事空间
    if pillar in ("劳动与阶级", "城市与生存"):
        narrative += 1
    narrative = min(narrative, 10)

    # --- 4. 结构分析深度 ---
    structural = 5  # 基础分
    # 能连接到系统性批判的题材
    structural_keywords = ["结构", "制度", "系统", "机制", "阶级",
                           "资本", "政策", "法律", "时代", "代际",
                           "历史", "社会", "文化", "权力"]
    hits = sum(1 for kw in structural_keywords if kw in text)
    structural += min(hits, 3)
    # 五支柱议题天然有结构分析空间
    if pillar in ("劳动与阶级", "技术与权力", "教育与阶层"):
        structural += 1
    structural = min(structural, 10)

    # --- 5. 人格匹配度 ---
    persona = calc_persona_fit(title, angle)

    # --- 加权总分 ---
    # 爆款公式: 反直觉 × 叙事空间 × 结构深度 是乘数关系
    # 事件热度是触发条件，人格匹配是门槛
    total = round(
        heat * 0.20 +
        counter * 0.25 +
        narrative * 0.20 +
        structural * 0.15 +
        persona * 0.20
    , 1)

    return {
        "total": total,
        "heat": heat,
        "counter_intuitive": counter,
        "narrative_space": narrative,
        "structural_depth": structural,
        "persona_fit": persona,
    }


# =========================================================================
# 扫描引擎 v2.0
# =========================================================================

def _load_watch_list() -> list[dict]:
    """HS-004：从 hot-watch.json 加载专项监控关键词列表"""
    if not _HOT_WATCH.exists():
        return []
    try:
        data = json.loads(_HOT_WATCH.read_text(encoding='utf-8'))
        return data.get("watch_list", [])
    except (json.JSONDecodeError, OSError):
        return []


def _merged_pillar_keywords() -> dict[str, list[str]]:
    """HS-002：合并 PILLAR_KEYWORDS 与 EVENT_TRIGGERS，按支柱拼接关键词列表。

    旧实现 {**PILLAR_KEYWORDS, **EVENT_TRIGGERS} 会让后者整表覆盖前者的同名 key，
    导致 consume 的支柱分类丢失主关键词。这里改为逐项 extend。
    """
    merged: dict[str, list[str]] = {}
    for source in (PILLAR_KEYWORDS, EVENT_TRIGGERS):
        for pillar, keywords in source.items():
            merged.setdefault(pillar, []).extend(keywords)
    return merged


def build_search_queries(pillar: str = None, mode: str = "hybrid") -> list[dict]:
    """构建搜索查询列表

    Args:
        pillar: 限定支柱
        mode: hybrid=关键词+事件, keyword=仅关键词(兼容v1), event=仅事件

    Returns:
        [{"pillar": "...", "query": "...", "source": "...", "mode": "..."}]
    """
    queries = []
    pillars = [pillar] if pillar else list(PILLAR_KEYWORDS.keys())

    if mode in ("hybrid", "keyword"):
        for p in pillars:
            keywords = PILLAR_KEYWORDS.get(p, [])
            for kw in keywords:
                queries.append({
                    "pillar": p,
                    "query": kw,
                    "source": "keyword_watch",
                    "mode": "keyword",
                })

    if mode in ("hybrid", "event"):
        for p in pillars:
            triggers = EVENT_TRIGGERS.get(p, [])
            for t in triggers:
                queries.append({
                    "pillar": p,
                    "query": t,
                    "source": "event_trigger",
                    "mode": "event",
                })

    # HS-004：纳入 hot-watch.json 专项监控关键词（按支柱归类）
    for w in _load_watch_list():
        wp = w.get("pillar")
        if pillar and wp != pillar:
            continue
        queries.append({
            "pillar": wp or "cross",
            "query": w.get("keyword", ""),
            "source": "watch_list",
            "mode": "keyword",
            "frequency": w.get("frequency", "weekly"),
        })

    # 跨平台热榜检测 (始终跑)
    cross_hotlist = [
        ("知乎热榜 今日 社会 热点", "hotlist", "社会热点"),
        ("微博热搜 今日 争议 话题", "hotlist", "社会争议"),
        ("百度热搜 今日 社会 新闻", "hotlist", "社会热点"),
    ]
    for q, src, cat in cross_hotlist:
        queries.append({
            "pillar": "cross",
            "query": q,
            "source": src,
            "mode": "hotlist",
            "category": cat,
        })

    # HS-06：查询去重——分词 Jaccard 相似度 >0.6 合并（保留更长/更具体者），省查询槽
    return _dedup_queries(queries)


def _dedup_queries(queries: list[dict], threshold: float = 0.6) -> list[dict]:
    """查询级去重：避免近义查询重复扫描。"""
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
                # 保留更长/更具体的查询
                if len(q["query"]) > len(kept["query"]):
                    deduped[i] = q
                is_dup = True
                break
        if not is_dup:
            deduped.append(q)
    return deduped


def build_event_query() -> list[dict]:
    """构建"事件触发"扫描查询 — 专门找今天在吵什么

    这些查询不是为了搜索某个固定关键词，而是发现"今天有什么事值得做"
    """
    event_queries = [
        # 争议/对立检测
        {"query": "今天 热搜 打工人 争议", "pillar": "劳动与阶级", "focus": "backlash"},
        {"query": "今天 微博 吵 什么 话题", "pillar": "cross", "focus": "controversy"},
        {"query": "2026年 最新 社会 争议 话题", "pillar": "cross", "focus": "controversy"},
        {"query": "评论区 吵翻 热搜 话题", "pillar": "cross", "focus": "backlash"},
        {"query": "人大代表 建议 引发 争议 2026", "pillar": "劳动与阶级", "focus": "proposal"},
        {"query": "最新 政策 引发 讨论 2026", "pillar": "cross", "focus": "policy"},
    ]
    return event_queries


# =========================================================================
# 结果解析与评分 v2.0
# =========================================================================

def parse_search_result(query: dict, websearch_summary: str) -> dict | None:
    """解析 WebSearch 结果，判断是否有爆款潜力

    Args:
        query: 原始查询
        websearch_summary: WebSearch 返回的摘要

    Returns:
        如果值得跟进 → topic dict; 否则 None
    """
    if not websearch_summary or len(websearch_summary.strip()) < 30:
        return None

    summary = websearch_summary.lower()
    pillar = query.get("pillar", "未分类")
    source = query.get("source", "keyword_watch")

    # 判断是否值得做
    # 1. 有具体事件/数据/人物 → 值得
    has_event = any(kw in summary for kw in [
        "提案", "建议", "发布", "宣布", "判决", "最新",
        "称", "表示", "报道", "数据显示",
    ])
    # 2. 有争议/对立 → 高价值
    has_controversy = any(kw in summary for kw in [
        "争议", "反对", "质疑", "批评", "不满", "争议不断",
        "吵", "矛盾", "反弹", "两极分化",
    ])
    # 3. 有具体数据 → 高价值
    has_data = bool(re.search(r'\d+[万亿%]', summary))

    # 构造标题和角度
    title = _extract_title(websearch_summary, query)
    angle = _extract_angle(websearch_summary, query)

    # 评分
    topic = {
        "title": title,
        "angle": angle,
        "pillar": pillar,
        "source": source,
        "scan_mode": query.get("mode", "keyword"),
        "has_event": has_event,
        "has_controversy": has_controversy,
        "has_data": has_data,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }

    # 五维评分
    scores = score_bomb_potential(topic)
    topic.update(scores)

    return topic


def _extract_title(summary: str, query: dict) -> str:
    """从 WebSearch 摘要中提取标题"""
    # 优先用搜索词本身
    q = query.get("query", "")
    # 找第一句有信息量的
    lines = summary.strip().split("\n")
    for line in lines:
        line = line.strip()
        if len(line) > 10 and not line.startswith(("http", "www")):
            return line[:80]
    return q


def _extract_angle(summary: str, query: dict) -> str:
    """从搜索摘要中提取分析角度"""
    pillar = query.get("pillar", "未分类")
    focus = query.get("focus", "")

    # 根据焦点类型推荐角度
    if "backlash" in focus:
        return "为什么这件事让人吵起来了——反对者真正在怕什么，支持者真正在想什么"
    elif "controversy" in focus:
        return "表面的争议之下，是什么结构性的分歧没有被说出来"
    elif "proposal" in focus:
        return "这个提案动了谁的蛋糕——政策背后的利益格局分析"
    elif "policy" in focus:
        return "这项政策名义上帮谁、实际上帮谁、被谁反对了"

    # 根据支柱推荐角度
    angle_templates = {
        "劳动与阶级": "从具体人物的处境出发，分析这套结构如何锁死了他们的选择",
        "技术与权力": "表面的技术进步背后，谁在受益、谁在付出代价",
        "心理与规训": "这不是某个人的心理问题——是环境和制度在制造症状",
        "教育与阶层": "这套筛选机制表面上公平，实际上在完成什么功能",
        "城市与生存": "这些数字背后，普通人每天在面临什么选择",
    }
    return angle_templates.get(pillar, "从个人故事切入，连接到结构性分析")


# =========================================================================
# 热点简报 (v2.0 增强版)
# =========================================================================

def generate_report(topics: list[dict]) -> str:
    """生成可读的热点简报"""
    if not topics:
        return "当前无有效热点信号。运行 `python hot-scanner.py scan` 扫描。"

    lines = []
    lines.append("=" * 60)
    lines.append("📡 热点简报 v2.0")
    lines.append(f"生成时间: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"候选选题: {len(topics)}")
    lines.append("=" * 60)
    lines.append("")

    # 按总分排序
    sorted_topics = sorted(topics, key=lambda t: t.get("total", 0), reverse=True)

    # 爆款潜力 ≥ 7.5 的标记为高优
    high_priority = [t for t in sorted_topics if t.get("total", 0) >= 7.5]
    medium = [t for t in sorted_topics if 6.0 <= t.get("total", 0) < 7.5]
    low = [t for t in sorted_topics if t.get("total", 0) < 6.0]

    if high_priority:
        lines.append("🔥 HIGH PRIORITY — 爆款潜力高")
        lines.append("-" * 40)
        for t in high_priority:
            lines.append(f"  [{t.get('pillar', '?')}] {t['title']}")
            lines.append(f"      总分: {t['total']}  |  "
                         f"热度:{t.get('heat','?')}  "
                         f"反直觉:{t.get('counter_intuitive','?')}  "
                         f"叙事:{t.get('narrative_space','?')}  "
                         f"结构:{t.get('structural_depth','?')}  "
                         f"人格:{t.get('persona_fit','?')}")
            if t.get("has_controversy"):
                lines.append(f"      ⚡ 有争议对立")
            if t.get("has_event"):
                lines.append(f"      📰 有事件触发")
            lines.append(f"      切入角度: {t.get('angle', '')}")
            lines.append("")
        lines.append("")

    if medium:
        lines.append("📌 MEDIUM — 可关注")
        lines.append("-" * 40)
        for t in medium:
            lines.append(f"  [{t['pillar']}] {t['title']} (总分: {t.get('total', '?')})")
        lines.append("")

    if low:
        lines.append("  🟢 LOW — 暂不跟进")
        lines.append("-" * 40)
        for t in low[:5]:
            lines.append(f"  [{t['pillar']}] {t['title']} ({t.get('total', '?')})")

    return "\n".join(lines)


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="热点扫描器 v2.0 — 五维爆款评分 + 事件触发")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- scan ---
    scan = sub.add_parser("scan", help="扫描热点选题 (v2.0 增强)")
    scan.add_argument("--pillar", default=None, help="限定支柱")
    scan.add_argument("--mode", default="hybrid",
                      choices=["hybrid", "keyword", "event"],
                      help="扫描模式: hybrid(默认), keyword(兼容v1), event(仅事件)")
    scan.add_argument("--output", default=None, help="输出JSON路径")
    scan.add_argument("--max-results", type=int, default=15, help="最大结果数")

    # --- consume ---
    consume = sub.add_parser("consume", help="消费 WebSearch 结果, 输出爆款评分选题")
    consume.add_argument("results_json", help="WebSearch 结果 JSON 路径")
    consume.add_argument("--output", default=None, help="输出到选题池 JSON")
    consume.add_argument("--min-score", type=float, default=6.0, help="最低总评分阈值")

    # --- watch ---
    _watch = sub.add_parser("watch", help="列出监控关键词 + 事件触发词")

    # --- event-scan ---
    event = sub.add_parser("event-scan", help="仅事件触发扫描 — 找今天在吵什么")
    event.add_argument("--output", default=None, help="输出JSON路径")

    # --- report ---
    _report = sub.add_parser("report", help="生成热点简报")

    args = parser.parse_args()

    # ================================================================
    # COMMAND: scan
    # ================================================================
    if args.command == "scan":
        queries = build_search_queries(args.pillar, args.mode)

        print(f"{'='*60}")
        print(f"📡 热点扫描 v2.0")
        print(f"   扫描模式: {args.mode.upper()}")
        print(f"   查询总数: {len(queries)}")
        print(f"   限定支柱: {args.pillar or '全部'}")
        print(f"   扫描时间: {datetime.now(timezone.utc).isoformat()}")
        print(f"{'='*60}")
        print()

        # 按来源分组
        by_mode = {"keyword": 0, "event": 0, "hotlist": 0}
        for q in queries:
            m = q.get("mode", "keyword")
            by_mode[m] = by_mode.get(m, 0) + 1
        print(f"  关键词扫描: {by_mode.get('keyword', 0)} 条")
        print(f"  事件触发扫描: {by_mode.get('event', 0)} 条")
        print(f"  热榜检测: {by_mode.get('hotlist', 0)} 条")
        print()

        # 分组显示
        by_pillar = {}
        for q in queries:
            if q["mode"] == "hotlist":
                by_pillar.setdefault("🌐 热榜检测", []).append(q)
            else:
                by_pillar.setdefault(q["pillar"], []).append(q)

        results = []
        for pillar, qs in by_pillar.items():
            print(f"## {pillar} ({len(qs)} 查询)")
            show_count = min(len(qs), 8)
            for q in qs[:show_count]:
                tag = {"keyword": "🔍", "event": "⚡", "hotlist": "🌐"}.get(q.get("mode", ""), "  ")
                print(f"  {tag} [{q.get('source','?')}] {q['query']}")

                # 模拟评分 (实际应由 Claude WebSearch 消费)
                topic = {
                    "title": q["query"],
                    "angle": f"搜索词: {q['query']}",
                    "pillar": q["pillar"],
                    "source": q.get("source", "keyword_watch"),
                    "scan_mode": q.get("mode", "keyword"),
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                }
                scores = score_bomb_potential(topic)
                topic.update(scores)
                results.append(topic)

            if len(qs) > show_count:
                print(f"  ... 还有 {len(qs) - show_count} 条")
            print()

        # 排序和输出
        results.sort(key=lambda r: r.get("total", 0), reverse=True)
        top = results[:args.max_results]

        print(f"{'='*60}")
        print(f"🔥 TOP {len(top)} 爆款潜力选题 (五维评分)")
        print(f"{'='*60}")
        print()
        for i, r in enumerate(top):
            tag = "🔥" if r["total"] >= 7.5 else "📌" if r["total"] >= 6.0 else "🟢"
            print(f"  {i+1}. {tag} [{r['pillar']}] {r['title']}")
            print(f"      总分: {r['total']} | "
                  f"热度:{r['heat']} 反直觉:{r['counter_intuitive']} "
                  f"叙事:{r['narrative_space']} 结构:{r['structural_depth']} "
                  f"人格:{r['persona_fit']}")
            print()

        # 高优选题详细说明
        high_pri = [r for r in top if r["total"] >= 7.5]
        if high_pri:
            print(f"\n🔥 高优推荐分析:")
            print("-" * 40)
            for r in high_pri:
                deficit = []
                if r["counter_intuitive"] < 7:
                    deficit.append("反直觉分低→需要找对立角度")
                if r["narrative_space"] < 7:
                    deficit.append("叙事空间低→需要找具体人物")
                if r["persona_fit"] < 6:
                    deficit.append("人格匹配低→需要调整切入角度")
                if r["heat"] < 6:
                    deficit.append("热度低→需要等事件触发或自己制造争议")
                print(f"  [{r['pillar']}] {r['title']}")
                if deficit:
                    print(f"     ⚠️ {"；".join(deficit)}")
                # HS-008：r['angle'] 已是角度字符串，直接用，不再误用 _extract_angle(summary, query)
                print(f"     切入: {r.get('angle', '')}")
                print()

        if args.output:
            output_path = Path(args.output)
            existing = []
            if output_path.exists():
                existing = json.loads(output_path.read_text(encoding='utf-8'))
            existing_queries = {t.get("title") for t in existing if isinstance(t, dict)}
            new_topics = [r for r in top if r["title"] not in existing_queries]
            merged = existing + new_topics
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2, default=str),
                encoding='utf-8'
            )
            print(f"[OK] {len(new_topics)} 个新选题已写入 {args.output}")

    # ================================================================
    # COMMAND: consume
    # ================================================================
    elif args.command == "consume":
        with open(args.results_json, 'r', encoding='utf-8') as f:
            search_results = json.load(f)

        # HS-002：用合并后的关键词做支柱匹配（旧 {**PILLAR_KEYWORDS,**EVENT_TRIGGERS} 会让
        #         EVENT_TRIGGERS 覆盖 PILLAR_KEYWORDS 的同名 key，主关键词全部丢失）
        merged_kw = _merged_pillar_keywords()

        topics = []
        for query, summary in search_results.items():
            if not summary or len(summary.strip()) < 30:
                continue

            # 支柱匹配：关键词任一分词出现在 query 中即归该支柱
            matched_pillar = "未分类"
            for pillar, keywords in merged_kw.items():
                if any(any(tok in query for tok in kw.split()) for kw in keywords):
                    matched_pillar = pillar
                    break

            # HS-008：用 parse_search_result 解析（原为死代码），统一标题/角度/评分提取
            query_dict = {
                "query": query,
                "pillar": matched_pillar,
                "source": "websearch",
                "mode": "keyword",
                "focus": "",
            }
            topic = parse_search_result(query_dict, summary)
            if topic is None:
                # summary 过短等回退：用 query 作标题
                topic = {
                    "title": query,
                    "angle": summary[:200],
                    "pillar": matched_pillar,
                    "source": "websearch",
                    "scan_mode": "keyword",
                    "scanned_at": datetime.now(timezone.utc).isoformat(),
                    "has_event": False,
                    "has_controversy": False,
                    "has_data": False,
                }
                scores = score_bomb_potential(topic)
                topic.update(scores)
            topics.append(topic)

        topics.sort(key=lambda t: t.get("total", 0), reverse=True)
        qualified = [t for t in topics if t.get("total", 0) >= args.min_score]

        print(f"{'='*60}")
        print(f"消费 WebSearch 结果 — 五维爆款评分")
        print(f"{'='*60}")
        print(f"  输入: {len(search_results)} 查询 → {len(topics)} 有效结果")
        print(f"  通过阈值 ({args.min_score}): {len(qualified)} 选题")
        print()

        for i, t in enumerate(qualified[:15]):
            tag = "🔥" if t["total"] >= 7.5 else "📌" if t["total"] >= 6.0 else "🟢"
            print(f"  {i+1}. {tag} [{t['pillar']}] {t['title'][:60]}")
            print(f"      总分: {t['total']} | "
                  f"热度:{t['heat']} 反直觉:{t['counter_intuitive']} "
                  f"叙事:{t['narrative_space']} 结构:{t['structural_depth']} "
                  f"人格:{t['persona_fit']}")
            print(f"      {t['angle'][:100]}...")
            print()

        if args.output:
            output_path = Path(args.output)
            existing = []
            if output_path.exists():
                existing = json.loads(output_path.read_text(encoding='utf-8'))
            existing_queries = {t.get("title") for t in existing if isinstance(t, dict)}
            new_topics = [t for t in qualified if t["title"] not in existing_queries]
            merged = existing + new_topics
            output_path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2, default=str),
                encoding='utf-8'
            )
            print(f"[OK] {len(new_topics)} 个新选题已注入 {args.output}")

    # ================================================================
    # COMMAND: event-scan
    # ================================================================
    elif args.command == "event-scan":
        events = build_event_query()

        print(f"{'='*60}")
        print(f"⚡ 事件触发扫描 — 今天在吵什么")
        print(f"   扫描时间: {datetime.now(timezone.utc).isoformat()}")
        print(f"   查询数: {len(events)}")
        print(f"{'='*60}")
        print()

        results = []
        for ev in events:
            print(f"  ⚡ [{ev['pillar']}] {ev['query']} — 焦点: {ev['focus']}")
            topic = {
                "title": ev["query"],
                "angle": f"事件触发: {ev['focus']}",
                "pillar": ev["pillar"],
                "source": "event_scan",
                "scan_mode": "event",
                "scanned_at": datetime.now(timezone.utc).isoformat(),
            }
            scores = score_bomb_potential(topic)
            topic.update(scores)
            results.append(topic)

        results.sort(key=lambda r: r.get("total", 0), reverse=True)
        print()
        print(f"排序结果:")
        for i, r in enumerate(results):
            print(f"  {i+1}. [{r['pillar']}] {r['title']} (总分: {r['total']})")

        if args.output:
            Path(args.output).write_text(
                json.dumps(results, ensure_ascii=False, indent=2, default=str),
                encoding='utf-8'
            )
            print(f"\n[OK] 已写入 {args.output}")

    # ================================================================
    # COMMAND: watch
    # ================================================================
    elif args.command == "watch":
        print("=" * 60)
        print("📡 热点监控 v2.0 — 关键词 + 事件触发词")
        print("=" * 60)
        print()

        print("🔍 支柱关键词监控:")
        for pillar, keywords in PILLAR_KEYWORDS.items():
            print(f"\n## {pillar}")
            for kw in keywords:
                print(f"  - {kw}")

        print("\n" + "=" * 40)
        print("⚡ 事件触发词监控 (v2.0 新增):")
        for pillar, triggers in EVENT_TRIGGERS.items():
            print(f"\n## {pillar}")
            for t in triggers:
                print(f"  ⚡ {t}")

        print("\n" + "=" * 40)
        print("🌐 热榜监控:")
        print("  - 微博热搜 (社会类)")
        print("  - 知乎热榜")
        print("  - 百度热搜 (社会)")

        # 也读 hot-watch.json 的专项监控
        if _HOT_WATCH.exists():
            watch_data = json.loads(_HOT_WATCH.read_text(encoding='utf-8'))
            watch_list = watch_data.get("watch_list", [])
            if watch_list:
                print(f"\n📋 专项监控 ({len(watch_list)} 项)")
                for w in watch_list:
                    print(f"  - [{w['pillar']}] {w['keyword']} (频率: {w['frequency']})")

    # ================================================================
    # COMMAND: report
    # ================================================================
    elif args.command == "report":
        print("=" * 60)
        print("📡 热点简报 v2.0")
        print(f"   生成时间: {datetime.now(timezone.utc).isoformat()}")
        print("=" * 60)
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

        # 爆款选题待命列表
        print(f"\n## 高优直出建议")
        print(f"  选题池里有 {len(ready) if _EVERGREEN_POOL.exists() else '?'} 篇 ready 选题")
        print(f"  要产出爆款，建议:")
        print(f"    1. 先跑 `python hot-scanner.py scan --mode event` 检测今天的热点")
        print(f"    2. 如果有事件触发 → 立即走管线")
        print(f"    3. 如果无事件 → 从选题池选高优常青选题 + 自己制造非共识角度")
        print(f"    4. 参考 7小时工作制: 选题 → 研究 → persona → QA → 发布")


if __name__ == "__main__":
    main()
