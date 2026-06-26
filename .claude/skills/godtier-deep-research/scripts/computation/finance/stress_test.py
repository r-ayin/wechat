#!/usr/bin/env python3
"""压力测试 - 假设情景冲击"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "stress_test", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base_revenue", type=float, required=True)
    p.add_argument("--base_margin", type=float, required=True, help="利润率(如0.15=15%%))")
    p.add_argument("--revenue_shock", type=float, required=True, help="收入冲击(如-0.20=-20%%))")
    p.add_argument("--margin_shock", type=float, default=0, help="利润率冲击")
    p.add_argument("--fixed_costs", type=float, default=0)
    args = p.parse_args()

    stressed_revenue = args.base_revenue * (1 + args.revenue_shock)
    stressed_margin = args.base_margin + args.margin_shock
    stressed_profit = stressed_revenue * stressed_margin - args.fixed_costs
    base_profit = args.base_revenue * args.base_margin - args.fixed_costs
    profit_impact = (stressed_profit - base_profit) / abs(base_profit) * 100 if base_profit else 0

    result = {
        "base_revenue": args.base_revenue,
        "stressed_revenue": round(stressed_revenue, 2),
        "base_profit": round(base_profit, 2),
        "stressed_profit": round(stressed_profit, 2),
        "profit_impact_pct": round(profit_impact, 2),
        "revenue_shock": args.revenue_shock,
        "margin_shock": args.margin_shock,
    }
    print(json.dumps(audit(result), ensure_ascii=False))

if __name__ == "__main__":
    main()
