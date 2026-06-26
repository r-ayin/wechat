#!/usr/bin/env python3
"""数据清洗 - 去除异常值、处理缺失"""
import json, argparse, statistics
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "cleaner", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", nargs="+", type=float, required=True)
    p.add_argument("--op", choices=["remove_outliers", "fill_missing", "winsorize"], required=True)
    p.add_argument("--std_threshold", type=float, default=2.0, help="异常值标准差阈值")
    args = p.parse_args()
    d = args.data

    if args.op == "remove_outliers":
        mean = statistics.mean(d)
        std = statistics.stdev(d) if len(d) > 1 else 0
        cleaned = [x for x in d if abs(x - mean) <= args.std_threshold * std]
        result = {"original_count": len(d), "cleaned_count": len(cleaned), "removed": len(d) - len(cleaned), "data": cleaned}
    elif args.op == "fill_missing":
        # In our case, None is represented by filtering; this is a passthrough
        result = {"data": d, "note": "no missing values in float list"}
    elif args.op == "winsorize":
        s = sorted(d)
        lo = s[int(0.05 * len(s))]
        hi = s[int(0.95 * len(s))]
        cleaned = [max(lo, min(hi, x)) for x in d]
        result = {"data": cleaned, "lower_bound": lo, "upper_bound": hi}

    print(json.dumps(audit(result, n=len(d), op=args.op), ensure_ascii=False))

if __name__ == "__main__":
    main()
