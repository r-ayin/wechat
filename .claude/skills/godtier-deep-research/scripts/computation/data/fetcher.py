#!/usr/bin/env python3
"""数据获取 - 从JSON文件读取结构化数据（Agent不直接调用此脚本，由主流程使用）"""
import json, argparse, os
from datetime import datetime

def load_json(filepath):
    """加载JSON数据文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def extract_values(data, key_path):
    """从嵌套JSON中提取值，key_path如 'revenue.current' """
    keys = key_path.split('.')
    val = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        elif isinstance(val, list) and k.isdigit():
            val = val[int(k)]
        else:
            return None
    return val

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--file", required=True, help="JSON文件路径")
    p.add_argument("--key", help="提取的key路径")
    args = p.parse_args()
    data = load_json(args.file)
    if args.key:
        result = extract_values(data, args.key)
    else:
        result = data
    print(json.dumps({"result": result, "source_file": args.file}, ensure_ascii=False, indent=2))
