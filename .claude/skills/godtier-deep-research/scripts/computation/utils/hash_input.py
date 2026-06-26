#!/usr/bin/env python3
"""输入哈希 - 为审计日志生成输入指纹"""
import json, hashlib, sys
from datetime import datetime

def main():
    data = sys.stdin.read()
    h = hashlib.sha256(data.encode()).hexdigest()[:16]
    print(json.dumps({"input_hash": h, "input_length": len(data), "timestamp": datetime.utcnow().isoformat()}))

if __name__ == "__main__":
    main()
