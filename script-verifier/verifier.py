#!/usr/bin/env python3
"""
L4 脚本验证主编排器

完整流程：
  ① claim_extractor → 提取四类声明
  ② fact_checker plan → 生成搜索计划
  ③ [Claude 执行 WebSearch] → 收集搜索结果
  ④ fact_checker verify → 逐条判定
  ⑤ 任一条 FALSIFIED → 修复闭环（最多 3 次）
  ⑥ 生成最终验证报告

用法：
  # 步骤 1: 提取声明 + 生成搜索计划
  python verifier.py extract <script.md> --output claims.json

  # 步骤 2: Claude 执行 WebSearch（手动/在 Skill 中），结果写入 results.json
  #   {"C-001": "搜索摘要...", "C-002": "搜索摘要..."}

  # 步骤 3: 判定 + 生成报告
  python verifier.py judge claims.json --results results.json --output report.json

  # 或一条命令跑通（如果已有 results.json）
  python verifier.py verify <script.md> --results results.json
"""

import json
import os
import re
import sys
import io
from datetime import datetime, timezone
from pathlib import Path

# 跨平台编码安全：Windows GBK 终端无法输出 emoji/CJK
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 添加模块路径
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from claim_extractor import extract_all
from fact_checker import generate_search_queries, verify_claims


MAX_RETRIES = 3


def _count_words(text: str) -> int:
    """统计真实词数（AHV-007）。

    CJK 每字算一词，拉丁字母串/数字串各算一词；不再把标点、空白、markdown 语法
    当作词，避免 len(text) 那样把字符数误报为词数（旧实现偏高约 20%）。
    """
    return len(re.findall(r'[一-鿿]|[A-Za-z]+|\d+', text))


def _atomic_write_text(path: str, text: str) -> None:
    """原子写文本（WM-VER-02, audit-2026-07-05-001）。

    tmp + os.replace + os.fsync：避免崩溃半写导致下游 pipeline-gate 的 grep 兜底
    读到残缺 JSON 字段（如 `"falsified": 0` 片段）而误判门禁通过。
    """
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


# =========================================================================
# 提取 + 搜索计划
# =========================================================================

def extract_and_plan(script_path: str) -> dict:
    """步骤 1: 提取声明 + 生成搜索计划

    Args:
        script_path: 脚本 markdown 文件路径

    Returns:
        {"claims": [...], "search_plan": {...}}
    """
    with open(script_path, 'r', encoding='utf-8') as f:
        text = f.read()

    # 提取
    extracted = extract_all(text, script_path)
    claims = extracted["claims"]

    # 生成搜索计划
    plan_result = generate_search_queries(claims)
    queries = plan_result["queries"]
    truncated_count = plan_result["truncated_count"]

    return {
        "script": script_path,
        "script_name": Path(script_path).name,
        "total_words": _count_words(text),
        "extracted_at": extracted["summary"]["extracted_at"],
        "claims": claims,
        "extraction_summary": extracted["summary"],
        "search_plan": {
            "total_queries": len(queries),
            "truncated_count": truncated_count,
            "queries": queries,
        },
    }


# =========================================================================
# 判定 + 报告
# =========================================================================

