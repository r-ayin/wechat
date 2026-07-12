#!/usr/bin/env python3
"""
L4 事实验证器 — 双模式：plan（生成搜索计划）+ verify（判定逐条结论）

plan 模式:  claims JSON → 搜索查询列表（供 Claude 执行 WebSearch）
verify 模式: claims + search_results → 逐条 VERIFIED / UNVERIFIABLE / FALSIFIED

搜索执行在 Claude 会话中完成（WebSearch tool），本模块负责查询生成 + 结论判定。
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# AHV-005：复用 claim_extractor 的中文数字转换器
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from claim_extractor import cn2num


# =========================================================================
# 模式 1: 搜索计划生成
# =========================================================================

def generate_search_queries(claims: list[dict], max_queries: int = 30) -> list[dict]:
    """为每条声明生成优化的搜索查询

    按优先级排序：
      1. FALSIFIED 风险最高（精确数字无来源）
      2. 政策/报告名称（需精确匹配）
      3. 人物+事件组合
      4. 普通数据

    Args:
        claims: claim_extractor 输出的 claims 列表
        max_queries: 最大查询数（避免 API 成本爆炸）

    Returns:
        搜索计划列表
    """
    queries = []

    for claim in claims:
        query = _build_query(claim)
        if not query:
            continue

        queries.append({
            "claim_id": claim["id"],
            "claim_type": claim["type"],
            "claim_text": claim["text"][:80],
            "query": query,
            "priority": _get_priority(claim),
            "context": claim.get("context", "")[:100],
        })

    # 按优先级排序：high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    queries.sort(key=lambda q: (priority_order.get(q["priority"], 2), q["claim_id"]))

    # 截断到最大查询数
    truncated_count = 0
    if len(queries) > max_queries:
        truncated_count = len(queries) - max_queries
        print(
            f"[fact_checker] WARNING: generate_search_queries truncated {truncated_count} "
            f"lower-priority queries (max_queries={max_queries}, original={len(queries)}). "
            f"Affected priorities: {sorted({q['priority'] for q in queries[max_queries:]})}",
            file=sys.stderr,
        )
        queries = queries[:max_queries]

    return {"queries": queries, "truncated_count": truncated_count}


def _build_query(claim: dict) -> str | None:
    """为单条声明构建搜索查询"""
    claim_type = claim["type"]
    text = claim["text"].strip()

    if claim_type == "PERSON":
        # 人物查询：姓名 + 身份提示
        role = claim.get("role_hint", "")
        age = claim.get("age", "")
        if claim.get("is_full_name"):
            # 全名 → 直接搜
            parts = [text]
            if role:
                parts.append(role)
            if age:
                parts.append(f"{age}岁")
            return " ".join(parts)
        elif claim.get("is_pseudonym"):
            # 化名 → 搜索描述的行业事件而非人名
            if role:
                return f"{role} {text} 骑手 网约车司机 外卖"
            return None  # 纯化名无法搜索

    elif claim_type == "EVENT":
        # 事件查询：日期 + 核心关键词
        date = claim.get("date", "")
        policy = claim.get("policy_name", "")

        if policy:
            return f"{date} 《{policy}》 出台 发布"
        elif date:
            # 提取上下文关键词（去掉日期部分）
            ctx = claim.get("context", "")
            keywords = _extract_keywords(ctx, exclude=[date, "出台", "发布", "报道"])
            return f"{date} {keywords}"[:200]
        else:
            return text[:200]

    elif claim_type == "DATA":
        # 数据查询：数据 + 主题关键词
        ctx = claim.get("context", "")
        # 从上下文中提取主题词
        topic_keywords = _extract_keywords(ctx, exclude=[text])
        return f"{text} {topic_keywords} 数据 统计 来源"[:200]

    elif claim_type == "QUOTE":
        if claim.get("ref_type") == "policy":
            return f"{text} 全文 原文"
        elif claim.get("ref_type") == "report":
            return f"{text} 报告 发布"
        elif claim.get("ref_type") == "attribution":
            return f"{text} 采访 报道"
        else:
            return text[:200]

    return text[:200]


def _extract_keywords(context: str, exclude: list[str] = None, max_chars: int = 80) -> str:
    """从上下文中提取关键词（简易版，去掉标点和排除词）"""
    exclude = exclude or []
    # 去掉所有非中文非字母数字的字符
    cleaned = re.sub(r'[^一-鿿A-Za-z0-9]', ' ', context)
    # 去掉排除词
    for ex in exclude:
        cleaned = cleaned.replace(ex, '')
    # 取前几个词
    words = cleaned.strip().split()
    return ' '.join(words[:6])[:max_chars]


def _get_priority(claim: dict) -> str:
    """确定声明验证的优先级"""
    # 精确数字无来源 → high
    if claim.get("risk") == "high":
        return "high"
    # 政策/报告名称 → high
    if claim.get("ref_type") in ("policy", "report"):
        return "high"
    # 有日期的事件 → medium
    if claim.get("date"):
        return "medium"
    # 全名人物 → medium
    if claim.get("is_full_name"):
        return "medium"
    # 其余 → low
    return "low"


# =========================================================================
# 模式 2: 事实验证判定
# =========================================================================

def verify_claims(
    claims: list[dict],
    search_results: dict[str, str],
    strictness: str = "standard",
) -> list[dict]:
    """根据搜索结果判定每条声明的真实性

    判定规则：
      VERIFIED      — ≥2 独立信源确认，或 1 个官方/权威信源
      UNVERIFIABLE  — 找不到信源但不可证伪
      FALSIFIED     — 与信源矛盾 / 人物事件不存在 / 数据严重偏差

    Args:
        claims: 声明列表
        search_results: {claim_id: "搜索摘要文本"} 映射
        strictness: "strict"(发布前) / "standard"(常规) / "lenient"(草稿)

    Returns:
        带 verdict / confidence / needs_claude_review 的 claims 列表
    """
    verified_claims = []

    for claim_in in claims:
        # WC-H03 fix: avoid mutating the caller's claims list in-place.
        # Shallow copy is sufficient — we only add top-level keys, no nested mutation.
        claim = claim_in.copy()

        result_text = search_results.get(claim["id"], "")

        verdict = _judge_claim(claim, result_text, strictness)
        claim["verdict"] = verdict["verdict"]
        claim["verdict_reason"] = verdict["reason"]
        claim["search_result_snippet"] = result_text[:300] if result_text else None
        claim["verified_at"] = datetime.now(timezone.utc).isoformat()

        # 后处理：置信度评分 + Claude 审核标记
        confidence = verdict.get("confidence")
        if confidence is None:
            confidence = _compute_confidence(claim, claim["verdict"], result_text)
        claim["confidence"] = confidence
        claim["needs_claude_review"] = (
            verdict.get("needs_claude_review", False)
            or confidence < 0.7
            or claim.get("risk") == "high"
        )

        verified_claims.append(claim)

    # QAH-04：多声明交叉验证——同主题数值不一致检测，标 needs_claude_review
    cross_issues = cross_validate_claims(verified_claims)
    for c in verified_claims:
        c["cross_validation_issues"] = cross_issues.get(c["id"], [])

    return verified_claims


def cross_validate_claims(claims: list[dict]) -> dict:
    """QAH-04：检测同一事实多声明间的一致性。
    找上下文相似（分词 Jaccard>0.4）但数值差异>2倍的 DATA 声明对，标记不一致。
    返回 {claim_id: [issue 描述]}。
    """
    issues: dict = {}
    data_claims = [c for c in claims if c.get("type") == "DATA"]
    for i, a in enumerate(data_claims):
        ta = set(a.get("context", "").split())
        va = _extract_numeric_values(a.get("text", ""))
        if not va:
            continue
        for b in data_claims[i + 1:]:
            tb = set(b.get("context", "").split())
            if not ta or not tb:
                continue
            jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0
            if jaccard < 0.4:
                continue
            vb = _extract_numeric_values(b.get("text", ""))
            if not vb:
                continue
            # 比较最大数值；任一侧为 0 则比值无意义（WC-H05: 原仅守 mb==0，
            # va=[0.0], vb=[5.0] 会得 ratio=0<0.5 误报不一致）
            ma, mb = max(va), max(vb)
            if ma == 0 or mb == 0:
                continue
            ratio = ma / mb
            if ratio > 2.0 or ratio < 0.5:
                msg = (f"与声明 {b['id']}「{b.get('text','')}」数值不一致"
                       f"（{ma} vs {mb}，比值 {ratio:.2f}），上下文相似(J={jaccard:.2f})")
                issues.setdefault(a["id"], []).append(msg)
                issues.setdefault(b["id"], []).append(
                    f"与声明 {a['id']}「{a.get('text','')}」数值不一致")
    return issues


def _compute_confidence(claim: dict, verdict: str, search_result: str) -> float:
    """根据可用信号估算判定置信度 (0.0-1.0)

    信号加权:
      - 多信源确认: +0.3
      - 精确匹配: +0.2
      - 搜索结果非空: +0.2
      - 官方/权威信源: +0.2
      - 基线: 0.1
    """
    score = 0.1

    if not search_result or len(search_result.strip()) < 20:
        return 0.05 if verdict == "UNVERIFIABLE" else 0.1

    # 信源数量
    source_count = _estimate_source_count(search_result)
    if source_count >= 3:
        score += 0.3
    elif source_count >= 1:
        score += 0.2

    # 精确匹配
    has_corroboration = _check_corroboration(claim.get("text", ""), search_result)
    if has_corroboration:
        score += 0.2

    # 权威信源（QAH-02：三级可信度分级，替代原二值 +0.2）
    cred = _source_credibility(search_result)
    score += cred  # Tier1 +0.3 / Tier2 +0.2 / Tier3 +0.1 / 无 +0

    # 与判定一致性调整
    if verdict == "FALSIFIED":
        score = min(score, 0.5)  # FALSIFIED 需要 Claude 确认
    elif verdict == "VERIFIED":
        score = min(score + 0.1, 1.0)

    return round(score, 2)


def _judge_claim(claim: dict, search_result: str, strictness: str) -> dict:
    """判定单条声明

    返回 {"verdict": "VERIFIED|UNVERIFIABLE|FALSIFIED", "reason": "...", "confidence": 0.0-1.0}
    """
    claim_type = claim["type"]
    text = claim["text"]

    # WebSearch 执行失败 vs 空结果
    if search_result and search_result.startswith("ERROR:"):
        return {
            "verdict": "UNVERIFIABLE",
            "reason": f"搜索执行失败，无法验证: {search_result[6:]}",
            "confidence": 0.0,
            "needs_claude_review": True,
        }

    # 无搜索结果
    if not search_result or len(search_result.strip()) < 20:
        # 化名人物 → 默认 UNVERIFIABLE（但不阻断）
        if claim.get("is_pseudonym"):
            return {
                "verdict": "UNVERIFIABLE",
                "reason": "化名人物，无法直接验证。身份背景需交叉验证行业常态数据。"
            }
        # 精确数字无来源 → UNVERIFIABLE + 人工复核（H-004, audit-2026-07-06-022）。
        # 旧实现直接判 FALSIFIED，攻击者可构造"搜索必空"的声明触发自动虚假标记，
        # 形成 search-poisoning DoS：批量注入高风险 claim → 全部 auto-FALSIFIED →
        # 报告可信度被人为拉低。改为 UNVERIFIABLE + needs_claude_review，与 ERROR: 分支对齐。
        if claim.get("risk") == "high":
            return {
                "verdict": "UNVERIFIABLE",
                "reason": f"精确数据「{text}」无搜索结果支持，需人工交叉验证。",
                "confidence": 0.0,
                "needs_claude_review": True,
            }
        return {
            "verdict": "UNVERIFIABLE",
            "reason": f"搜索「{text}」未找到相关信源。"
        }

    # 有搜索结果 → 分析结果
    has_corroboration = _check_corroboration(text, search_result)
    has_contradiction = _check_contradiction(text, search_result)
    source_count = _estimate_source_count(search_result)

    if claim_type == "PERSON" and claim.get("is_full_name"):
        # 全名人物：搜到相关信息 → VERIFIED
        if has_corroboration and source_count >= 1:
            return {
                "verdict": "VERIFIED",
                "reason": f"人物在搜索结果中出现，身份可交叉验证（信源数≈{source_count}）。"
            }
        elif has_corroboration:
            return {
                "verdict": "VERIFIED",
                "reason": "人物在搜索结果中有相关记载。"
            }
        else:
            return {
                "verdict": "UNVERIFIABLE",
                "reason": f"人物「{text}」在搜索结果中未找到明确记载，可能为化名或虚构。"
            }

    elif claim_type == "EVENT":
        if has_corroboration and source_count >= (1 if strictness == "lenient" else 2):
            return {
                "verdict": "VERIFIED",
                "reason": f"事件在≥{source_count}个信源中得到确认。"
            }
        elif has_contradiction:
            return {
                "verdict": "FALSIFIED",
                "reason": f"搜索结果与声明描述矛盾。"
            }
        elif has_corroboration:
            return {
                "verdict": "UNVERIFIABLE",
                "reason": f"事件有相关记载但信源不足（仅{source_count}个，需≥2）。"
            }
        else:
            return {
                "verdict": "UNVERIFIABLE",
                "reason": "搜索结果中未找到该事件的确切记载。"
            }

    elif claim_type == "DATA":
        # QAH-05：信源时效性——数据年份距今>3年标过期风险（caveat，不阻断）
        recency_note = ""
        if claim.get("data_year"):
            try:
                from datetime import date
                age = date.today().year - int(claim["data_year"])
                if age > 3:
                    recency_note = f"（⚠ 数据年份 {claim['data_year']}，距今 {age} 年，可能过期）"
            except (ValueError, TypeError):
                pass
        if has_corroboration and source_count >= 1:
            # 额外检查：数值范围是否合理
            if _check_value_range(text, search_result):
                return {
                    "verdict": "VERIFIED",
                    "reason": f"数据在搜索结果中得到确认。{recency_note}".strip()
                }
            else:
                return {
                    "verdict": "FALSIFIED",
                    "reason": f"数据「{text}」与搜索结果中的实际数值不符。{recency_note}".strip()
                }
        elif claim.get("is_approximate"):
            return {
                "verdict": "UNVERIFIABLE",
                "reason": f"约数无法精确验证，但方向描述与行业趋势一致则可接受。{recency_note}".strip()
            }
        else:
            return {
                "verdict": "UNVERIFIABLE",
                "reason": f"数据「{text}」在搜索结果中未找到直接来源。{recency_note}".strip()
            }

    elif claim_type == "QUOTE":
        if claim.get("ref_type") == "policy":
            if has_contradiction:
                return {
                    "verdict": "FALSIFIED",
                    "reason": f"搜索结果中存在辟谣/否定信息，政策「{text}」的引用关联声明可能虚假。"
                }
            if has_corroboration:
                return {
                    "verdict": "VERIFIED",
                    "reason": f"政策文件在搜索结果中被确认存在。"
                }
            else:
                return {
                    "verdict": "FALSIFIED",
                    "reason": f"政策「{text}」在搜索结果中未找到——政策名称必须一字不差。"
                }
        elif claim.get("ref_type") == "report":
            if has_contradiction:
                return {
                    "verdict": "FALSIFIED",
                    "reason": "搜索结果中存在辟谣/否定信息，该报告/报道的引用关联声明可能虚假。"
                }
            if has_corroboration:
                return {
                    "verdict": "VERIFIED",
                    "reason": "报告/报道在搜索结果中被确认。"
                }
            else:
                return {
                    "verdict": "UNVERIFIABLE",
                    "reason": "报告名称未在搜索结果中精确匹配，可能名称有偏差或为概括性引用。"
                }
        else:
            if has_contradiction:
                return {
                    "verdict": "FALSIFIED",
                    "reason": "搜索结果中存在辟谣/否定信息，该引用的关联声明可能虚假。"
                }
            if has_corroboration:
                return {
                    "verdict": "VERIFIED",
                    "reason": "引述言论在搜索结果中有相关记载。"
                }
            else:
                return {
                    "verdict": "UNVERIFIABLE",
                    "reason": "搜索结果中未找到该引用的直接来源。"
                }

    return {
        "verdict": "UNVERIFIABLE",
        "reason": "无法判定。"
    }


def _check_corroboration(claim_text: str, search_result: str) -> bool:
    """检查搜索结果是否支持该声明

    MV-002 fix: 收紧关键实体提取，避免噪声 entity（短 CJK 词、纯年份/小数字）
    触发虚假 VERIFIED。
      - 数字 entity 要求 ≥3 位或带千分位/小数点（排除 "0"/"1"/"2026" 等噪声）
      - CJK entity 长度 > 2（排除 "我们"/"他们"/"但是" 等高频双字词）
      - 显式停用词表过滤残余高频虚词
    """
    # 数字 (≥3位或含千分位/小数) | 书名号内容 | CJK/字母混合 (>2字符)
    raw_entities = re.findall(
        r'\d{3,}|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|[《〈][^》〉]+[》〉]|[A-Za-z一-鿿]{3,}',
        claim_text,
    )

    # 停用词：高频虚词/代词，即便长度≥3也无鉴别力
    _STOP_WORDS = frozenset({
        "我们", "他们", "她们", "它们", "自己", "这个", "那个", "这些", "那些",
        "什么", "怎么", "如何", "为什么", "但是", "而且", "或者", "以及", "因为",
        "所以", "如果", "虽然", "然而", "因此", "于是", "不过", "只是", "就是",
        "还是", "已经", "可以", "应该", "需要", "可能", "必须", "the", "and", "for",
        "that", "this", "with", "from", "have", "been", "will", "are", "was", "were",
    })

    key_entities = [
        e for e in raw_entities
        if e not in _STOP_WORDS and not re.fullmatch(r'\d{1,4}', e)  # 再挡一次纯年份
    ]

    if not key_entities:
        # 无关键实体可匹配——前 30 字纯子串匹配易因通用开头命中而假 VERIFIED（WM-FC-03）。
        # 交 needs_claude_review，不再兜圈子串。
        return False

    # 至少半数关键实体在结果中出现
    matches = sum(1 for e in key_entities if e in search_result)
    return matches >= max(1, len(key_entities) // 2)


def _check_contradiction(claim_text: str, search_result: str) -> bool:
    """检查搜索结果是否与声明矛盾

    AHV-003：旧实现含 '没有'/'不是'——这俩是中文最高频词之一，几乎任何搜索结果
    都命中，导致 EVENT claim 被系统性误标 FALSIFIED。现仅保留强否定信号（辟谣/
    谣言/不实/虚假/并非/不存在），弱否定交给 Claude 在会话中判断。
    """
    # 仅强否定模式；弱否定（没有/不是/错误/误解）不再自动触发 FALSIFIED
    negation_patterns = [
        r'(?:辟谣|谣言|不实|虚假|并非|不存在|否认|捏造|伪造)',
    ]
    for pat in negation_patterns:
        if re.search(pat, search_result):
            return True
    return False


def _source_credibility(search_result: str) -> float:
    """QAH-02：信源可信度三级评分。
    Tier-1 政府/国际组织（gov.cn/stats.gov.cn/who.int/un.org/ilo.org/...）+0.3
    Tier-2 主流媒体（people.com.cn/xinhuanet.com/cctv.com/...）+0.2
    Tier-3 其他可识别信源 +0.1；无信源 +0
    """
    tier1 = ("gov.cn", "stats.gov.cn", "mohrss.gov.cn", "who.int", "un.org",
             "ilo.org", "europa.eu", "cdc.gov", "chinacdc.cn", "acftu.org",
             "moe.gov.cn", "npc.gov.cn")
    tier2 = ("people.com.cn", "xinhuanet.com", "cctv.com", "chinadaily.com.cn",
             "thepaper.cn", "caixin.com", "bjnews.com", "sciencenet.cn")
    if any(d in search_result for d in tier1):
        return 0.3
    if any(d in search_result for d in tier2):
        return 0.2
    # 有 URL 但非上述域 → Tier-3
    if re.search(r'https?://', search_result):
        return 0.1
    return 0.0


def _estimate_source_count(search_result: str) -> int:
    """估算搜索结果中的独立信源数量"""
    urls = re.findall(r'https?://[^\s]+', search_result)
    # 去重域名
    domains = set()
    for url in urls:
        match = re.search(r'https?://([^/\s]+)', url)
        if match:
            domains.add(match.group(1))

    # 自然数：0 个 URL 返回 0，让上游按"信源不足"处理
    # （WM-FC-02：原 max(1,...) 把空结果当单信源，_compute_confidence 误加 +0.2 置信度虚高）
    return len(domains)


def _extract_numeric_values(text: str) -> list[float]:
    """从文本提取所有数值，统一为浮点数。

    支持：阿拉伯数字（含千分位）、'1270万'/'14.7亿'（阿拉伯+万/亿）、
    纯中文数字（'一千二百七十万'，仅含数量级单位时才转换）。
    """
    vals = []
    # 阿拉伯数字 + 可选 万/亿 单位
    for m in re.finditer(r'([\d,]+\.?\d*)\s*(亿|万)?', text):
        n = m.group(1).replace(',', '')
        if not n:
            continue
        try:
            v = float(n)
        except ValueError:
            continue
        if m.group(2) == '亿':
            v *= 1e8
        elif m.group(2) == '万':
            v *= 1e4
        vals.append(v)
    # 纯中文数字（仅含数量级单位 十/百/千/万/亿 的才转换，避免 "两成" 中的 "两" 误判）
    for m in re.finditer(r'[一二三四五六七八九十百千万亿两]+', text):
        tok = m.group()
        if not any(u in tok for u in '十百千万亿'):
            continue
        v = cn2num(tok)
        if v:
            vals.append(float(v))
    return vals


def _check_value_range(claim_text: str, search_result: str) -> bool:
    """检查声明的数值是否在搜索结果的合理范围内

    AHV-005：旧实现只提取阿拉伯数字，中文数字声明（"一千二百七十万"）无 claim_nums
    → 直接 return True 放行，数值核查对中文数字完全失效。现统一提取并比较
    声明与搜索结果中的数值（含中文数字与'1270万'格式）。
    """
    claim_nums = _extract_numeric_values(claim_text)
    if not claim_nums:
        return True  # 无数值，无法比较，默认通过

    result_nums = _extract_numeric_values(search_result)

    # 声明数字在搜索结果数字的 ±50% 范围内即视为一致
    for cv in claim_nums:
        for rv in result_nums:
            if rv == 0:
                continue
            ratio = cv / rv
            if 0.5 <= ratio <= 2.0:
                return True

    # 声明含数值、搜索结果无数值 → 默认存疑（WM-FC-01, audit-2026-07-05-001）。
    # 旧实现 `return len(result_nums) == 0` 让 DATA 声明在结果纯散文时默认通过，
    # 数值层校验形同虚设，叠加 _check_corroboration 文本命中即 VERIFIED。
    # 改为返回 False → 交由上游判 FALSIFIED 或 needs_claude_review，避免无数值佐证的数据声明误过门禁。
    return False


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="L4 事实验证器")
    sub = parser.add_subparsers(dest="mode", required=True)

    # plan 模式
    plan_parser = sub.add_parser("plan", help="生成搜索计划")
    plan_parser.add_argument("claims_json", help="claim_extractor 输出的 JSON 文件")
    plan_parser.add_argument("--max-queries", type=int, default=30, help="最大查询数")

    # verify 模式
    verify_parser = sub.add_parser("verify", help="验证声明")
    verify_parser.add_argument("claims_json", help="claim_extractor 输出的 JSON 文件")
    verify_parser.add_argument("results_json", help="搜索结果 JSON 文件 {claim_id: summary}")
    verify_parser.add_argument("--strictness", default="standard",
                               choices=["strict", "standard", "lenient"])

    args = parser.parse_args()

    if args.mode == "plan":
        with open(args.claims_json, 'r', encoding='utf-8') as f:
            data = json.load(f)

        claims = data.get("claims", data)  # 兼容两种输入格式
        result = generate_search_queries(claims, args.max_queries)
        queries = result["queries"]
        truncated_count = result["truncated_count"]

        print(json.dumps({
            "mode": "plan",
            "total_queries": len(queries),
            "truncated_count": truncated_count,
            "queries": queries,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))

    elif args.mode == "verify":
        with open(args.claims_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        claims = data.get("claims", data)

        with open(args.results_json, 'r', encoding='utf-8') as f:
            search_results = json.load(f)

        verified = verify_claims(claims, search_results, args.strictness)

        summary = {
            "total": len(verified),
            "verified": sum(1 for c in verified if c["verdict"] == "VERIFIED"),
            "unverifiable": sum(1 for c in verified if c["verdict"] == "UNVERIFIABLE"),
            "falsified": sum(1 for c in verified if c["verdict"] == "FALSIFIED"),
        }

        print(json.dumps({
            "mode": "verify",
            "summary": summary,
            "overall": "PASS" if summary["falsified"] == 0 else "FAIL",
            "claims": verified,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))

        if summary["falsified"] > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
