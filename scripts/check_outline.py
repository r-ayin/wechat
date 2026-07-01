#!/usr/bin/env python3
"""Check outline.json structure for Phase 3 writing pipeline.

Usage: check_outline.py <outline_json_path> <min_bytes>

Exit codes:
  0 - outline valid (sections >= 5, total word_budget >= min_bytes, all sections have thesis)
  1 - validation failed or runtime error (message on stderr)

Extracted from scripts/steps.py inline `python -c` to allow:
  - unit testing without shell escaping
  - lint/type-check coverage
  - argv-based parameter passing instead of string interpolation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def validate_outline(outline_path: str, min_bytes: int) -> None:
    path = Path(outline_path)
    if not path.exists():
        raise SystemExit(f"ERROR: outline file not found: {outline_path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"ERROR: invalid JSON in {outline_path}: {e}")

    if not isinstance(data, list):
        raise SystemExit(f"ERROR: outline must be a list, got {type(data).__name__}")

    section_count = len(data)
    if section_count < 5:
        raise SystemExit(f"FAIL: 节数={section_count} < 5")

    total_budget = sum(s.get("word_budget", 0) for s in data if isinstance(s, dict))
    if total_budget < min_bytes:
        raise SystemExit(
            f"FAIL: 总字数预算={total_budget} < min_bytes={min_bytes}"
        )

    missing_thesis = [
        i for i, s in enumerate(data)
        if not isinstance(s, dict) or not s.get("thesis")
    ]
    if missing_thesis:
        raise SystemExit(f"FAIL: 节缺论点 indices={missing_thesis}")

    print(f"outline OK {section_count} 节 (budget={total_budget})")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(f"Usage: {sys.argv[0]} <outline_json_path> <min_bytes>")

    outline_path = sys.argv[1]
    try:
        min_bytes = int(sys.argv[2])
    except ValueError:
        raise SystemExit(f"ERROR: min_bytes must be int, got {sys.argv[2]!r}")

    validate_outline(outline_path, min_bytes)


if __name__ == "__main__":
    main()
