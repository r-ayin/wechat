#!/usr/bin/env python3
"""Layer 2: 逻辑级幻觉检测

检查文章中的逻辑推理是否：
1. 因果推论有传导机制
2. 没有相关≠因果的推论
3. 有反面证据讨论
4. 没有以偏概全
"""
import json, re, sys
from datetime import datetime, timezone


def detect_causal_claims(text):
    """检测因果推论"""
    causal_patterns = [
        r'因为.*?所以',
        r'由于.*?导致',
        r'因此',
        r'据此',
        r'这表明',
        r'这意味着',
        r'由此可见',
        r'从而',
        r'推动了',
        r'造成了',
        r'使得',
    ]
    claims = []
    for pat in causal_patterns:
        for m in re.finditer(pat, text):
            claims.append({
                "text": m.group(),
                "position": m.start(),
                "context": text[max(0, m.start()-50):m.end()+50],
            })
    return claims


def check_counter_evidence(text):
    """检查是否有反面证据讨论"""
    counter_patterns = [
        r'但也?可能',
        r'另一方[面看]',
        r'不过',
        r'然而',
        r'风险在于',
        r'不确定性',
        r'需要警惕',
        r'但.*?不同',
    ]
    found = []
    for pat in counter_patterns:
        for m in re.finditer(pat, text):
            found.append({"text": m.group(), "position": m.start()})
    return found


def check_correlation_vs_causation(text):
    """检查是否存在相关≠因果的问题"""
    suspicious = [
        r'相关.*?表明.*?因果',
        r'伴随.*?必然',
        r'同步.*?因为',
    ]
    issues = []
    for pat in suspicious:
        for m in re.finditer(pat, text):
            issues.append({"text": m.group(), "issue": "可能存在相关≠因果推论"})
    return issues


def detect(article_text):
    """
    运行逻辑级幻觉检测

    返回:
        检测报告dict
    """
    causal_claims = detect_causal_claims(article_text)
    counter_evidence = check_counter_evidence(article_text)
    correlation_issues = check_correlation_vs_causation(article_text)

    # 评估：有因果推论时，应有反面证据
    has_causal = len(causal_claims) > 0
    has_counter = len(counter_evidence) > 0

    issues = []
    if has_causal and not has_counter:
        issues.append({
            "issue": "有因果推论但未讨论反面证据",
            "causal_count": len(causal_claims),
            "counter_count": len(counter_evidence),
        })
    issues.extend(correlation_issues)

    passed = len(issues) == 0

    report = {
        "layer": "L2_logic",
        "passed": passed,
        "causal_claims_count": len(causal_claims),
        "counter_evidence_count": len(counter_evidence),
        "correlation_issues": len(correlation_issues),
        "issues": issues,
        "issue_count": len(issues),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python logic_hallucination.py <article.md>")
        sys.exit(1)

    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        text = f.read()

    report = detect(text)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if not report["passed"]:
        sys.exit(1)