def judge_and_report(
    claims: list[dict],
    search_results: dict[str, str],
    script_path: str = None,
    strictness: str = "standard",
) -> dict:
    """步骤 3: 逐条判定 + 生成报告

    Args:
        claims: 声明列表
        search_results: {claim_id: "搜索摘要"} 映射
        script_path: 脚本路径（用于报告）
        strictness: "strict" | "standard" | "lenient"

    Returns:
        完整验证报告
    """
    verified = verify_claims(claims, search_results, strictness)

    # 统计
    falsified = [c for c in verified if c["verdict"] == "FALSIFIED"]
    unverifiable = [c for c in verified if c["verdict"] == "UNVERIFIABLE"]
    verified_ok = [c for c in verified if c["verdict"] == "VERIFIED"]

    # 关键失败：FALSIFIED 或 高风险 UNVERIFIABLE
    critical_fails = falsified + [
        c for c in unverifiable
        if c.get("risk") == "high" or c.get("ref_type") == "policy"
    ]

    needs_remediation = len(falsified) > 0
    has_caveats = len(unverifiable) > 0

    if needs_remediation:
        overall = "FAIL"
    elif has_caveats:
        overall = "PASS_WITH_CAVEATS"
    else:
        overall = "PASS"

    report = {
        "script": script_path or "unknown",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "strictness": strictness,
        "overall": overall,
        "summary": {
            "total": len(verified),
            "verified": len(verified_ok),
            "unverifiable": len(unverifiable),
            "falsified": len(falsified),
            "critical_fails": len(critical_fails),
        },
        "claims": verified,
        "falsified_claims": [
            {
                "id": c["id"],
                "type": c["type"],
                "text": c["text"],
                "reason": c.get("verdict_reason", ""),
                "context": c.get("context", "")[:100],
            }
            for c in falsified
        ],
        "critical_fails": [
            {
                "id": c["id"],
                "type": c["type"],
                "text": c["text"],
                "verdict": c["verdict"],
                "reason": c.get("verdict_reason", ""),
            }
            for c in critical_fails
        ],
        "needs_remediation": needs_remediation,
        "remediation_hints": [],
    }

    # 生成修复提示
    if needs_remediation:
        for c in falsified:
            report["remediation_hints"].append({
                "claim_id": c["id"],
                "original_text": c["text"],
                "search_query": f"真实 {c['text']} 数据 来源",
                "instruction": (
                    f"声明「{c['text']}」被标记为虚假。"
                    f"请 WebSearch 搜索真实替代数据，然后基于真实数据重写包含此声明的脚本段落。"
                ),
            })

    return report


# =========================================================================
# 修复闭环（在 Claude 会话中执行）
# =========================================================================

def build_remediation_prompt(report: dict) -> str:
    """构建修复提示词 — 供 Claude 在重生成时使用

    将此 prompt 作为 system instruction 的一部分传给 split-engine，
    确保重生成的脚本只使用已验证的事实。
    """
    if not report.get("needs_remediation"):
        return ""

    falsified = report.get("falsified_claims", [])
    critical = report.get("critical_fails", [])

    lines = [
        "## [FAIL] 事实验证失败 — 以下声明不可使用",
        "",
        "以下声明经 WebSearch 验证为虚假或无法验证。**严禁在重写时使用这些内容。**",
        "",
    ]

    if falsified:
        lines.append("### 被证伪的声明（FALSIFIED）")
        for c in falsified:
            lines.append(f"- ❌ [{c['type']}] {c['text']}")
            lines.append(f"  原因: {c.get('reason', '与信源矛盾')}")
            lines.append(f"  上下文: {c.get('context', '')}")
            lines.append("")
        lines.append("")

    if critical:
        lines.append("### 高风险未验证声明（UNVERIFIABLE·高风险）")
        lines.append("以下声明未能验证，如需使用必须标注'据公开资料'或降低确定性：")
        for c in critical:
            lines.append(f"- ⚠️ [{c['type']}] {c['text']}")
            lines.append(f"  原因: {c.get('reason', '信源不足')}")
            lines.append("")
        lines.append("")

    lines.extend([
        "### [OK] 重写规则",
        "1. 仅使用以下已验证事实替换被证伪的声明",
        "2. 如果找不到替代事实 → 删除该段落，不编造",
        "3. 化名人物可保留，但其背景事件必须与已验证的行业常态一致",
        "4. 数据必须可追溯到具体来源（URL 或官方发布）",
        "5. 政策/法律名称必须一字不差",
        "",
        "### 已验证的事实（替换用）",
        "[Claude 在此填入 WebSearch 找到的真实事实]",
    ])

    return "\n".join(lines)


# =========================================================================
# 修复结果合并
# =========================================================================

