#!/usr/bin/env python3
"""百分比运算 - 增长率、变化率、占比"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"input": inputs, "operation": "percentage", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--op", required=True, choices=["growth_rate", "change_rate", "share", "markup", "margin"])
    p.add_argument("--current", type=float, required=True)
    p.add_argument("--base", type=float, required=True)
    p.add_argument("--precision", type=int, default=4)
    args = p.parse_args()
    c, b = args.current, args.base
    if args.op == "growth_rate":
        assert b != 0, "base cannot be 0"
        result = (c - b) / abs(b) * 100
    elif args.op == "change_rate":
        assert b != 0, "base cannot be 0"
        result = (c - b) / b * 100
    elif args.op == "share":
        assert b != 0, "base cannot be 0"
        result = c / b * 100
    elif args.op == "markup":
        assert b != 0, "base cannot be 0"
        result = (c - b) / b * 100
    elif args.op == "margin":
        assert c != 0, "revenue cannot be 0"
        result = b / c * 100
    print(json.dumps(audit(round(result, args.precision), current=c, base=b, op=args.op), ensure_ascii=False))

if __name__ == "__main__":
    main()
