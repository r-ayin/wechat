#!/usr/bin/env python3
"""
L4 声明提取器 — 从口播脚本中提取四类可验证声明。

四类声明：
  PERSON — 有名有姓的人物、有明确身份的代称
  EVENT  — 带时间/地点的具体事件、政策出台、报道发布
  DATA   — 精确数字、百分比、统计量
  QUOTE  — 政策名称、报告标题、专家言论归属

输出：JSON claims 数组，每条含 id/type/text/context/verification_hint
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# =========================================================================
# 提取规则表
# =========================================================================

# --- PERSON: 人物声明 ---
# 中文全名：常见百家姓 + 1-2个CJK字符
_SURNAMES = (
    '王李张刘陈杨黄赵周吴徐孙马胡朱郭何罗高林郑梁谢唐'
    '许冯宋韩邓彭曹曾田萧潘袁蔡蒋余于杜叶程魏苏吕丁任'
    '卢姚钟姜崔谭陆范汪廖石金贾韦夏付方白邹孟熊秦邱江'
    '尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤'
)
PERSON_NAME_RE = re.compile(r'[' + _SURNAMES + r'][一-鿿]{1,2}')

# 非人名过滤：常见非人名双字组合
_NON_NAME_WORDS = {
    '小时', '下载', '什么', '怎么', '可以', '没有', '自己', '知道', '一个',
    '因为', '所以', '但是', '不过', '然后', '如果', '虽然', '已经', '这个',
    '那个', '这些', '那些', '很多', '可能', '不是', '还是', '或者', '只是',
    '不会', '不能', '不要', '不用', '不同', '一样', '一直', '一些', '起来',
    '出来', '回来', '过来', '过去', '进去', '下去', '上去', '开始', '出来',
    '如何', '于是', '对于', '由于', '等于', '关于', '终于', '至于',
    '但是', '而且', '或者', '所以', '因此', '然而', '虽然', '不过',
    '下午', '上午', '今天', '明天', '昨天', '现在', '以后', '以前',
}

# 化名黑名单：常见词不以化名处理
_NICKNAME_BLACKLIST = {
    '老板', '老师', '老大', '老公', '老婆', '老妈', '老爸',
    '小时', '小看', '小结', '小组', '小心', '小说',
}

# 化名模式：老X / 小X / X姐 / X哥 / X师傅 / X总
NICKNAME_RE = re.compile(
    r'(?:老[一-鿿]|小[一-鿿]'
    r'|[一-鿿]{1,2}(?:姐|哥|师傅|叔|姨|总|工|老师))'
)

# 年龄+职业模式："今年43岁"、"38岁，开网约车"
AGE_ROLE_RE = re.compile(
    r'今年(\d{1,3})岁.*?(?:在|，|,).*?(?:做|跑|干|当|是).*?([。，,\.\n]|$)'
)

# 年龄锚点（AHV-004：支持中文数字年龄，如 "今年三十二岁"、"四十五岁"）
# groups: 1=今年+阿拉伯, 2=阿拉伯, 3=今年+中文, 4=中文
AGE_ANCHOR_RE = re.compile(
    r'今年(\d{1,3})岁|(\d{1,3})岁|今年([一二三四五六七八九十百]+)岁|([一二三四五六七八九十百]+)岁'
)

def _anchor_age(anchor) -> str | None:
    """从年龄锚点 match 提取年龄值（阿拉伯数字字符串），中文数字自动转换。"""
    if anchor.group(1):
        return anchor.group(1)
    if anchor.group(2):
        return anchor.group(2)
    cn = anchor.group(3) or anchor.group(4)
    if cn:
        converted = cn2num(cn)
        return str(converted) if converted else cn
    return None

# --- EVENT: 事件声明 ---
# 日期模式
DATE_RE = re.compile(
    r'(?:(\d{4})年(\d{1,2})月(?:(\d{1,2})日)?)'
)

# 报道来源模式（要求更严格的来源标识）
REPORT_SOURCE_RE = re.compile(
    r'(?:据|根据|援引|引用|来源[：:]|参考)\s*'
    r'([^，。,\.\n]{3,50}(?:报道|发布|数据|统计|调查|研究|指出|显示|消息))'
)

# 政策/文件出台模式
POLICY_INTRO_RE = re.compile(
    r'(\d{4}年\d{1,2}月)\s*(?:出台|发布|实施|生效|通过|印发)的?'
    r'(?:了)?\s*[《〈]([^》〉]+)[》〉]'
)

# --- DATA: 数据声明 ---
# 带上下文的数字（复用 godtier 规则 + 脚本特有模式）
DATA_PATTERNS = [
    # 中文数字："六十万"、"三百五十亿"、"两成"、"七成"
    (re.compile(r'(?:[一二三四五六七八九十百千万亿两]+)\s*(?:亿|万|千|百|个|家|人|元|块|美元|%|倍|成|例)'), 'quantity_cn'),
    # 百分比："超过30%"、"占比高达65%"
    (re.compile(r'(?:超过|达到|高达|约为|仅有|不到|占比?|增长|下降|提升|降低|年增)'
                r'\s*[\d,]+\.?\d*\s*%'), 'percentage'),
    # 数量+单位："2亿灵活就业者"、"5000出头"、"月均8000多"
    (re.compile(r'[\d,]+\.?\d*\s*(?:亿|万|千|百|个|家|人|元|块|美元|%|倍|成)'), 'quantity'),
    # 比例："每三个骑手里"、"三成"
    (re.compile(r'(?:每[二三四五六七八九十\d]+个|[二三四五六七八九十\d]+成)'), 'ratio'),
    # 趋势数字："增长了3倍"、"下降了40%"
    (re.compile(r'(?:增长|下降|提升|降低|减少|增加|翻)了?\s*[\d,]+\.?\d*\s*(?:倍|%|成)'), 'trend'),
]

# --- QUOTE: 引用声明 ---
# 《书名号》包裹的政策/报告/文件
TITLE_RE = re.compile(r'[《〈]([^》〉]{2,60})[》〉]')

# "某某说/指出/认为/强调/表示" 归属模式
ATTRIBUTION_RE = re.compile(
    r'([^\s，。,!！?？]{2,20}(?:专家|学者|教授|研究员|主任|负责人|代表|人士|医生|律师|记者|编辑))'
    r'\s*(?:说|指出|认为|强调|表示|称|写道|提到|介绍)'
)


# =========================================================================
# 中文数字转换 + 通用量词过滤（AHV-001 / AHV-004 / AHV-010）
# =========================================================================

_CN_DIGIT = {'零':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
_CN_UNIT = {'十':10,'百':100,'千':1000,'万':10000,'亿':100000000}

def cn2num(s: str) -> int | None:
    """中文数字字符串转 int。支持 '三十二' '一百二十七' '十四万' '一千二百七十万' 等。
    无法解析返回 None。"""
    if not s:
        return None
    total = 0          # 累计的亿/万段合计
    section = 0        # 当前万以内的累计
    number = 0         # 上一个单独数字 0-9
    for ch in s:
        if ch in _CN_DIGIT:
            number = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            if ch == '十':
                section += (number if number else 1) * unit
            elif ch in ('百', '千'):
                section += number * unit
            else:  # 万 / 亿 —— 段分隔符，把当前 section 收拢后乘以万/亿
                section = (section + number) * unit
                total += section
                section = 0
            number = 0
        else:
            return None
    result = total + section + number
    return result if result > 0 else None

# 通用量词单位：与<100的小数字组合时视为叙述性量词，不作为可验证数据声明
_GENERIC_MEASURE_UNITS = {
    '个','名','位','只','条','块','件','种','项','份','篇','段','句','话',
    '年','天','月','周','日','时','点','分','秒','步','次','回','遍','场',
    '顿','口','座','把','张','本','辆','台','家','人','起','桩','单','门',
}

def _is_noise_quantifier(data_text: str) -> bool:
    """判断 quantity_cn 命中是否为叙述性噪声量词（如 '三个' '一个' '六百块' 的小数）。
    统计性单位（亿/万/千/百/%/倍/成/美元/元/例）即便小也保留。"""
    m = re.match(r'^([一二三四五六七八九十百千万亿两]+)\s*(亿|万|千|百|个|家|人|元|块|美元|%|倍|成|例)', data_text)
    if not m:
        return False
    numeral, unit = m.group(1), m.group(2)
    # 统计性单位直接保留
    if unit in ('亿','万','%','倍','成','美元'):
        return False
    val = cn2num(numeral)
    # 无法解析或 < 100 且为通用量词 → 噪声
    if val is None:
        return False
    if val < 100 and unit in _GENERIC_MEASURE_UNITS:
        return True
    return False


# =========================================================================
# 提取函数
# =========================================================================

def extract_person_claims(text: str) -> list[dict]:
    """提取人物声明 — 年龄锚点驱动，高精度低召回"""
    claims = []
    seen = set()

    # 找到所有"今年X岁"或"X岁"的年龄锚点（含中文数字）
    age_anchors = []
    for m in AGE_ANCHOR_RE.finditer(text):
        age_anchors.append(m)

    # 从每个年龄锚点向外扩展，找最近的（≤50 字符）人名或化名
    for anchor in age_anchors:
        search_start = max(0, anchor.start() - 50)
        search_end = min(len(text), anchor.end() + 50)
        search_region = text[search_start:search_end]
        anchor_pos_in_region = anchor.start() - search_start

        # 全名
        for m in PERSON_NAME_RE.finditer(search_region):
            name = m.group()
            if name in seen or name in _NON_NAME_WORDS:
                continue
            # 名字必须在锚点前 40 字符内出现
            if m.start() > anchor_pos_in_region + 20:
                continue

            seen.add(name)

            ctx_start = max(0, search_start + m.start() - 20)
            ctx_end = min(len(text), search_start + m.end() + 80)
            context = text[ctx_start:ctx_end].strip()

            role_match = re.search(
                r'(?:在|跑|做|干|当|开|送|接|是)([^。，,\.\n]{2,25})',
                context
            )
            age_val = _anchor_age(anchor)
            claims.append({
                "id": f"P-{len(claims)+1:03d}",
                "type": "PERSON",
                "text": name,
                "context": context[:150],
                "position": search_start + m.start(),
                "is_full_name": True,
                "has_role_info": bool(role_match),
                "age": age_val,
                "role_hint": role_match.group(1).strip() if role_match else None,
                "verification_hint": (
                    f"搜索确认「{name}」是否真实存在"
                    f"（{age_val}岁"
                    + (f"，{role_match.group(1).strip()}" if role_match else "")
                    + "）"
                ),
            })
            break  # 每个年龄锚点只取最近的一个全名

        # 化名
        for m in NICKNAME_RE.finditer(search_region):
            nickname = m.group()
            if nickname in seen or nickname in _NICKNAME_BLACKLIST:
                continue
            if m.start() > anchor_pos_in_region + 30:
                continue

            seen.add(nickname)

            ctx_start = max(0, search_start + m.start() - 40)
            ctx_end = min(len(text), search_start + m.end() + 80)
            context = text[ctx_start:ctx_end].strip()

            role_match = re.search(
                r'(?:在|跑|做|干|当|开|送|接|是)([^。，,\.\n]{2,25})',
                context
            )
            age_val = _anchor_age(anchor)
            claims.append({
                "id": f"P-{len(claims)+1:03d}",
                "type": "PERSON",
                "text": nickname,
                "context": context[:150],
                "position": search_start + m.start(),
                "is_full_name": False,
                "is_pseudonym": True,
                "has_role_info": bool(role_match),
                "age": age_val,
                "role_hint": role_match.group(1).strip() if role_match else None,
                "verification_hint": (
                    f"化名「{nickname}」— 验证{age_val}岁身份背景"
                    + (f"（{role_match.group(1).strip()}）" if role_match else "")
                    + "是否与行业常态一致"
                ),
            })
            break

    return claims


def extract_event_claims(text: str) -> list[dict]:
    """提取事件声明"""
    claims = []

    # 日期+事件
    for m in DATE_RE.finditer(text):
        year, month, day = m.group(1), m.group(2), m.group(3)

        ctx_start = max(0, m.start() - 30)
        ctx_end = min(len(text), m.end() + 120)
        context = text[ctx_start:ctx_end].strip()

        # 过滤掉"2026年6月"做时间状语但无具体事件的
        # 至少要有动作词
        has_action = bool(re.search(r'(?:出台|发布|报道|指出|显示|发生|出现|开始|成立|推出|上线'
                                     r'|下架|爆发|通过|实施|生效|召开|举行|公布)', context))
        if not has_action:
            continue

        date_str = f"{year}年{month}月"
        if day:
            date_str += f"{day}日"

        claims.append({
            "id": f"E-{len(claims)+1:03d}",
            "type": "EVENT",
            "text": date_str,
            "context": context[:150],
            "position": m.start(),
            "date": date_str,
            "verification_hint": f"搜索「{date_str} {context[:40]}」确认事件是否真实发生",
        })

    # 报道来源
    for m in REPORT_SOURCE_RE.finditer(text):
        source_text = m.group(1)
        ctx_start = max(0, m.start() - 20)
        ctx_end = min(len(text), m.end() + 60)
        context = text[ctx_start:ctx_end].strip()

        claims.append({
            "id": f"E-{len(claims)+1:03d}",
            "type": "EVENT",
            "text": f"来源：{source_text}",
            "context": context[:150],
            "position": m.start(),
            "verification_hint": f"搜索确认「{source_text}」是否真实存在",
        })

    # 政策出台
    for m in POLICY_INTRO_RE.finditer(text):
        date_part = m.group(1)
        policy_name = m.group(2)

        ctx_start = max(0, m.start() - 10)
        ctx_end = min(len(text), m.end() + 60)
        context = text[ctx_start:ctx_end].strip()

        claims.append({
            "id": f"E-{len(claims)+1:03d}",
            "type": "EVENT",
            "text": f"{date_part}出台《{policy_name}》",
            "context": context[:150],
            "position": m.start(),
            "date": date_part,
            "policy_name": policy_name,
            "verification_hint": f"搜索「{date_part} 《{policy_name}》」确认政策是否真实出台",
        })

    return claims


def extract_data_claims(text: str) -> list[dict]:
    """提取数据声明"""
    claims = []

    for pattern, data_type in DATA_PATTERNS:
        for m in pattern.finditer(text):
            data_text = m.group().strip()

            ctx_start = max(0, m.start() - 50)
            ctx_end = min(len(text), m.end() + 80)
            context = text[ctx_start:ctx_end].strip()

            # 跳过明显不是数据的（如章节编号、电话号）
            if re.match(r'^\d{1,2}[。．、）\)]', data_text):
                continue

            # AHV-001/AHV-010：过滤中文数字+通用量词的叙述性噪声（"三个""一个"）
            if data_type == 'quantity_cn' and _is_noise_quantifier(data_text):
                continue

            # 检查上下文是否有来源线索
            has_source_nearby = bool(re.search(
                r'(?:据|根据|按照|引用|来自|来源|报道|统计|调查|研究|数据|显示|指出)',
                context
            ))

            # 检查数字的精确度
            has_decimal = '.' in data_text or '．' in data_text
            is_approximate = bool(re.search(r'(?:约|大概|大约|左右|多|出头|以上|以下)', context))

            claims.append({
                "id": f"D-{len(claims)+1:03d}",
                "type": "DATA",
                "text": data_text,
                "data_type": data_type,
                "context": context[:150],
                "position": m.start(),
                "has_source_in_text": has_source_nearby,
                "is_precise": has_decimal,
                "is_approximate": is_approximate,
                "risk": "high" if (has_decimal and not has_source_nearby and not is_approximate) else "medium",
                "verification_hint": f"搜索确认「{data_text}」的数据来源" +
                                     ("（精确数字无来源，高风险）" if has_decimal and not has_source_nearby else ""),
            })

    return claims


def extract_quote_claims(text: str) -> list[dict]:
    """提取引用声明"""
    claims = []

    # 《书名号》引用
    for m in TITLE_RE.finditer(text):
        title = m.group(1)

        # 跳过明显不是正式引用的（如文学性比喻）
        if len(title) < 3:
            continue
        if re.search(r'(?:热浪|低吼|太阳|大海|风暴|命运)', title):
            continue

        ctx_start = max(0, m.start() - 30)
        ctx_end = min(len(text), m.end() + 40)
        context = text[ctx_start:ctx_end].strip()

        # 判断类型
        if re.search(r'(?:法|条例|规定|办法|通知|指引|原则|标准|规范)', title):
            ref_type = 'policy'
        elif re.search(r'(?:报告|报道|调查|研究|统计|数据|白皮书|蓝皮书)', title):
            ref_type = 'report'
        else:
            ref_type = 'other'

        claims.append({
            "id": f"Q-{len(claims)+1:03d}",
            "type": "QUOTE",
            "text": f"《{title}》",
            "ref_type": ref_type,
            "context": context[:120],
            "position": m.start(),
            "verification_hint": f"搜索确认「《{title}》」是否真实存在" +
                                 ("（政策/法规，需精确匹配名称）" if ref_type == 'policy' else ""),
        })

    # 专家归属
    for m in ATTRIBUTION_RE.finditer(text):
        person_title = m.group(1)

        ctx_start = max(0, m.start() - 20)
        ctx_end = min(len(text), m.end() + 60)
        context = text[ctx_start:ctx_end].strip()

        claims.append({
            "id": f"Q-{len(claims)+1:03d}",
            "type": "QUOTE",
            "text": f"{person_title}{m.group(0)[len(person_title):]}",
            "ref_type": "attribution",
            "context": context[:150],
            "position": m.start(),
            "verification_hint": f"搜索确认「{person_title}」是否发表过相关言论",
        })

    return claims


# =========================================================================
# 主编排
# =========================================================================

def extract_all(text: str, script_path: str = None) -> dict:
    """提取所有四类声明

    Args:
        text: 脚本文本全文
        script_path: 脚本文件路径（可选，用于报告）

    Returns:
        {"claims": [...], "summary": {...}}
    """
    person_claims = extract_person_claims(text)
    event_claims = extract_event_claims(text)
    data_claims = extract_data_claims(text)
    quote_claims = extract_quote_claims(text)

    all_claims = person_claims + event_claims + data_claims + quote_claims

    # 按位置排序
    all_claims.sort(key=lambda c: c["position"])

    # 去重：同类型+相同文本+位置<300字符 → 保留第一个
    # AHV-010：对短文本（≤4字符，如通用量词残留）做全局去重，无论位置距离
    deduped = []
    seen_global = set()
    for claim in all_claims:
        text = claim["text"]
        # 短文本全局去重（防止 "30%" 之外的残余重复量词跨段保留）
        global_key = (claim["type"], text) if len(text) <= 4 else None
        if global_key is not None and global_key in seen_global:
            continue
        is_dup = False
        for existing in deduped:
            if (claim["type"] == existing["type"]
                    and claim["text"] == existing["text"]
                    and abs(claim["position"] - existing["position"]) < 300):
                is_dup = True
                break
        if not is_dup:
            deduped.append(claim)
            if global_key is not None:
                seen_global.add(global_key)

    all_claims = deduped

    # 重新编号
    for i, claim in enumerate(all_claims):
        claim["id"] = f"C-{i+1:03d}"

    high_risk = [c for c in all_claims if c.get("risk") == "high"]
    pseudonym_persons = [c for c in all_claims if c.get("is_pseudonym")]

    # AHV-002：by_type 必须基于去重后的 all_claims，与 total 一致
    from collections import Counter
    type_counts = Counter(c["type"] for c in all_claims)
    summary = {
        "total": len(all_claims),
        "by_type": {
            "PERSON": type_counts.get("PERSON", 0),
            "EVENT": type_counts.get("EVENT", 0),
            "DATA": type_counts.get("DATA", 0),
            "QUOTE": type_counts.get("QUOTE", 0),
        },
        "high_risk_count": len(high_risk),
        "pseudonym_count": len(pseudonym_persons),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }

    if script_path:
        summary["script"] = script_path

    return {
        "claims": all_claims,
        "summary": summary,
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python claim_extractor.py <script.md> [--json]")
        print("  --json  输出纯 JSON（默认带摘要头）")
        sys.exit(1)

    script_path = sys.argv[1]
    json_only = "--json" in sys.argv

    with open(script_path, 'r', encoding='utf-8') as f:
        text = f.read()

    result = extract_all(text, script_path)

    if json_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"=== Claim Extraction: {Path(script_path).name} ===")
        print(f"Total claims: {result['summary']['total']}")
        print(f"  PERSON: {result['summary']['by_type']['PERSON']}")
        print(f"  EVENT:  {result['summary']['by_type']['EVENT']}")
        print(f"  DATA:   {result['summary']['by_type']['DATA']}")
        print(f"  QUOTE:  {result['summary']['by_type']['QUOTE']}")
        print(f"  High risk: {result['summary']['high_risk_count']}")
        print(f"  Pseudonyms: {result['summary']['pseudonym_count']}")
        print()

        for claim in result["claims"]:
            risk_flag = "HIGH" if claim.get("risk") == "high" else "LO" if claim.get("is_pseudonym") else "  "
            print(f"[{risk_flag}] [{claim['type']}] {claim['text'][:60]}")
            print(f"     |-- {claim['verification_hint'][:100]}")
            print()

        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