def merge_retry_report(attempts: list[dict]) -> dict:
    """合并多次修复尝试的报告

    Args:
        attempts: 每次尝试的 report dict 列表

    Returns:
        合并后的最终报告
    """
    if not attempts:
        return {"overall": "ERROR", "error": "无验证尝试"}

    final = attempts[-1].copy()
    final["retries"] = len(attempts) - 1
    final["attempts"] = []
    final["retry_history"] = []

    for i, report in enumerate(attempts):
        final["retry_history"].append({
            "attempt": i + 1,
            "overall": report["overall"],
            "falsified_count": report["summary"]["falsified"],
            "unverifiable_count": report["summary"]["unverifiable"],
        })

    if final["overall"] == "PASS":
        final["status"] = "PASSED" if len(attempts) == 1 else f"PASSED_AFTER_{len(attempts)-1}_RETRIES"
    else:
        final["status"] = f"FAILED_AFTER_{len(attempts)}_ATTEMPTS"
        final["recommendation"] = (
            f"选题事实无法验证，建议放弃或降级为观点类内容（明确标注'个人观点，非事实陈述'）。"
        )

    return final


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="L4 脚本验证主编排器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 从脚本提取声明 + 生成搜索计划
  python verifier.py extract script.md -o plan.json

  # 根据搜索结果判定
  python verifier.py judge plan.json --results search_results.json -o report.json

  # 一条命令验证（需要已有 results.json）
  python verifier.py verify script.md --results results.json
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # extract
    ext = sub.add_parser("extract", help="提取声明 + 生成搜索计划")
    ext.add_argument("script", help="脚本 markdown 文件")
    ext.add_argument("-o", "--output", help="输出 JSON 路径", default=None)

    # judge
    judge = sub.add_parser("judge", help="根据搜索结果判定声明真实性")
    judge.add_argument("plan_json", help="extract 输出的计划 JSON")
    judge.add_argument("--results", required=True, help="搜索结果 JSON {claim_id: summary}")
    judge.add_argument("-o", "--output", help="输出报告路径", default=None)
    judge.add_argument("--strictness", default="standard",
                       choices=["strict", "standard", "lenient"])

    # verify (快捷：extract + judge 合一，需已有 results)
    verify = sub.add_parser("verify", help="快捷验证（需已有 results.json）")
    verify.add_argument("script", help="脚本 markdown 文件")
    verify.add_argument("--results", required=True, help="搜索结果 JSON")
    verify.add_argument("-o", "--output", help="输出报告路径", default=None)
    verify.add_argument("--strictness", default="standard",
                        choices=["strict", "standard", "lenient"])

    # remediation_prompt
    rem = sub.add_parser("remediation-prompt", help="从失败报告生成修复提示词")
    rem.add_argument("report_json", help="judge/verify 输出的报告 JSON")

    # retry
    retry = sub.add_parser("retry", help="从失败报告生成修复任务，供 Claude 执行修复闭环")
    retry.add_argument("report_json", help="judge/verify 输出的 FAIL 报告 JSON")
    retry.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                       help=f"最大重试次数 (默认 {MAX_RETRIES})")

    args = parser.parse_args()

    if args.command == "extract":
        result = extract_and_plan(args.script)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            _atomic_write_text(args.output, output)
            print(f"[OK] 计划已写入 {args.output}")
            print(f"   声明数: {result['extraction_summary']['total']}")
            print(f"   搜索查询: {result['search_plan']['total_queries']}")
        else:
            print(output)

    elif args.command == "judge":
        with open(args.plan_json, 'r', encoding='utf-8') as f:
            plan = json.load(f)

        with open(args.results, 'r', encoding='utf-8') as f:
            search_results = json.load(f)

        claims = plan.get("claims", plan)
        report = judge_and_report(
            claims, search_results,
            script_path=plan.get("script"),
            strictness=args.strictness,
        )
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            _atomic_write_text(args.output, output)
            status_map = {"PASS": "[OK] PASS", "PASS_WITH_CAVEATS": "[WARN] PASS_WITH_CAVEATS", "FAIL": "[FAIL] FAIL"}
            status = status_map.get(report["overall"], f"[?] {report['overall']}")
            print(f"{status}  验证: {report['summary']['verified']} / "
                  f"未验证: {report['summary']['unverifiable']} / "
                  f"虚假: {report['summary']['falsified']}")
            if report["needs_remediation"]:
                print(f"   需要修复 {len(report['falsified_claims'])} 条虚假声明")
            if report["overall"] == "PASS_WITH_CAVEATS":
                print(f"   {report['summary']['unverifiable']} 条声明无法验证，需人工确认")
        else:
            print(output)

        if report["overall"] == "FAIL":
            sys.exit(1)
        # PASS_WITH_CAVEATS 不阻塞，但用非零退出码提示注意
        if report["overall"] == "PASS_WITH_CAVEATS":
            sys.exit(2)

    elif args.command == "verify":
        # 快捷模式：一步完成 extract + plan + judge
        with open(args.results, 'r', encoding='utf-8') as f:
            search_results = json.load(f)

        plan = extract_and_plan(args.script)
        claims = plan["claims"]
        report = judge_and_report(
            claims, search_results,
            script_path=args.script,
            strictness=args.strictness,
        )

        # 把搜索计划也写入报告
        report["search_plan"] = plan["search_plan"]

        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            _atomic_write_text(args.output, output)
            status_map = {"PASS": "[OK] PASS", "PASS_WITH_CAVEATS": "[WARN] PASS_WITH_CAVEATS", "FAIL": "[FAIL] FAIL"}
            status = status_map.get(report["overall"], f"[?] {report['overall']}")
            print(f"{status} | 总数:{report['summary']['total']} "
                  f"通过:{report['summary']['verified']} "
                  f"未验证:{report['summary']['unverifiable']} "
                  f"虚假:{report['summary']['falsified']}")
        else:
            print(output)

    elif args.command == "remediation-prompt":
        with open(args.report_json, 'r', encoding='utf-8') as f:
            report = json.load(f)

        prompt = build_remediation_prompt(report)
        print(prompt)

    elif args.command == "retry":
        with open(args.report_json, 'r', encoding='utf-8') as f:
            report = json.load(f)

        max_retries = args.max_retries

        # AHV-008/AHV-009：维护尝试历史，自增计数器并写回报告文件，
        # 达上限时用 merge_retry_report 合并所有尝试产出最终报告。
        history = report.get("_retry_history", [])
        # 把当前报告作为一次尝试记入历史
        history.append({
            "attempt": len(history) + 1,
            "overall": report.get("overall"),
            "falsified_count": report.get("summary", {}).get("falsified", 0),
            "unverifiable_count": report.get("summary", {}).get("unverifiable", 0),
        })
        retries_so_far = len(history) - 1

        if retries_so_far >= max_retries:
            # 合并所有尝试，写回最终报告
            merged = merge_retry_report([report])  # 单次合并以补全 retry_history/status
            merged["retries"] = retries_so_far
            merged["_retry_history"] = history
            _atomic_write_text(
                args.report_json,
                json.dumps(merged, ensure_ascii=False, indent=2))
            print(f"[STOP] 已达最大重试次数 ({max_retries})")
            print(f"  建议: 放弃该选题或降级为观点类内容")
            print(f"  最终报告已写回 {args.report_json}（status={merged.get('status')})")
            sys.exit(1)

        # 自增计数器并写回，使循环调用能正确推进
        report["retries"] = retries_so_far + 1
        report["_retry_history"] = history
        _atomic_write_text(
            args.report_json,
            json.dumps(report, ensure_ascii=False, indent=2))

        print(f"[RETRY {retries_so_far + 1}/{max_retries}] 修复任务已生成")
        print(f"  FALSIFIED: {len(report.get('falsified_claims', []))} 条")
        print(f"  CRITICAL:  {len(report.get('critical_fails', []))} 条")
        print()
        print("=== Claude 修复指令 ===")
        print("1. 逐条 WebSearch FALSIFIED 声明 → 找到真实替代数据")
        print("2. 基于搜索结果修正原文中的虚假声明")
        print("3. 重新运行: python verifier.py extract <script> -o plan.json")
        print("4. 重新运行: python verifier.py judge plan.json --results results.json -o report.json")
        print("5. 再次运行: python verifier.py retry report.json   (计数器已自增)")
        print()
        prompt = build_remediation_prompt(report)
        if prompt:
            print("=== 修复约束（注入到下轮生成的 system prompt）===")
            print(prompt)
        sys.exit(0)


if __name__ == "__main__":
    main()
