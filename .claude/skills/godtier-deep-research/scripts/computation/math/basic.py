#!/usr/bin/env python3
"""基础数学运算 - 加减乘除、幂、根"""
import json
import sys
import argparse
import math
from datetime import datetime


def audit(result, **inputs):
    return {
        "result": result,
        "audit": {
            "input": inputs,
            "operation": "basic",
            "timestamp": datetime.utcnow().isoformat(),
        }
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--op", required=True, choices=["add", "sub", "mul", "div", "pow", "sqrt", "abs", "round"])
    parser.add_argument("--a", type=float, required=True)
    parser.add_argument("--b", type=float)
    parser.add_argument("--precision", type=int, default=4)
    args = parser.parse_args()

    a, b = args.a, args.b
    if args.op == "add":
        assert b is not None, "b required for add"
        result = a + b
    elif args.op == "sub":
        assert b is not None, "b required for sub"
        result = a - b
    elif args.op == "mul":
        assert b is not None, "b required for mul"
        result = a * b
    elif args.op == "div":
        assert b is not None and b != 0, "b required and non-zero for div"
        result = a / b
    elif args.op == "pow":
        assert b is not None, "b required for pow"
        result = a ** b
    elif args.op == "sqrt":
        result = math.sqrt(a)
    elif args.op == "abs":
        result = abs(a)
    elif args.op == "round":
        result = round(a, int(b or 0))

    result = round(result, args.precision)
    print(json.dumps(audit(result, a=a, b=b, op=args.op), ensure_ascii=False))


if __name__ == "__main__":
    main()
