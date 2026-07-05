#!/usr/bin/env python3
"""审计日志 - 记录所有计算操作"""
import json, os, hashlib
from datetime import datetime, timezone

LOG_DIR = os.environ.get("AUDIT_LOG_DIR", ".")
LOG_FILE = os.path.join(LOG_DIR, "computation_audit.jsonl")

def log(operation, inputs, result, script_name=""):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "script": script_name,
        "input_hash": hashlib.sha256(str(inputs).encode()).hexdigest()[:16] if inputs else None,
        "result_summary": str(result)[:200],
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry

if __name__ == "__main__":
    import sys
    data = json.loads(sys.stdin.read())
    entry = log(data.get("operation"), data.get("inputs"), data.get("result"), data.get("script", ""))
    print(json.dumps(entry, ensure_ascii=False))
