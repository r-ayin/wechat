#!/usr/bin/env python3
"""数据过滤 - 阈值过滤、范围过滤"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "filter", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", nargs="+", type=float, required=True)
    p.add_argument("--op", choices=["gt", "gte", "lt", "lte", "eq", "range"], required=True)
    p.add_argument("--threshold", type=float)
    p.add_argument("--low", type=float)
    p.add_argument("--high", type=float)
    args = p.parse_args()
    d = args.data
    if args.op == "gt": result = [x for x in d if x > args.threshold]
    elif args.op == "gte": result = [x for x in d if x >= args.threshold]
    elif args.op == "lt": result = [x for x in d if x < args.threshold]
    elif args.op == "lte": result = [x for x in d if x <= args.threshold]
    elif args.op == "eq": result = [x for x in d if x == args.threshold]
    elif args.op == "range": result = [x for x in d if args.low <= x <= args.high]
    print(json.dumps(audit(result, total=len(d), filtered=len(result)), ensure_ascii=False))

if __name__ == "__main__":
    main()
