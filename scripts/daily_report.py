#!/usr/bin/env python3
"""daily_report.py — 热点选题日报 HTML 渲染器 (v3.0)

从 scan-results JSON 渲染一份热点选题日报 HTML，落地 output/hotspot-report-{date}.html。

纯标准库，零第三方依赖。

v3.0 变更:
  - 移除 evergreen-pool.json 常青兜底 — 日报只展示当天搜索到的真实内容
  - 移除硬编码的"项目身份锚定" — 日报纯数据驱动
  - 适配 v3.0 新的四维评分字段 (relevance/depth/novelty/narrative)
  - 无数据时生成简洁占位页，不再硬编码兜底文字

CLI:
  python scripts/daily_report.py [--date YYYY-MM-DD|today] [--output PATH]
                                 [--top N] [--scan PATH]
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SCAN = _ROOT / "topic-pool" / "scan-results.json"
_DEFAULT_OUT_DIR = _ROOT / "output"

_TIER_HOT = 7.5
_TIER_MID = 6.0

# v3.0 四维字段（替代旧五维）
_DIMS = [
    ("相关度", "relevance"),
    ("深度", "depth"),
    ("新颖度", "novelty"),
    ("叙事", "narrative"),
]


def _esc(text) -> str:
    if text is None:
        return ""
    return _html.escape(str(text), quote=True)


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tier(total: float) -> tuple[str, str]:
    if total >= _TIER_HOT:
        return "hot", "🔥"
    if total >= _TIER_MID:
        return "mid", "📌"
    return "low", "🟢"


def _bar_width(score: float) -> int:
    w = int(round(_num(score) * 10))
    return max(0, min(100, w))


def _flag(value) -> str:
    return "✓" if value else "—"


def _fmt_num(score) -> str:
    n = _num(score)
    if n == int(n):
        return str(int(n))
    return f"{n:.1f}"


_CSS = """  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    margin: 0; padding: 0; background: #f5f5f7; color: #1d1d1f;
    line-height: 1.6;
  }
  .container { max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }
  header { text-align: center; margin-bottom: 32px; padding-bottom: 24px; border-bottom: 1px solid #d2d2d7; }
  header h1 { margin: 0 0 8px; font-size: 28px; }
  header .meta { color: #6e6e73; font-size: 14px; }
  header .meta b { color: #1d1d1f; }
  .card {
    display: flex; gap: 16px; background: #fff; border-radius: 12px;
    padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    border-left: 4px solid #d2d2d7;
  }
  .card.hot { border-left-color: #ff3b30; }
  .card.mid { border-left-color: #ff9500; }
  .card.low { border-left-color: #34c759; }
  .rank {
    font-size: 24px; font-weight: 700; color: #8e8e93;
    min-width: 36px; text-align: center;
  }
  .body { flex: 1; min-width: 0; }
  .header { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: 13px; }
  .tag { font-size: 16px; }
  .pillar {
    background: #f0f0f2; padding: 2px 8px; border-radius: 4px;
    color: #6e6e73; font-weight: 500;
  }
  .score { margin-left: auto; color: #6e6e73; }
  .score b { color: #1d1d1f; font-size: 15px; }
  h3 { margin: 0 0 8px; font-size: 17px; line-height: 1.4; }
  .summary { margin: 0 0 12px; font-size: 14px; color: #3a3a3c; }
  .digest { margin: 0 0 12px; padding: 10px 12px; font-size: 14px;
            color: #1d1d1f; background: #f5f5f7; border-radius: 8px;
            border-left: 3px solid #007aff; line-height: 1.55; }
  .query-prov { margin: 0 0 6px; font-size: 12px; color: #8e8e93; }
  .dims { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 8px; }
  .dim { display: flex; align-items: center; gap: 6px; font-size: 12px; min-width: 110px; }
  .dim span { color: #6e6e73; min-width: 36px; }
  .dim b { min-width: 20px; text-align: right; }
  .bar { width: 60px; height: 6px; background: #f0f0f2; border-radius: 3px; overflow: hidden; }
  .bar > div { height: 100%; background: #007aff; border-radius: 3px; }
  .flags { font-size: 12px; color: #6e6e73; margin-bottom: 6px; }
  .angle { font-size: 12px; color: #8e8e93; padding-top: 6px; border-top: 1px dashed #e5e5ea; }
  .empty { background:#fff; border-radius:12px; padding:40px; text-align:center; color:#6e6e73; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .empty p { margin: 8px 0; }
  footer { text-align: center; color: #8e8e93; font-size: 12px; margin-top: 40px; }
"""


def _render_dim(label: str, score) -> str:
    return (
        f'<div class="dim"><span>{_esc(label)}</span>'
        f'<div class="bar"><div style="width:{_bar_width(score)}%"></div></div>'
        f'<b>{_esc(_fmt_num(score))}</b></div>'
    )


def _render_card(index: int, item: dict) -> str:
    total = _num(item.get("total"))
    tier_cls, emoji = _tier(total)
    pillar = item.get("pillar") or "未分类"
    title = item.get("title") or "(无标题)"
    angle = item.get("angle") or ""
    digest = item.get("digest") or ""
    query_prov = item.get("query") or ""
    source = item.get("source") or "?"
    scanned = item.get("scanned_at") or ""

    dims = "".join(_render_dim(label, item.get(key)) for label, key in _DIMS)
    flags = (
        f"事件 {_flag(item.get('has_event'))} · "
        f"争议 {_flag(item.get('has_controversy'))} · "
        f"数据 {_flag(item.get('has_data'))}"
    )
    provenance = f"数据源 {_esc(source)}"
    if scanned:
        provenance += f" · {_esc(scanned)}"

    digest_html = (
        f'    <div class="digest">{_esc(digest)}</div>\n' if digest else "")
    query_html = (
        f'    <div class="query-prov">查询词: {_esc(query_prov)}</div>\n'
        if query_prov and query_prov != title else "")

    return (
        f'<article class="card {tier_cls}">\n'
        f'  <div class="rank">{index}</div>\n'
        f'  <div class="body">\n'
        f'    <div class="header">\n'
        f'      <span class="tag">{emoji}</span>\n'
        f'      <span class="pillar">{_esc(pillar)}</span>\n'
        f'      <span class="score">总分 <b>{_esc(_fmt_num(total))}</b></span>\n'
        f'    </div>\n'
        f'    <h3>{_esc(title)}</h3>\n'
        f'    {digest_html}'
        f'    <p class="summary">{_esc(angle)}</p>\n'
        f'    <div class="dims">{dims}</div>\n'
        f'    <div class="flags">{flags}</div>\n'
        f'    <div class="angle">{provenance}</div>\n'
        f'    {query_html}'
        f'  </div>\n'
        f'</article>\n'
    )


def build_html(date_str: str, topics: list[dict]) -> str:
    high = [t for t in topics if _num(t.get("total")) >= _TIER_HOT]
    mid = [t for t in topics if _TIER_MID <= _num(t.get("total")) < _TIER_HOT]
    low = [t for t in topics if _num(t.get("total")) < _TIER_MID]

    cards = []
    idx = 0
    for bucket in (high, mid, low):
        for item in bucket:
            idx += 1
            cards.append(_render_card(idx, item))

    cards_html = "".join(cards)

    # 评分说明 (动态，基于实际维度)
    dim_desc = "×".join(d[0] for d in _DIMS)

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>热点选题扫描 · {_esc(date_str)}</title>\n'
        f'<style>{_CSS}</style>\n</head>\n<body>\n<div class="container">\n'
        '  <header>\n'
        '    <h1>📡 热点选题扫描</h1>\n'
        f'    <div class="meta">扫描日期 <b>{_esc(date_str)}</b> · '
        f'共 <b>{len(topics)}</b> 个选题 · '
        f'四维评分（{dim_desc}）</div>\n'
        '  </header>\n\n'
        f'{cards_html}\n'
        '  <footer>\n'
        '    本报告由 wechat-main 热点扫描管线自动生成\n'
        '  </footer>\n'
        '</div>\n</body>\n</html>\n'
    )


def _empty_page(date_str: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>热点选题扫描 · {_esc(date_str)}</title>\n'
        f'<style>{_CSS}</style>\n</head>\n<body>\n<div class="container">\n'
        f'  <header><h1>📡 热点选题扫描</h1>'
        f'<div class="meta">扫描日期 <b>{_esc(date_str)}</b></div></header>\n'
        f'  <div class="empty">'
        f'<p>今日热点扫描未产生有效选题。</p>'
        f'<p>搜索关键词覆盖了 {_esc(date_str)} 的热点领域，但全部摘要未通过内容质量阈值。</p>'
        f'</div>\n'
        f'  <footer>本报告由 wechat-main 热点扫描管线自动生成</footer>\n'
        f'</div>\n</body>\n</html>\n'
    )


def _load_scan(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON 解析失败: {e}", file=sys.stderr)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("topics"), list):
        return data["topics"]
    return []


def _derive_date(topics: list[dict], date_arg: str | None) -> str:
    if date_arg:
        if date_arg == "today":
            return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        return date_arg
    best = ""
    for t in topics:
        s = t.get("scanned_at") or ""
        if s and s > best:
            best = s
    if best:
        return best[:10]
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def main() -> int:
    p = argparse.ArgumentParser(
        description="热点选题日报 HTML 渲染器 (v3.0)")
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD 或 today")
    p.add_argument("--output", default=None)
    p.add_argument("--top", type=int, default=0,
                   help="只取总分前 N 条（0=全量）")
    p.add_argument("--scan", default=str(_DEFAULT_SCAN),
                   help=f"scan-results JSON 路径（默认 {_DEFAULT_SCAN}）")
    args = p.parse_args()

    topics = _load_scan(Path(args.scan))
    topics.sort(key=lambda t: _num(t.get("total")), reverse=True)

    # 过滤无 digest 的卡：DeepSeek 精炼失败（瞬时错误）或主动判定『(无明确热点)』
    # 的条目都没有 digest —— 这些卡只有查询词当标题、没有真实内容，渲染出来就是
    # "只有关键词没有内容"。默认丢弃，--keep-no-digest 可关掉过滤用于排查。
    before = len(topics)
    topics = [t for t in topics if (t.get("digest") or "").strip()]
    dropped = before - len(topics)
    if dropped:
        print(f"  🗑️ 过滤 {dropped} 条无 digest 条目（DeepSeek 精炼失败/无热点）",
              file=sys.stderr)

    if args.top and args.top > 0:
        topics = topics[:args.top]

    date_str = _derive_date(topics, args.date)

    if not topics:
        html = _empty_page(date_str)
    else:
        html = build_html(date_str, topics)

    if args.output:
        out_path = Path(args.output).resolve()
        # M-016 (audit-2026-07-06-022): --output 必须落在项目根内，防路径遍历写任意文件
        try:
            out_path.relative_to(_ROOT)
        except ValueError:
            print(f"❌ --output 路径必须在项目根 {_ROOT} 内: {out_path}", file=sys.stderr)
            return 2
    else:
        out_path = _DEFAULT_OUT_DIR / f"hotspot-report-{date_str}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # M-016: atomic write — tempfile + os.replace 防中途崩溃留半截 HTML
    fd, tmp_path = tempfile.mkstemp(
        prefix=".hotspot-report-", suffix=".tmp",
        dir=str(out_path.parent), text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp_path, str(out_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    print(f"✅ 报告已生成: {out_path} "
          f"({len(topics)} 选题, {len(html):,} 字节)")
    return 0


if __name__ == "__main__":
    sys.exit(main())