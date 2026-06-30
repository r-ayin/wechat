#!/usr/bin/env python3
"""brave_search.py — Brave Web Search 取数器

复用 topic-pool/hot-scanner.py 的 build_search_queries() 拿到查询列表（五支柱
关键词 + 事件触发词 + hot-watch 专项监控），对每条查询调 Brave Web Search API，
把结果拼成 {query: summary} JSON —— 正好喂 `hot-scanner.py consume`。

纯标准库（urllib），零第三方依赖。不依赖任何 LLM 的 WebSearch 工具。

环境变量：
  BRAVE_SEARCH_KEY  — Brave API 订阅令牌（必需，从 .wechat-env source 进来）

CLI:
  python scripts/brave_search.py [--output PATH] [--max-queries N]
                                 [--count N] [--freshness pd|pw|""]
                                 [--pillar 支柱] [--mode hybrid|keyword|event]
                                 [--sleep 秒]

退出码：0（个别 query 失败跳过不阻断；完全无 key/无结果仍写空 JSON 退出 0，
以便 cron 的 fallback 用现有 scan-results 继续渲染）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOPIC_POOL = _ROOT / "topic-pool"

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_DEFAULT_OUTPUT = "/tmp/wechat-scan-results.json"


# =========================================================================
# 查询源：复用 hot-scanner.py（纯本地，零网络）
# =========================================================================

def _load_queries(pillar: str | None, mode: str) -> list[dict]:
    """从 topic-pool/hot-scanner.py 的 build_search_queries() 拿查询列表。
    文件名含连字符无法直接 import，按 path 加载。返回 [{query, pillar, ...}]。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hot_scanner_mod", _TOPIC_POOL / "hot-scanner.py")
    if spec is None or spec.loader is None:
        print("❌ 无法加载 topic-pool/hot-scanner.py", file=sys.stderr)
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod.build_search_queries(pillar=pillar, mode=mode)


# =========================================================================
# Brave API 调用
# =========================================================================

def _brave_search(query: str, key: str, count: int,
                  freshness: str | None) -> list[dict]:
    """对单条 query 调 Brave Web Search API，返回 results 列表。"""
    params = {
        "q": query,
        "count": str(count),
        "country": "CN",
        "search_lang": "zh-hans",
    }
    if freshness:
        params["freshness"] = freshness
    url = f"{_BRAVE_ENDPOINT}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            "X-Subscription-Token": key,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8"))

    # web.results 为主；news 数组（热点新闻）补充，name 字段对应标题
    results = list((data.get("web") or {}).get("results") or [])
    results.extend(data.get("news") or [])
    return results


def _summarize(results: list[dict]) -> str:
    """把 Brave 结果拼成喂 consume 的 summary 文本（≥30 字才被 consume 接收）。
    web 结果用 title，news 结果用 name，二者都用 description。"""
    parts = []
    for r in results:
        title = (r.get("title") or r.get("name") or "").strip()
        desc = (r.get("description") or "").strip()
        if title and desc:
            parts.append(f"{title}。{desc}")
        elif title:
            parts.append(title)
        elif desc:
            parts.append(desc)
    return " ".join(parts)


def _fetch_one(query: str, key: str, count: int,
               freshness: str | None) -> tuple[str, bool]:
    """取一条 query 的 summary。返回 (summary, ok)。
    freshness 命中 0 条时回退到不限时间再试一次。"""
    try:
        results = _brave_search(query, key, count, freshness)
        if not results and freshness:
            results = _brave_search(query, key, count, None)
        return _summarize(results), bool(results)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        print(f"⚠️ [{e.code}] {query!r}: {body}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"⚠️ 网络错误 {query!r}: {e.reason}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 异常 {query!r}: {e}", file=sys.stderr)
    return "", False


# =========================================================================
# 主流程
# =========================================================================

def run(args) -> int:
    key = os.environ.get("BRAVE_SEARCH_KEY", "").strip()
    if not key:
        print("❌ 未设置 BRAVE_SEARCH_KEY 环境变量（source .wechat-env ?）",
              file=sys.stderr)
        # 仍写空 JSON，让 cron fallback 继续
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text("{}", encoding="utf-8")
        return 0

    queries = _load_queries(args.pillar, args.mode)
    if not queries:
        print("❌ 未能加载查询列表", file=sys.stderr)
        Path(args.output).write_text("{}", encoding="utf-8")
        return 0

    if args.max_queries and args.max_queries > 0:
        queries = queries[:args.max_queries]

    freshness = args.freshness or None
    results: dict[str, str] = {}
    ok_count = 0
    for i, q in enumerate(queries, 1):
        query_text = q.get("query", "")
        if not query_text:
            continue
        summary, ok = _fetch_one(query_text, key, args.count, freshness)
        if ok and len(summary.strip()) >= 30:
            results[query_text] = summary
            ok_count += 1
        # 进度（每 10 条一报）
        if i % 10 == 0 or i == len(queries):
            print(f"  进度 {i}/{len(queries)}（有效 {ok_count}）", file=sys.stderr)
        if args.sleep > 0 and i < len(queries):
            time.sleep(args.sleep)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✅ 取数完成: {ok_count}/{len(queries)} 条有效 → {out_path} "
          f"({len(results)} 条 summary)", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Brave Web Search 取数器")
    p.add_argument("--output", default=_DEFAULT_OUTPUT,
                   help=f"输出 JSON 路径（默认 {_DEFAULT_OUTPUT}）")
    p.add_argument("--max-queries", type=int, default=0,
                   help="最多取 N 条 query（0=全量）")
    p.add_argument("--count", type=int, default=5,
                   help="每条 query 取多少条搜索结果（默认 5）")
    p.add_argument("--freshness", default="pd",
                   help="时间过滤: pd=过去一天 / pw=过去一周 / 空串=不限（默认 pd）")
    p.add_argument("--pillar", default=None, help="限定支柱（默认全部）")
    p.add_argument("--mode", default="hybrid",
                   choices=["hybrid", "keyword", "event"],
                   help="查询模式（默认 hybrid）")
    p.add_argument("--sleep", type=float, default=1.0,
                   help="query 间睡眠秒数（限流，默认 1.0）")
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
