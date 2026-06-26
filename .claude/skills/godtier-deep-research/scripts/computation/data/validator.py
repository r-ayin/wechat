#!/usr/bin/env python3
"""数据验证 - 检查数据完整性"""
import json, argparse
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "validator", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", nargs="+", type=float, required=True)
    p.add_argument("--min_val", type=float)
    p.add_argument("--max_val", type=float)
    p.add_argument("--allow_negative", action="store_true")
    args = p.parse_args()

    issues = []
    for i, v in enumerate(args.data):
        if args.min_val is not None and v < args.min_val:
            issues.append({"index": i, "value": v, "issue": f"below min {args.min_val}"})
        if args.max_val is not None and v > args.max_val:
            issues.append({"index": i, "value": v, "issue": f"above max {args.max_val}"})
        if not args.allow_negative and v < 0:
            issues.append({"index": i, "value": v, "issue": "negative value"})

    result = {"valid": len(issues) == 0, "total": len(args.data), "issues": issues, "issue_count": len(issues)}
    print(json.dumps(audit(result), ensure_ascii=False))

if __name__ == "__main__":
    main()
