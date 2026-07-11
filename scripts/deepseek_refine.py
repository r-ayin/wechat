#!/usr/bin/env python3
"""deepseek_refine.py — 兼容层 (v3.0)

v3.0 变更: hot-scanner.py consume 已通过 LLM 一步到位完成标题+摘要+评分，
不再需要单独的 refine 步骤。本脚本保留为兼容层，直接跳过（no-op），
让 daily-hotspot.sh 调用链不中断。

CLI（保留以兼容现有调用）:
  python scripts/deepseek_refine.py --scan PATH  # no-op, 直接返回 0
"""

import sys
from pathlib import Path


def main() -> int:
    print("  ⏭️  v3.0: hot-scanner consume 已内置 LLM 精炼，跳过 refine 步骤",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())