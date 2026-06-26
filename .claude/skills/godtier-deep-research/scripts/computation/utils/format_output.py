#!/usr/bin/env python3
"""格式化输出 - 统一JSON输出格式"""
import json, sys
from datetime import datetime

def format_result(data, source="unknown"):
    return json.dumps({
        "source": source,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    data = json.loads(sys.stdin.read())
    print(format_result(data, sys.argv[1] if len(sys.argv) > 1 else "stdin"))
