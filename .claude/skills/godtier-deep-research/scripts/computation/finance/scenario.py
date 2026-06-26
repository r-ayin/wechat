#!/usr/bin/env python3
"""情景分析 - 乐观/基准/悲观三情景"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "scenario", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", type=float, required=True, help="基准情景值")
    p.add_argument("--optimistic", type=float, required=True, help="乐观情景值")
    p.add_argument("--pessimistic", type=float, required=True, help="悲观情景值")
    p.add_argument("--prob_optimistic", type=float, default=0.25)
    p.add_argument("--prob_base", type=float, default=0.50)
    p.add_argument("--prob_pessimistic", type=float, default=0.25)
    args = p.parse_args()

    expected = (args.optimistic * args.prob_optimistic + args.base * args.prob_base + args.pessimistic * args.prob_pessimistic)
    result = {
        "scenarios": {"optimistic": args.optimistic, "base": args.base, "pessimistic": args.pessimistic},
        "probabilities": {"optimistic": args.prob_optimistic, "base": args.prob_base, "pessimistic": args.prob_pessimistic},
        "expected_value": round(expected, 4),
        "spread": round(args.optimistic - args.pessimistic, 4),
    }
    print(json.dumps(audit(result), ensure_ascii=False))

if __name__ == "__main__":
    main()
