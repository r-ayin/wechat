#!/usr/bin/env python3
"""描述性统计 - 均值、中位数、标准差、分位数"""
import json, argparse, statistics
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "descriptive", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", nargs="+", type=float, required=True)
    p.add_argument("--op", choices=["mean", "median", "stdev", "variance", "min", "max", "sum", "count", "percentile"], required=True)
    p.add_argument("--pct", type=float)
    args = p.parse_args()
    d = args.data
    if args.op == "mean": result = statistics.mean(d)
    elif args.op == "median": result = statistics.median(d)
    elif args.op == "stdev": result = statistics.stdev(d) if len(d) > 1 else 0
    elif args.op == "variance": result = statistics.variance(d) if len(d) > 1 else 0
    elif args.op == "min": result = min(d)
    elif args.op == "max": result = max(d)
    elif args.op == "sum": result = sum(d)
    elif args.op == "count": result = len(d)
    elif args.op == "percentile":
        assert args.pct is not None, "--pct required for percentile"
        s = sorted(d)
        k = (len(s) - 1) * args.pct / 100
        f = int(k)
        result = s[f] + (k - f) * (s[f+1] - s[f]) if f + 1 < len(s) else s[f]
    print(json.dumps(audit(round(result, 4) if isinstance(result, float) else result, n=len(d), op=args.op), ensure_ascii=False))

if __name__ == "__main__":
    main()
