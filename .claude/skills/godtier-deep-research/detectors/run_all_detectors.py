#!/usr/bin/env python3
"""运行所有三层幻觉检测，生成综合报告"""
import json, sys, os
from datetime import datetime, timezone

# Add detectors to path
DETECTORS_DIR = os.path.dirname(__file__)

def detect_all(article_path, mode="finance"):
    """运行所有三层幻觉检测，生成综合报告

    Args:
        article_path: 文章路径
        mode: 检测模式 ("finance" / "general")，IMP-03：旧实现不传 mode，
              非金融场景也套金融数值区间（PE 0-500 等），现透传给子检测器。
    """
    with open(article_path, 'r', encoding='utf-8') as f:
        text = f.read()

    results = {}

    # Layer 1: Number hallucination
    sys.path.insert(0, DETECTORS_DIR)
    from number_hallucination import detect as detect_numbers
    results["layer1_number"] = detect_numbers(text, mode=mode)

    # Layer 2: Logic hallucination（logic 检测器无 mode 参数，不透传）
    from logic_hallucination import detect as detect_logic
    results["layer2_logic"] = detect_logic(text)

    # Layer 3: Source + full text
    from source_hallucination import detect as detect_source
    results["layer3_source"] = detect_source(text, mode=mode)

    # Overall result
    all_passed = all(r["passed"] for r in results.values())

    report = {
        "overall": "PASS" if all_passed else "FAIL",
        "article": article_path,
        "layers": results,
        "summary": {
            "layer1_passed": results["layer1_number"]["passed"],
            "layer2_passed": results["layer2_logic"]["passed"],
            "layer3_passed": results["layer3_source"]["passed"],
            "critical_numbers": results["layer1_number"].get("critical_count", 0),
            "logic_issues": results["layer2_logic"].get("issue_count", 0),
            "source_issues": results["layer3_source"].get("issue_count", 0),
        },
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_all_detectors.py <article.md> [output.json] [--mode finance|general]")
        sys.exit(1)

    article_path = sys.argv[1]
    output_path = None
    mode = "finance"
    # 解析可选 --mode 与 output 路径
    rest = sys.argv[2:]
    if "--mode" in rest:
        idx = rest.index("--mode")
        mode = rest[idx + 1]
        rest = rest[:idx] + rest[idx + 2:]
    if rest:
        output_path = rest[0]

    report = detect_all(article_path, mode=mode)

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Report saved to {output_path}")
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["overall"] != "PASS":
        sys.exit(1)
