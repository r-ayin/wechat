#!/usr/bin/env python3
"""交叉验证 - 比较两个数据源的结果"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "cross_check", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--value_a", type=float, required=True)
    p.add_argument("--value_b", type=float, required=True)
    p.add_argument("--tolerance_pct", type=float, default=5.0, help="允许偏差百分比")
    p.add_argument("--source_a", type=str, default="source_a")
    p.add_argument("--source_b", type=str, default="source_b")
    args = p.parse_args()

    diff = abs(args.value_a - args.value_b)
    avg = (args.value_a + args.value_b) / 2
    diff_pct = (diff / abs(avg) * 100) if avg else 0
    consistent = diff_pct <= args.tolerance_pct

    result = {
        "consistent": consistent,
        "value_a": args.value_a,
        "value_b": args.value_b,
        "diff": round(diff, 4),
        "diff_pct": round(diff_pct, 2),
        "tolerance_pct": args.tolerance_pct,
        "source_a": args.source_a,
        "source_b": args.source_b,
    }
    print(json.dumps(audit(result), ensure_ascii=False))

if __name__ == "__main__":
    main()
