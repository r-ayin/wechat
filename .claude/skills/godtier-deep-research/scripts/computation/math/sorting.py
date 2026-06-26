#!/usr/bin/env python3
"""排序操作 - 确保排序结果可靠"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"input_count": len(inputs.get("data", [])), "operation": "sorting", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", nargs="+", type=float, required=True)
    p.add_argument("--order", choices=["asc", "desc"], default="desc")
    p.add_argument("--top", type=int)
    args = p.parse_args()
    data = sorted(args.data, reverse=(args.order == "desc"))
    if args.top:
        data = data[:args.top]
    print(json.dumps(audit(data, data=args.data, order=args.order, top=args.top), ensure_ascii=False))

if __name__ == "__main__":
    main()
