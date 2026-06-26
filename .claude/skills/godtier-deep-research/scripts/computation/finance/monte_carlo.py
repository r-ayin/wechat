#!/usr/bin/env python3
"""蒙特卡洛模拟 - 简化版"""
import json, argparse, random, statistics, math
from datetime import datetime

def audit(result, **inputs):
    return {"result": result, "audit": {"operation": "monte_carlo", "timestamp": datetime.utcnow().isoformat()}}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base_value", type=float, required=True)
    p.add_argument("--volatility", type=float, required=True, help="波动率(如0.2=20%%))")
    p.add_argument("--drift", type=float, default=0.0, help="漂移率")
    p.add_argument("--simulations", type=int, default=10000)
    p.add_argument("--periods", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    random.seed(args.seed)
    results = []
    for _ in range(args.simulations):
        value = args.base_value
        for _ in range(args.periods):
            # MIN-01：改用几何布朗运动(GBM)对数正态模型，保证价格恒正。
            # 旧算术收益 value *= (1+shock) 在高波动/多期下会产生负资产价。
            shock = math.exp(
                (args.drift - 0.5 * args.volatility ** 2)
                + args.volatility * random.gauss(0, 1)
            )
            value *= shock
        results.append(value)

    results.sort()
    result = {
        "mean": round(statistics.mean(results), 2),
        "median": round(statistics.median(results), 2),
        "stdev": round(statistics.stdev(results), 2),
        "p5": round(results[int(0.05 * len(results))], 2),
        "p25": round(results[int(0.25 * len(results))], 2),
        "p75": round(results[int(0.75 * len(results))], 2),
        "p95": round(results[int(0.95 * len(results))], 2),
        "min": round(min(results), 2),
        "max": round(max(results), 2),
        "simulations": args.simulations,
    }
    print(json.dumps(audit(result, base=args.base_value, vol=args.volatility, drift=args.drift), ensure_ascii=False))

if __name__ == "__main__":
    main()
