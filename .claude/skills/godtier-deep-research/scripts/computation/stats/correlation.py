#!/usr/bin/env python3
"""相关性分析 - Pearson/Spearman"""
import json, argparse, statistics
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "correlation", "timestamp": datetime.utcnow().isoformat()}}

def pearson(x, y):
    n = len(x)
    mx, my = statistics.mean(x), statistics.mean(y)
    cov = sum((x[i]-mx)*(y[i]-my) for i in range(n)) / n
    sx = statistics.stdev(x) if len(x) > 1 else 1
    sy = statistics.stdev(y) if len(y) > 1 else 1
    return cov / (sx * sy) if sx and sy else 0

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--x", nargs="+", type=float, required=True)
    p.add_argument("--y", nargs="+", type=float, required=True)
    p.add_argument("--method", choices=["pearson"], default="pearson")
    args = p.parse_args()
    assert len(args.x) == len(args.y), "x and y must have same length"
    result = pearson(args.x, args.y)
    print(json.dumps(audit(round(result, 4), n=len(args.x), method=args.method), ensure_ascii=False))

if __name__ == "__main__":
    main()
