#!/usr/bin/env python3
"""简单线性回归 - y = mx + b"""
import json, argparse, statistics
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "regression", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--x", nargs="+", type=float, required=True)
    p.add_argument("--y", nargs="+", type=float, required=True)
    args = p.parse_args()
    assert len(args.x) == len(args.y), "x and y must have same length"
    n = len(args.x)
    mx, my = statistics.mean(args.x), statistics.mean(args.y)
    ss_xx = sum((x-mx)**2 for x in args.x)
    ss_xy = sum((args.x[i]-mx)*(args.y[i]-my) for i in range(n))
    slope = ss_xy / ss_xx if ss_xx else 0
    intercept = my - slope * mx
    # R-squared
    ss_yy = sum((y-my)**2 for y in args.y)
    r_squared = (ss_xy**2) / (ss_xx * ss_yy) if ss_xx and ss_yy else 0
    result = {"slope": round(slope, 4), "intercept": round(intercept, 4), "r_squared": round(r_squared, 4), "equation": f"y = {round(slope,4)}x + {round(intercept,4)}"}
    print(json.dumps(audit(result, n=n), ensure_ascii=False))

if __name__ == "__main__":
    main()
