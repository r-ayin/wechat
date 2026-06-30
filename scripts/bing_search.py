#!/usr/bin/env python3
"""bing_search.py — Bing 中国 SERP 抓取取数器

复用 topic-pool/hot-scanner.py 的 build_search_queries() 拿查询列表，对每条查询
抓 cn.bing.com 搜索结果页，解析 b_algo 块的标题+摘要，拼成 {query: summary} JSON
—— 正好喂 `hot-scanner.py consume`。

为何不用 Brave：中国阿里云 ECS 上 api.search.brave.com 被 DNS 投毒 + SNI 封锁，
不可达。cn.bing.com 在中国 ECS 稳定可达，无需 API key。

纯标准库（urllib + 正则），零第三方依赖。

CLI（与 brave_search.py 同接口，cron 可互换）:
  python scripts/bing_search.py [--output PATH] [--max-queries N]
                                 [--count N] [--pillar 支柱]
                                 [--mode hybrid|keyword|event] [--sleep 秒]

退出码：0（个别 query 失败跳过；完全无结果仍写空 JSON 退出 0，让 cron fallback）。
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOPIC_POOL = _ROOT / "topic-pool"
_DEFAULT_OUTPUT = "/tmp/wechat-scan-results.json"

_BING_URL = "https://cn.bing.com/search"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# b_algo 结果块
_BLOCK_RE = re.compile(r'<li class="b_algo".*?</li>', re.S)
_H2_RE = re.compile(r'<h2>(.*?)</h2>', re.S)
_P_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def _strip(text: str) -> str:
    return _html.unescape(_TAG_RE.sub("", text)).strip()


def _load_queries(pillar: str | None, mode: str) -> list[dict]:
    """从 hot-scanner.py 的 build_search_queries() 拿查询列表（按 path 加载，文件名含连字符）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hot_scanner_mod", _TOPIC_POOL / "hot-scanner.py")
    if spec is None or spec.loader is None:
        print("❌ 无法加载 topic-pool/hot-scanner.py", file=sys.stderr)
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod.build_search_queries(pillar=pillar, mode=mode)


def _bing_fetch(query: str, count: int) -> list[dict]:
    """抓 Bing SERP，返回 [{title, snippet}] 列表。"""
    params = {"q": query, "count": str(count), "setlang": "zh-Hans",
              "cc": "CN", "form": "QBLH"}
    url = f"{_BING_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", "replace")

    results = []
    for block in _BLOCK_RE.findall(raw):
        h2 = _H2_RE.search(block)
        p = _P_RE.search(block)
        title = _strip(h2.group(1)) if h2 else ""
        snippet = _strip(p.group(1)) if p else ""
        if title or snippet:
            results.append({"title": title, "snippet": snippet})
    return results


def _summarize(results: list[dict]) -> str:
    """拼成喂 consume 的 summary（≥30 字才被 consume 接收）。"""
    parts = []
    for r in results:
        t, s = r.get("title", "").strip(), r.get("snippet", "").strip()
        if t and s:
            parts.append(f"{t}。{s}")
        elif s:
            parts.append(s)
        elif t:
            parts.append(t)
    return " ".join(parts)


def _fetch_one(query: str, count: int) -> tuple[str, bool]:
    try:
        results = _bing_fetch(query, count)
        return _summarize(results), bool(results)
    except urllib.error.HTTPError as e:
        print(f"⚠️ [{e.code}] {query!r}", file=sys.stderr)
    except urllib.error.URLError as e:
        print(f"⚠️ 网络错误 {query!r}: {e.reason}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 异常 {query!r}: {e}", file=sys.stderr)
    return "", False


def run(args) -> int:
    queries = _load_queries(args.pillar, args.mode)
    if not queries:
        print("❌ 未能加载查询列表", file=sys.stderr)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text("{}", encoding="utf-8")
        return 0

    if args.max_queries and args.max_queries > 0:
        queries = queries[:args.max_queries]

    results: dict[str, str] = {}
    ok = 0
    for i, q in enumerate(queries, 1):
        qt = q.get("query", "")
        if not qt:
            continue
        summary, good = _fetch_one(qt, args.count)
        if good and len(summary.strip()) >= 30:
            results[qt] = summary
            ok += 1
        if i % 10 == 0 or i == len(queries):
            print(f"  进度 {i}/{len(queries)}（有效 {ok}）", file=sys.stderr)
        if args.sleep > 0 and i < len(queries):
            time.sleep(args.sleep)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 取数完成: {ok}/{len(queries)} 条有效 → {out} "
          f"({len(results)} 条 summary)", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Bing 中国 SERP 抓取取数器")
    p.add_argument("--output", default=_DEFAULT_OUTPUT)
    p.add_argument("--max-queries", type=int, default=0)
    p.add_argument("--count", type=int, default=8, help="每条 query 取结果数（默认 8）")
    p.add_argument("--pillar", default=None)
    p.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "event"])
    p.add_argument("--sleep", type=float, default=1.0)
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
