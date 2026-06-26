#!/usr/bin/env python3
"""Layer 3: 信源级幻觉检测 + 全文级验证

1. 抽查URL是否可访问
2. 检查信源多样性
3. 检查时间一致性
4. 检查单位一致性

支持双模式：
- finance: 检查 B/亿、M/万 单位一致性
- general: 跳过单位一致性检查
"""
import json, re, sys
from datetime import datetime, timezone

# =========================================================================
# 可配置单位对（按模式）
# =========================================================================
UNIT_PAIRS = {
    "finance": {
        "billion_B": r'\d+\.?\d*\s*B\b',
        "billion_亿": r'\d+\.?\d*\s*亿',
        "million_M": r'\d+\.?\d*\s*M\b',
        "million_万": r'\d+\.?\d*\s*万',
    },
    "general": {},  # 通用模式暂不检查单位一致性
}


def extract_urls(text):
    """提取所有URL"""
    pattern = r'https?://[^\s\)\]<>"]+'
    urls = []
    seen = set()
    for m in re.finditer(pattern, text):
        url = m.group().rstrip('.,;')
        if url not in seen:
            seen.add(url)
            urls.append({"url": url, "position": m.start(), "domain": re.findall(r'https?://([^/]+)', url)[0] if re.findall(r'https?://([^/]+)', url) else ""})
    return urls


def check_source_diversity(urls):
    """检查信源多样性"""
    domains = [u["domain"] for u in urls]
    unique_domains = set(domains)
    domain_counts = {}
    for d in domains:
        domain_counts[d] = domain_counts.get(d, 0) + 1

    return {
        "total_urls": len(urls),
        "unique_domains": len(unique_domains),
        "domains": dict(sorted(domain_counts.items(), key=lambda x: -x[1])),
        "diversity_score": len(unique_domains) / max(len(urls), 1),
    }


def check_temporal_consistency(text):
    """检查时间一致性 - 没有未来日期引用"""
    year_pattern = r'20[2-3]\d'
    years = [int(y) for y in re.findall(year_pattern, text)]
    current_year = datetime.now(timezone.utc).year
    issues = []
    for y in years:
        if y > current_year + 1:
            issues.append({"year": y, "issue": f"引用了未来年份（当前{current_year}）"})
    return issues


def check_units(text, mode="finance"):
    """检查单位一致性 - 同一指标的单位是否统一

    Args:
        text: 文章全文
        mode: 检测模式 ("finance" / "general")
              finance: 检查 B/亿、M/万 混用
              general: 跳过（返回空列表）
    """
    unit_patterns = UNIT_PAIRS.get(mode, UNIT_PAIRS["finance"])

    # general 模式无单位对，直接返回空
    if not unit_patterns:
        return []

    found_units = {}
    for name, pat in unit_patterns.items():
        matches = re.findall(pat, text)
        if matches:
            found_units[name] = len(matches)

    issues = []
    if found_units.get("billion_B") and found_units.get("billion_亿"):
        issues.append({"issue": "同时使用B和亿表示十亿级单位", "detail": found_units})
    if found_units.get("million_M") and found_units.get("million_万"):
        issues.append({"issue": "同时使用M和万表示百万级单位", "detail": found_units})

    return issues


def detect(article_text, sample_rate=0.1, mode="finance"):
    """
    运行信源级幻觉检测

    参数:
        article_text: 文章全文
        sample_rate: URL抽样比例
        mode: 检测模式 ("finance" / "general")，默认 "finance" 保持向后兼容

    返回:
        检测报告dict
    """
    urls = extract_urls(article_text)
    diversity = check_source_diversity(urls)
    temporal_issues = check_temporal_consistency(article_text)
    unit_issues = check_units(article_text, mode=mode)

    all_issues = temporal_issues + unit_issues
    passed = len(all_issues) == 0 and diversity["unique_domains"] >= 5

    if diversity["unique_domains"] < 5:
        all_issues.append({"issue": f"信源多样性不足（{diversity['unique_domains']}个域名，需要≥5）"})

    report = {
        "layer": "L3_source_full",
        "passed": passed,
        "source_diversity": diversity,
        "temporal_issues": temporal_issues,
        "unit_issues": unit_issues,
        "all_issues": all_issues,
        "issue_count": len(all_issues),
        "url_sample_note": f"URL连通性需手动抽查{int(sample_rate*100)}%",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python source_hallucination.py <article.md> [--mode finance|general]")
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
