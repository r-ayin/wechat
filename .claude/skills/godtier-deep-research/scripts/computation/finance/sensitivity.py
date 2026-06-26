#!/usr/bin/env python3
"""敏感性分析 - 一次一变量(One-At-a-Time)扰动法

对每个输入变量在基准值上下扰动 ±delta，用线性加权模型计算输出变化，
按影响幅度（swing）排序，识别对结果影响最大的变量。

用法:
  python sensitivity.py \
      --base '{"revenue":1000,"cost":600,"tax_rate":0.25}' \
      --model '{"revenue":1.0,"cost":-1.0,"tax_rate":-1000.0}' \
      --delta 0.1

说明:
  --base   各变量基准值 (JSON)
  --model  各变量对输出的权重 (JSON)，输出 = Σ weight_i × value_i
  --delta  扰动比例 (默认 0.1 = ±10%)
"""
import json, argparse, sys
from datetime import datetime


def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "sensitivity", "input": inputs, "timestamp": datetime.utcnow().isoformat()}}


def main():
    p = argparse.ArgumentParser(description="一次性单变量敏感性分析")
    p.add_argument("--base", required=True, help="各变量基准值 JSON，如 {\"x\":100}")
    p.add_argument("--model", required=True, help="各变量权重 JSON，输出=Σweight×value")
    p.add_argument("--delta", type=float, default=0.1, help="扰动比例 (默认 0.1=±10%)")
    args = p.parse_args()

    try:
        base = json.loads(args.base)
        model = json.loads(args.model)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"JSON 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if set(base.keys()) != set(model.keys()):
        print(json.dumps({"error": "base 与 model 的变量集合不一致"}, ensure_ascii=False))
        sys.exit(1)

    def output(values):
        return sum(model[k] * values[k] for k in values)

    base_output = output(base)

    rows = []
    for var in base:
        low_val = {k: (v * (1 - args.delta) if k == var else v) for k, v in base.items()}
        high_val = {k: (v * (1 + args.delta) if k == var else v) for k, v in base.items()}
        low_out = output(low_val)
        high_out = output(high_val)
        swing = high_out - low_out
        rows.append({
            "variable": var,
            "base_value": base[var],
            "low_output": round(low_out, 4),
            "high_output": round(high_out, 4),
            "swing": round(swing, 4),
            "abs_swing": round(abs(swing), 4),
            "sensitivity_pct": round(abs(swing) / abs(base_output) * 100, 2) if base_output else None,
        })

    # 按绝对影响排序
    rows.sort(key=lambda r: r["abs_swing"], reverse=True)

    result = {
        "base_output": round(base_output, 4),
        "delta": args.delta,
        "ranked_sensitivity": rows,
        "most_influential": rows[0]["variable"] if rows else None,
    }
    print(json.dumps(audit(result, n_vars=len(base), delta=args.delta), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
