#!/usr/bin/env python3
"""WACC计算 - 加权平均资本成本"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"input": inputs, "operation": "wacc", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--equity_value", type=float, required=True, help="股权市值")
    p.add_argument("--debt_value", type=float, required=True, help="债务市值")
    p.add_argument("--cost_of_equity", type=float, required=True, help="股权成本(如0.12=12%%))")
    p.add_argument("--cost_of_debt", type=float, required=True, help="债务成本(如0.05=5%%))")
    p.add_argument("--tax_rate", type=float, required=True, help="税率(如0.25=25%%))")
    p.add_argument("--precision", type=int, default=4)
    args = p.parse_args()
    v = args.equity_value + args.debt_value
    assert v > 0, "Total value must be positive"
    we = args.equity_value / v
    wd = args.debt_value / v
    wacc = we * args.cost_of_equity + wd * args.cost_of_debt * (1 - args.tax_rate)
    result = {
        "wacc": round(wacc, args.precision),
        "wacc_pct": round(wacc * 100, args.precision),
        "weight_equity": round(we, args.precision),
        "weight_debt": round(wd, args.precision),
        "total_value": v
    }
    print(json.dumps(audit(result, **vars(args)), ensure_ascii=False))

if __name__ == "__main__":
    main()
