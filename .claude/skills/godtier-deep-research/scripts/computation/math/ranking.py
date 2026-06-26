#!/usr/bin/env python3
"""排名操作"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "ranking", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--names", nargs="+", required=True)
    p.add_argument("--values", nargs="+", type=float, required=True)
    p.add_argument("--order", choices=["asc", "desc"], default="desc")
    args = p.parse_args()
    assert len(args.names) == len(args.values), "names and values must have same length"
    pairs = sorted(zip(args.names, args.values), key=lambda x: x[1], reverse=(args.order == "desc"))
    result = [{"rank": i+1, "name": n, "value": v} for i, (n, v) in enumerate(pairs)]
    print(json.dumps(audit(result, count=len(pairs)), ensure_ascii=False))

if __name__ == "__main__":
    main()
