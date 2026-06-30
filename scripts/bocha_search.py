#!/usr/bin/env python3
"""bocha_search.py — 博查 AI 搜索取数器

调博查 AI Search API（https://api.bocha.cn/v1/ai-search），把每条 query 的
搜索结果拼成长 summary JSON 喂 hot-scanner.py consume。

为何换博查：Bing 中国 SERP 对抽象中文查询有「首字查字典」行为
（"过劳死"→"过"字字源页），DNS 投毒+SNI 封锁又用不了 Brave。博查是中国
本土 AI 搜索 API，ECS 直连可达，每条 query 返回 10 个 webpage 结果
（name+snippet+summary+url+datePublished）+ AI 综合答案，质量远好于 Bing。

输出格式与 bing_search.py 兼容：{query: summary_string}。summary 拼装：
  AI 综合答案（msg type=answer）+ top N webpage 的 name+summary。
不带 summary 的结果跳过。baike/image/video/follow_up 消息类型忽略。

CLI（与 bing_search.py 接口兼容，cron 可互换）:
  python scripts/bocha_search.py [--output PATH] [--max-queries N]
                                 [--top N] [--pillar 支柱]
                                 [--mode hybrid|keyword|event] [--sleep 秒]
                                 [--concurrency N]

退出码：0（个别 query 失败跳过；完全无结果仍写空 JSON 退出 0，让 cron fallback）。
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TOPIC_POOL = _ROOT / "topic-pool"
_DEFAULT_OUTPUT = "/tmp/wechat-scan-results.json"
_DEFAULT_BASE = "https://api.bocha.cn/v1/ai-search"
_DEFAULT_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 1500
_TIMEOUT = 30


def _load_queries(pillar: str | None, mode: str) -> list[dict]:
    """从 hot-scanner.py 的 build_search_queries() 拿查询列表。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "hot_scanner_mod", _TOPIC_POOL / "hot-scanner.py")
    if spec is None or spec.loader is None:
        print("❌ 无法加载 topic-pool/hot-scanner.py", file=sys.stderr)
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod.build_search_queries(pillar=pillar, mode=mode)


def _parse_content(content) -> dict | list | None:
    """博查 content 字段有时是 str（JSON 编码）有时直接是 obj。"""
    if isinstance(content, str):
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None
    return content


def _bocha_fetch(api_key: str, base_url: str, query: str, top: int) -> str:
    """调博查 API，返回拼好的 summary 字符串。失败返回空串。"""
    body = json.dumps({"query": query}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError) as e:
        print(f"  ⚠️ 博查调用失败 [{query!r}]: {e}", file=sys.stderr)
        return ""
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ 博查异常 [{query!r}]: {e}", file=sys.stderr)
        return ""

    if data.get("code") != 200:
        print(f"  ⚠️ 博查非 200 [{query!r}]: code={data.get('code')} "
              f"msg={data.get('message', '')[:80]}", file=sys.stderr)
        return ""

    parts: list[str] = []
    # 1. AI 综合答案（type=answer, content_type=text）
    for m in data.get("messages", []):
        if m.get("type") == "answer" and m.get("content_type") == "text":
            ans = m.get("content", "")
            if isinstance(ans, str) and ans.strip():
                # 剥 [引用:N] 标记
                import re
                ans_clean = re.sub(r"\[引用:\d+(?:,\d+)*\]", "", ans).strip()
                if ans_clean:
                    parts.append(f"【AI 综合答案】{ans_clean}")
                    break

    # 2. webpage 结果（type=source, content_type=webpage）
    webpage_count = 0
    for m in data.get("messages", []):
        if m.get("type") != "source" or m.get("content_type") != "webpage":
            continue
        cj = _parse_content(m.get("content"))
        if not isinstance(cj, dict):
            continue
        for v in cj.get("value", []):
            if webpage_count >= top:
                break
            name = (v.get("name") or "").strip()
            summary = (v.get("summary") or "").strip()
            snippet = (v.get("snippet") or "").strip()
            url = (v.get("url") or "").strip()
            date_pub = (v.get("datePublished") or "").strip()
            if not summary and not snippet:
                continue
            text = summary or snippet
            head = name or url
            date_tag = f"[{date_pub[:10]}]" if date_pub else ""
            if head:
                parts.append(f"{date_tag} {head}。{text}")
            else:
                parts.append(f"{date_tag} {text}")
            webpage_count += 1

    return " ".join(parts)


def _fetch_one(api_key: str, base_url: str, query: str, top: int) -> str:
    try:
        return _bocha_fetch(api_key, base_url, query, top)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ 异常 [{query!r}]: {e}", file=sys.stderr)
        return ""


def run(args) -> int:
    api_key = os.environ.get("BOCHA_API_KEY", "").strip()
    if not api_key:
        print("❌ BOCHA_API_KEY 未设置", file=sys.stderr)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text("{}", encoding="utf-8")
        return 0

    queries = _load_queries(args.pillar, args.mode)
    if not queries:
        print("❌ 未能加载查询列表", file=sys.stderr)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text("{}", encoding="utf-8")
        return 0

    if args.max_queries and args.max_queries > 0:
        queries = queries[:args.max_queries]

    print(f"  🔄 博查取数: {len(queries)} 条 query, top={args.top}, "
          f"concurrency={args.concurrency}", file=sys.stderr)

    results: dict[str, str] = {}
    ok = 0
    work = [(q.get("query", "")) for q in queries if q.get("query")]

    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(_fetch_one, api_key, args.base_url, q, args.top): q
            for q in work
        }
        for i, fut in enumerate(cf.as_completed(futures), 1):
            q = futures[fut]
            try:
                summary = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ 线程异常 [{q!r}]: {e}", file=sys.stderr)
                summary = ""
            if summary and len(summary.strip()) >= 30:
                results[q] = summary
                ok += 1
            if i % 10 == 0 or i == len(work):
                print(f"  进度 {i}/{len(work)}（有效 {ok}）", file=sys.stderr)
            if args.sleep > 0 and i < len(work):
                time.sleep(args.sleep)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"✅ 博查取数完成: {ok}/{len(work)} 条有效 → {out} "
          f"({len(results)} 条 summary)", file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="博查 AI 搜索取数器")
    p.add_argument("--output", default=_DEFAULT_OUTPUT)
    p.add_argument("--max-queries", type=int, default=0)
    p.add_argument("--top", type=int, default=5,
                   help="每条 query 取几个 webpage 结果（默认 5）")
    p.add_argument("--pillar", default=None)
    p.add_argument("--mode", default="hybrid",
                   choices=["hybrid", "keyword", "event"])
    p.add_argument("--sleep", type=float, default=0.3)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--base-url", default=_DEFAULT_BASE)
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
