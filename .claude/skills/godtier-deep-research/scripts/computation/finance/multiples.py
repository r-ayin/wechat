#!/usr/bin/env python3
"""估值倍数计算"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"input": inputs, "operation": "multiples", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--op", choices=["ev_ebitda", "ev_revenue", "peg", "fair_value"], required=True)
    p.add_argument("--market_cap", type=float)
    p.add_argument("--total_debt", type=float, default=0)
    p.add_argument("--cash", type=float, default=0)
    p.add_argument("--metric", type=float, help="EBITDA/Revenue/Net Income")
    p.add_argument("--growth_rate", type=float, help="Growth rate for PEG")
    p.add_argument("--pe_ratio", type=float)
    p.add_argument("--industry_pe", type=float)
    p.add_argument("--eps", type=float)
    args = p.parse_args()

    if args.op == "ev_ebitda":
        ev = args.market_cap + args.total_debt - args.cash
        result = {"ev": ev, "ev_ebitda": round(ev / args.metric, 2) if args.metric else None}
    elif args.op == "ev_revenue":
        ev = args.market_cap + args.total_debt - args.cash
        result = {"ev": ev, "ev_revenue": round(ev / args.metric, 2) if args.metric else None}
    elif args.op == "peg":
        result = {"peg": round(args.pe_ratio / (args.growth_rate * 100), 2) if args.growth_rate else None}
    elif args.op == "fair_value":
        result = {"fair_value": round(args.industry_pe * args.eps, 2) if args.eps else None}
    print(json.dumps(audit(result, op=args.op), ensure_ascii=False))

if __name__ == "__main__":
    main()
