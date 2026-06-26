#!/usr/bin/env python3
"""时间序列 - 移动平均、趋势"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "timeseries", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", nargs="+", type=float, required=True)
    p.add_argument("--op", choices=["sma", "ema", "yoy_change", "cagr"], required=True)
    p.add_argument("--period", type=int, default=4)
    args = p.parse_args()
    d = args.data
    if args.op == "sma":
        w = args.period
        result = [round(sum(d[max(0,i-w+1):i+1])/min(w, i+1), 4) for i in range(len(d))]
    elif args.op == "ema":
        k = 2 / (args.period + 1)
        result = [d[0]]
        for i in range(1, len(d)):
            result.append(round(d[i]*k + result[-1]*(1-k), 4))
    elif args.op == "yoy_change":
        result = [round((d[i]-d[i-args.period])/abs(d[i-args.period])*100, 4) if i >= args.period and d[i-args.period] else None for i in range(len(d))]
    elif args.op == "cagr":
        if len(d) >= 2 and d[0] > 0:
            years = len(d) - 1
            result = round(((d[-1]/d[0])**(1/years) - 1) * 100, 4)
        else:
            result = None
    print(json.dumps(audit(result, n=len(d), op=args.op, period=args.period), ensure_ascii=False))

if __name__ == "__main__":
    main()
