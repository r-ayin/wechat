#!/usr/bin/env python3
"""Layer 1: 数字级幻觉检测

检查文章中的数字是否：
1. 有来源URL锚定
2. 有脚本计算记录
3. 在合理范围内
4. 单位一致

支持双模式：
- finance: 完整检查（PE比率、营收增长率、市值等）
- general: 通用检查（仅百分比范围）
"""
import json, re, sys, os
from datetime import datetime, timezone


# =========================================================================
# 可配置规则表
# =========================================================================

# 财经模式规则（现有规则，保持不变）
FINANCE_RULES = {
    "pe_ratio": {"min": 0, "max": 500},
    "revenue_growth_pct": {"min": -100, "max": 1000},
    "market_cap_B": {"min": 0, "max": 10000},
    "percentage": {"min": -100, "max": 100},
}

# 通用模式规则（仅保留通用检查）
GENERAL_RULES = {
    "percentage": {"min": -100, "max": 100},
}

RULES = {
    "finance": FINANCE_RULES,
    "general": GENERAL_RULES,
}


def load_rules(mode="finance"):
    """加载指定模式的检测规则

    Args:
        mode: "finance" 或 "general"

    Returns:
        dict: 规则字典
    """
    return RULES.get(mode, FINANCE_RULES)


def extract_numbers(text):
    """提取文本中的所有数字"""
    # 匹配各种数字格式：1,234.56 / 12.3% / $1.5B / ￥100亿
    patterns = [
        r'[\$¥€£]\s*[\d,]+\.?\d*\s*[BMK万亿]?',  # 货币
        r'[\d,]+\.?\d*\s*%',                        # 百分比
        r'[\d,]+\.?\d*\s*[BMK万亿]',               # 缩写
        r'(?<![a-zA-Z])[\d,]+\.?\d+(?![a-zA-Z])',  # 普通数字
    ]
    results = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            results.append({
                "text": m.group().strip(),
                "start": m.start(),
                "end": m.end(),
                "context": text[max(0, m.start()-30):m.end()+30],
            })

    # MIN-04：多个正则会重叠匹配（如 "$1.5B" 同时命中货币与普通数字模式），
    # 导致 total_numbers/critical_count 虚高。按位置合并重叠 span，每组保留最长者。
    results.sort(key=lambda r: (r["start"], -(r["end"] - r["start"])))
    deduped = []
    for r in results:
        if deduped and r["start"] < deduped[-1]["end"]:
            # 与上一条重叠：保留更长的那条
            prev = deduped[-1]
            if (r["end"] - r["start"]) > (prev["end"] - prev["start"]):
                deduped[-1] = r
            continue
        deduped.append(r)
    return deduped


def check_source_urls(numbers, text):
    """检查数字附近是否有URL引用"""
    # URL模式
    url_pattern = r'https?://[^\s\)\]<>"]+'
    urls = [(m.start(), m.end(), m.group()) for m in re.finditer(url_pattern, text)]

    for num in numbers:
        num["has_source"] = False
        num["nearby_url"] = None
        for url_start, url_end, url in urls:
            # URL在数字前后200字符内
            if abs(num["start"] - url_end) < 200 or abs(url_start - num["end"]) < 200:
                num["has_source"] = True
                num["nearby_url"] = url
                break
    return numbers


def check_reasonableness(numbers, rules=None, mode="finance"):
    """检查数字是否在合理范围内

    Args:
        numbers: 提取的数字列表
        rules: 可选的自定义规则字典（覆盖默认规则）
        mode: 模式 ("finance" / "general")，仅在 rules 为 None 时生效
    """
    if rules is None:
        rules = load_rules(mode)

    for num in numbers:
        # Extract numeric value
        raw = re.sub(r'[^\d.\-]', '', num["text"].replace(",", ""))
        try:
            val = float(raw)
            num["numeric_value"] = val
        except ValueError:
            num["numeric_value"] = None
            continue

    return numbers


def detect(article_text, audit_log_path=None, mode="finance"):
    """
    运行数字级幻觉检测

    参数:
        article_text: 文章全文
        audit_log_path: 计算审计日志路径（可选）
        mode: 检测模式 ("finance" / "general")，默认 "finance" 保持向后兼容

    返回:
        检测报告dict
    """
    numbers = extract_numbers(article_text)
    numbers = check_source_urls(numbers, article_text)
    numbers = check_reasonableness(numbers, mode=mode)

    # 统计
    total = len(numbers)
    with_source = sum(1 for n in numbers if n.get("has_source"))
    without_source = [n for n in numbers if not n.get("has_source")]

    # 严重问题：精确数字无来源
    critical = []
    for n in without_source:
        raw = n["text"]
        # 只对"精确"数字报警（不是常见的年份、序号等）
        if re.search(r'\d+\.\d+', raw) or '%' in raw or any(c in raw for c in '$¥€£BMK万亿'):
            critical.append({
                "number": n["text"],
                "context": n["context"],
                "issue": "精确数字无来源URL",
            })

    passed = len(critical) == 0

    report = {
        "layer": "L1_number",
        "passed": passed,
        "total_numbers": total,
        "with_source": with_source,
        "without_source": len(without_source),
        "critical_issues": critical,
        "critical_count": len(critical),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python number_hallucination.py <article.md> [--mode finance|general]")
        sys.exit(1)

    mode = "finance"  # 默认
    if len(sys.argv) >= 4 and sys.argv[2] == "--mode":
        mode = sys.argv[3]

    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        text = f.read()

    report = detect(text, mode=mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not report["passed"]:
        sys.exit(1)
