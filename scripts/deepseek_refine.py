#!/usr/bin/env python3
"""deepseek_refine.py — 用 DeepSeek 把 Bing 摘要炼成干净热点标题 + 事实摘要

背景：hot-scanner.py 的 _extract_title 直接把搜索查询词当标题
（如 "打工人 反对 热搜"），日报读起来像关键词堆。Bing SERP 抓回来的
摘要里其实有真实标题/事件/数字，但被拼成一长串塞进 summary 字段
喂给 consume 评分用，渲染时没体现。

本脚本在 consume 之后、daily_report 渲染之前插一道精炼：
  - 输入：scan-daily JSON（list[item]，item.title 现是查询词）
         + Bing 原始 summary JSON（{query: raw_summary}）
  - 对每条 item，把 query + raw_summary 喂给 DeepSeek，
    让它输出 {headline, digest}：
      * headline：10-25 字真实热点标题（含具体事件/人物/数字，非查询词拼接）
      * digest：60-120 字事实摘要（含人物/机构/数字/时间，非空泛评论）
  - 原查询词保留到 item.query（溯源），item.title 替换为 headline，
    新增 item.digest 字段（daily_report 渲染为标题下加粗摘要）。
  - 单条失败（API/解析/超时）跳过，保留原标题；零阻塞整条管线。

纯标准库（urllib + concurrent.futures），零第三方依赖。
DeepSeek 走 OpenAI 兼容 /chat/completions，DEEPSEEK_API_KEY 缺失则整体跳过。

CLI:
  python scripts/deepseek_refine.py \
      --scan output/state/scan-daily-YYYY-MM-DD.json \
      [--raw /tmp/wechat-scan-YYYY-MM-DD.json] \
      [--model deepseek-v4-flash] [--concurrency 4] [--max-items 0]

退出码：0（全部失败也退 0，让 cron 继续渲染）。
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_DEFAULT_MODEL = "deepseek-v4-flash"
_DEFAULT_BASE = "https://api.deepseek.com"
_DEFAULT_CONCURRENCY = 3
_MAX_TOKENS = 3000
_TIMEOUT = 90

_SYSTEM = (
    "你是一名资深中文热点选题编辑。给你一个搜索查询词和搜索引擎抓回的网页摘"
    "要片段，你要从中提炼出今天真正值得做选题报道的热点。要求："
    "1) headline 必须是真实事件标题，含具体人物/机构/数字/政策名/时间之一，"
    "10-25 字，不要直接复制查询词，不要『某某事件引发热议』这类套话；"
    "2) digest 60-120 字，必须含摘要里出现过的具体事实（人物/机构/数字/时间），"
    "不要空泛评论和价值判断；"
    "3) 如果摘要里没有明确的新闻事件（只是泛搜索/百科/无具体事件），"
    "也要从摘要里挑出最具体的一条信息作 headline（如某机构发布的报告/数据/政策/趋势判断），"
    "digest 写清这条信息的来源与内容；摘要实在无具体内容时 headline 填『(无明确热点)』、"
    "digest 填空字符串。"
    "严格只输出一个 JSON 对象，键为 headline 和 digest，不要 markdown 代码块，"
    "不要在 JSON 之外加任何解释文字。"
)


def _build_user(query: str, raw_summary: str, pillar: str) -> str:
    return (
        f"支柱: {pillar}\n"
        f"查询词: {query}\n"
        f"搜索摘要:\n{raw_summary[:1500]}\n\n"
        f"输出 JSON: {{\"headline\": \"...\", \"digest\": \"...\"}}"
    )


def _call_deepseek(api_key: str, base_url: str, model: str,
                   query: str, raw_summary: str, pillar: str) -> dict | None:
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_user(query, raw_summary, pillar)},
        ],
        "max_tokens": _MAX_TOKENS,
        "temperature": 0.3,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, json.JSONDecodeError) as e:
        print(f"  ⚠️ DeepSeek 调用失败 [{query!r}]: {e}", file=sys.stderr)
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ DeepSeek 异常 [{query!r}]: {e}", file=sys.stderr)
        return None

    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        print(f"  ⚠️ DeepSeek 响应结构异常 [{query!r}]", file=sys.stderr)
        return None
    return _parse_json(content, query)


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _parse_json(content: str, query: str) -> dict | None:
    content = content.strip()
    # 优先剥 markdown 代码块
    m = _JSON_BLOCK_RE.search(content)
    raw = m.group(1) if m else content
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # 兜底：第一个 { 到最后一个 } 之间切出来再试
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(content[start:end + 1])
            except json.JSONDecodeError as e:
                print(f"  ⚠️ JSON 解析失败 [{query!r}]: {e}", file=sys.stderr)
                return None
        else:
            print(f"  ⚠️ 响应无 JSON [{query!r}]: {content[:80]}", file=sys.stderr)
            return None
    headline = (obj.get("headline") or "").strip()
    digest = (obj.get("digest") or "").strip()
    if not headline:
        return None
    # DeepSeek 可能用半角/全角括号返回无热点标记，统一过滤
    if headline in ("(无明确热点)", "（无明确热点）", "(无明确事件)",
                    "（无明确事件）"):
        return None
    return {"headline": headline[:60], "digest": digest[:300]}


def refine_one(item: dict, raw_summary: str | None, ctx: dict) -> dict | None:
    query = (item.get("query") or item.get("title") or "").strip()
    pillar = item.get("pillar") or "未分类"
    if not query or not raw_summary or len(raw_summary.strip()) < 30:
        return None
    return _call_deepseek(
        ctx["api_key"], ctx["base_url"], ctx["model"],
        query, raw_summary, pillar)


def run(args) -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        print("  ⏭️  DEEPSEEK_API_KEY 未设置，跳过精炼（保留原 title）",
              file=sys.stderr)
        return 0

    scan_path = Path(args.scan)
    if not scan_path.is_file():
        print(f"  ⏭️  scan 文件不存在: {scan_path}", file=sys.stderr)
        return 0
    try:
        items = json.loads(scan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"  ❌ scan JSON 解析失败: {e}", file=sys.stderr)
        return 0
    if not isinstance(items, list) or not items:
        print("  ⏭️  scan 为空，跳过精炼", file=sys.stderr)
        return 0

    raw_map: dict[str, str] = {}
    if args.raw and Path(args.raw).is_file():
        try:
            raw_map = json.loads(Path(args.raw).read_text(encoding="utf-8"))
            if not isinstance(raw_map, dict):
                raw_map = {}
        except json.JSONDecodeError:
            raw_map = {}

    ctx = {
        "api_key": api_key,
        "base_url": args.base_url,
        "model": args.model,
    }

    work = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if args.max_items > 0 and len(work) >= args.max_items:
            break
        q = (it.get("query") or it.get("title") or "").strip()
        raw = raw_map.get(q) or raw_map.get(it.get("title", "")) or ""
        work.append((it, q, raw))

    print(f"  🔄 DeepSeek 精炼: {len(work)} 条 (model={args.model}, "
          f"concurrency={args.concurrency})", file=sys.stderr)

    refined = 0
    skipped_no_raw = 0
    failed = 0
    # Collect results separately to avoid concurrent mutation of `items`
    # dicts inside the as_completed loop (race window when threads resolve
    # out-of-order and caller reads items mid-write).
    updates: list[tuple[dict, str, dict]] = []
    with cf.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {
            pool.submit(refine_one, it, raw, ctx): (it, q)
            for it, q, raw in work
        }
        for fut in cf.as_completed(futures):
            it, q = futures[fut]
            try:
                res = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  ⚠️ 线程异常 [{q!r}]: {e}", file=sys.stderr)
                failed += 1
                continue
            if res is None:
                if not raw_map.get(q):
                    skipped_no_raw += 1
                else:
                    failed += 1
                continue
            updates.append((it, q, res))
            refined += 1

    # Single-threaded writeback — safe from races and easy to audit.
    for it, q, res in updates:
        it["query"] = q
        it["title"] = res["headline"]
        it["digest"] = res["digest"]

    scan_path.write_text(
        json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"  ✅ 精炼完成: {refined} 条替换标题+摘要, "
        f"{skipped_no_raw} 条无 raw 跳过, {failed} 条失败保留原标题 → {scan_path}",
        file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="DeepSeek 精炼热点标题+摘要")
    p.add_argument("--scan", required=True, help="scan-daily JSON 路径（in-place 修改）")
    p.add_argument("--raw", default="", help="Bing 原始 summary JSON 路径")
    p.add_argument("--base-url", default=_DEFAULT_BASE)
    p.add_argument("--model", default=_DEFAULT_MODEL)
    p.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    p.add_argument("--max-items", type=int, default=0, help="0=全部")
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
