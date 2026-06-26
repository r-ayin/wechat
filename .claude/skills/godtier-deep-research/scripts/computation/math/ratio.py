#!/usr/bin/env python3
"""比率计算 - P/E, P/B, ROE, ROIC 等"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"input": inputs, "operation": "ratio", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--op", required=True, choices=["pe", "pb", "ps", "roe", "roic", "current_ratio", "debt_equity", "gross_margin", "operating_margin", "net_margin"])
    p.add_argument("--numerator", type=float, required=True)
    p.add_argument("--denominator", type=float, required=True)
    p.add_argument("--precision", type=int, default=4)
    args = p.parse_args()
    n, d = args.numerator, args.denominator
    assert d != 0, "denominator cannot be 0"
    result = n / d
    print(json.dumps(audit(round(result, args.precision), numerator=n, denominator=d, op=args.op), ensure_ascii=False))

if __name__ == "__main__":
    main()
