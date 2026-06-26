#!/usr/bin/env python3
"""DCF估值 - 简化版贴现现金流"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"input": inputs, "operation": "dcf", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fcf", nargs="+", type=float, required=True, help="未来N年自由现金流")
    p.add_argument("--wacc", type=float, required=True, help="WACC(如0.10=10%%))")
    p.add_argument("--terminal_growth", type=float, default=0.02, help="永续增长率")
    p.add_argument("--shares_outstanding", type=float, help="总股本")
    args = p.parse_args()

    # MIN-02：Gordon Growth 模型要求 g < r，否则数学无定义（会产生负企业价值）。
    # 旧实现不校验，terminal_growth >= wacc 时静默产出错误结果。
    if args.terminal_growth >= args.wacc:
        raise ValueError(
            f"terminal_growth ({args.terminal_growth}) 必须 < wacc ({args.wacc})；"
            f"永续增长率不可大于等于贴现率（Gordon Growth 模型无定义）"
        )

    # PV of projected FCFs
    pv_fcfs = []
    for i, fcf in enumerate(args.fcf, 1):
        pv = fcf / ((1 + args.wacc) ** i)
        pv_fcfs.append(round(pv, 2))

    # Terminal value (Gordon Growth Model)
    last_fcf = args.fcf[-1]
    terminal_value = last_fcf * (1 + args.terminal_growth) / (args.wacc - args.terminal_growth)
    pv_terminal = terminal_value / ((1 + args.wacc) ** len(args.fcf))

    enterprise_value = sum(pv_fcfs) + pv_terminal

    result = {
        "pv_fcfs": pv_fcfs,
        "total_pv_fcfs": round(sum(pv_fcfs), 2),
        "terminal_value": round(terminal_value, 2),
        "pv_terminal": round(pv_terminal, 2),
        "enterprise_value": round(enterprise_value, 2),
    }
    if args.shares_outstanding:
        result["value_per_share"] = round(enterprise_value / args.shares_outstanding, 2)

    print(json.dumps(audit(result, fcf_years=len(args.fcf), wacc=args.wacc, terminal_growth=args.terminal_growth), ensure_ascii=False))

if __name__ == "__main__":
    main()
