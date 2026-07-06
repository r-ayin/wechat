#!/usr/bin/env python3
"""daily_report.py — 确定性热点选题日报 HTML 渲染器

从 topic-pool/scan-results.json（+ 可选 evergreen-pool.json 常青补充）渲染一份
多条热点选题日报 HTML，落地 output/hotspot-report-{date}.html。

纯标准库，零第三方依赖。复刻 output/hotspot-report-2026-06-29.html 的视觉结构
（单列排名卡 + 五维评分条 + 事件/争议/数据标记 + 来源行）。

数据源 schema（scan-results.json item）：
  title / angle / pillar / source / scan_mode / has_event / has_controversy /
  has_data / scanned_at / total / heat / counter_intuitive / narrative_space /
  structural_depth / persona_fit

CLI:
  python scripts/daily_report.py [--date YYYY-MM-DD|today] [--output PATH]
                                 [--top N] [--evergreen-top N] [--scan PATH]
                                 [--evergreen PATH]

退出码：0（空数据时产出占位页而非崩溃）。
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
_DEFAULT_EVERGREEN = _ROOT / "topic-pool" / "evergreen-pool.json"
_DEFAULT_OUT_DIR = _ROOT / "output"

# 卡片分级阈值（与 hotspot-report-2026-06-29.html summary-box 一致）
_TIER_HOT = 7.5
_TIER_MID = 6.0

# 五维字段（顺序即展示顺序）
_DIMS = [
    ("热度", "heat"),
    ("反直觉", "counter_intuitive"),
    ("叙事", "narrative_space"),
    ("结构", "structural_depth"),
    ("人格", "persona_fit"),
]


# =========================================================================
# 工具函数
# =========================================================================

def _esc(text) -> str:
    """HTML 转义，None/非字符串安全。"""
    if text is None:
        return ""
    return _html.escape(str(text), quote=True)


def _num(value, default=0.0) -> float:
    """容错取数：非数转 0。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _tier(total: float) -> tuple[str, str]:
    """总分 → (css 类, emoji)。"""
    if total >= _TIER_HOT:
        return "hot", "🔥"
    if total >= _TIER_MID:
        return "mid", "📌"
    return "low", "🟢"


def _bar_width(score: float) -> int:
    """分数（0-10）→ 进度条宽度百分比（0-100），钳制。"""
    w = int(round(_num(score) * 10))
    return max(0, min(100, w))


def _flag(value) -> str:
    """布尔 → ✓ / —。"""
    return "✓" if value else "—"


def _fmt_num(score) -> str:
    """数字展示：整数去 .0，小数保留一位。"""
    n = _num(score)
    if n == int(n):
        return str(int(n))
    return f"{n:.1f}"


# =========================================================================
# CSS（逐字复刻 hotspot-report-2026-06-29.html，新增 evergreen 分区样式）
# =========================================================================

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
  .summary-box {
    background: #fff; border-radius: 12px; padding: 20px 24px;
    margin-bottom: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
  }
  .summary-box h2 { margin: 0 0 12px; font-size: 18px; }
  .summary-box ul { margin: 0; padding-left: 20px; }
  .summary-box li { margin: 4px 0; font-size: 14px; }
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
  .section-title { margin: 40px 0 16px; font-size: 20px; font-weight: 600; }
  .empty { background:#fff; border-radius:12px; padding:40px; text-align:center; color:#6e6e73; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  footer { text-align: center; color: #8e8e93; font-size: 12px; margin-top: 40px; }
"""


# =========================================================================
# 卡片渲染
# =========================================================================

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
    summary = item.get("angle") or ""
    digest = item.get("digest") or ""
    query_prov = item.get("query") or ""
    source = item.get("source") or "?"
    scan_mode = item.get("scan_mode") or ""
    scanned = item.get("scanned_at") or ""

    dims = "".join(_render_dim(label, item.get(key)) for label, key in _DIMS)
    flags = (
        f"事件 {_flag(item.get('has_event'))} · "
        f"争议 {_flag(item.get('has_controversy'))} · "
        f"数据 {_flag(item.get('has_data'))}"
    )
    provenance = f"数据源 {_esc(source)}"
    if scan_mode:
        provenance += f" · {_esc(scan_mode)}"
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
        f'    <p class="summary">{_esc(summary)}</p>\n'
        f'    <div class="dims">{dims}</div>\n'
        f'    <div class="flags">{flags}</div>\n'
        f'    <div class="angle">{provenance}</div>\n'
        f'    {query_html}'
        f'  </div>\n'
        f'</article>\n'
    )


def _normalize_evergreen(item: dict) -> dict:
    """把 evergreen-pool 的 topic 归一化成 scan-results item 形状。"""
    scores = item.get("scores") or {}
    total = item.get("five_dim_score")
    if total is None:
        total = item.get("priority_score")
    return {
        "title": item.get("title") or item.get("id") or "(无标题)",
        "angle": item.get("angle") or item.get("data") or "",
        "pillar": item.get("pillar") or "常青",
        "source": "evergreen-pool",
        "scan_mode": item.get("urgency") or "",
        "has_event": bool(item.get("event")),
        "has_controversy": False,
        "has_data": bool(item.get("data")),
        "scanned_at": "",
        "total": _num(total),
        "heat": scores.get("heat", 0),
        "counter_intuitive": scores.get("counter_intuitive", 0),
        "narrative_space": scores.get("narrative_space", 0),
        "structural_depth": scores.get("structural_depth", 0),
        "persona_fit": scores.get("persona_fit", 0),
    }


# =========================================================================
# 整页组装
# =========================================================================

def _empty_page(date_str: str, reason: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>热点选题扫描 · { _esc(date_str)}</title>\n'
        f'<style>{_CSS}</style>\n</head>\n<body>\n<div class="container">\n'
        f'  <header><h1>📡 热点选题扫描</h1>'
        f'<div class="meta">扫描日期 <b>{_esc(date_str)}</b></div></header>\n'
        f'  <div class="empty">{_esc(reason)}</div>\n'
        f'  <footer>本报告由 wechat-main 热点扫描管线生成</footer>\n'
        f'</div>\n</body>\n</html>\n'
    )


def build_html(date_str: str, topics: list[dict],
               evergreen: list[dict] | None = None) -> str:
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

    evergreen_html = ""
    if evergreen:
        ev_cards = []
        for i, item in enumerate(sorted(
                evergreen, key=lambda t: _num(t.get("total")), reverse=True), 1):
            ev_cards.append(_render_card(i, item))
        evergreen_html = (
            f'<h2 class="section-title">🌳 常青补充（选题池 ready）</h2>\n'
            f'{"".join(ev_cards)}'
        )

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="UTF-8">\n<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>热点选题扫描 · {_esc(date_str)}</title>\n'
        f'<style>{_CSS}</style>\n</head>\n<body>\n<div class="container">\n'
        '  <header>\n'
        '    <h1>📡 热点选题扫描</h1>\n'
        f'    <div class="meta">扫描日期 <b>{_esc(date_str)}</b> · '
        f'共 <b>{len(topics)}</b> 个选题 · '
        '五维爆款评分（热度×反直觉×叙事×结构×人格）</div>\n'
        '  </header>\n\n'
        '  <div class="summary-box">\n'
        '    <h2>📋 项目身份锚定</h2>\n'
        '    <ul>\n'
        '      <li><b>名称</b>：被压迫者小组 — 信息差平权者</li>\n'
        '      <li><b>核心主张</b>：用深度研究内容帮普通人磨平 AI 时代的信息差</li>\n'
        '      <li><b>内容形态</b>：微信公众号深度长文（15000-30000 字/篇）</li>\n'
        '      <li><b>评分说明</b>：阈值 ≥7.5 🔥 高优 / 6.0-7.5 📌 中优 / &lt;6.0 🟢 待挖</li>\n'
        '    </ul>\n'
        '  </div>\n\n'
        f'{cards_html}\n'
        f'{evergreen_html}\n'
        '  <footer>\n'
        '    数据源：Brave Search API → hot-scanner.py consume · '
        '评分器：topic-pool/hot-scanner.py v2.0<br>\n'
        '    本报告由 wechat-main 热点扫描管线生成\n'
        '  </footer>\n'
        '</div>\n</body>\n</html>\n'
    )


# =========================================================================
# 数据加载
# =========================================================================

def _load_scan(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⚠️ scan-results.json 解析失败: {e}", file=sys.stderr)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("topics"), list):
        return data["topics"]
    return []


def _load_evergreen(path: Path, top_n: int) -> list[dict]:
    if not path.exists() or not top_n:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"⚠️ evergreen-pool.json 解析失败: {e}", file=sys.stderr)
        return []
    topics = data.get("topics", []) if isinstance(data, dict) else []
    ready = [t for t in topics if t.get("status") == "ready"]
    ready.sort(key=lambda t: _num(t.get("five_dim_score") or t.get("priority_score")),
               reverse=True)
    return [_normalize_evergreen(t) for t in ready[:top_n]]


def _derive_date(topics: list[dict], date_arg: str | None) -> str:
    if date_arg:
        if date_arg == "today":
            return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
        return date_arg
    # 默认取 scan-results 最新 scanned_at 的日期
    best = ""
    for t in topics:
        s = t.get("scanned_at") or ""
        if s and s > best:
            best = s
    if best:
        # ISO 8601 → 取前 10 位 YYYY-MM-DD
        return best[:10]
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


# =========================================================================
# CLI
# =========================================================================

def main() -> int:
    p = argparse.ArgumentParser(
        description="确定性热点选题日报 HTML 渲染器")
    p.add_argument("--date", default=None,
                   help="YYYY-MM-DD 或 today；默认取 scan-results 最新 scanned_at 日期")
    p.add_argument("--output", default=None,
                   help="输出 HTML 路径；默认 output/hotspot-report-{date}.html")
    p.add_argument("--top", type=int, default=0,
                   help="只取总分前 N 条（0=全量）")
    p.add_argument("--evergreen-top", type=int, default=5,
                   help="常青补充条数（0=关闭，默认 5）")
    p.add_argument("--scan", default=str(_DEFAULT_SCAN),
                   help=f"scan-results JSON 路径（默认 {_DEFAULT_SCAN}）")
    p.add_argument("--evergreen", default=str(_DEFAULT_EVERGREEN),
                   help=f"evergreen-pool JSON 路径（默认 {_DEFAULT_EVERGREEN}）")
    p.add_argument("--keep-no-digest", action="store_true",
                   help="保留无 digest 的条目（默认过滤：DeepSeek 精炼失败/判定无热点的卡不渲染）")
    args = p.parse_args()

    topics = _load_scan(Path(args.scan))
    topics.sort(key=lambda t: _num(t.get("total")), reverse=True)

    # 过滤无 digest 的卡：DeepSeek 精炼失败（瞬时错误）或主动判定『(无明确热点)』
    # 的条目都没有 digest —— 这些卡只有查询词当标题、没有真实内容，渲染出来就是
    # "只有关键词没有内容"。默认丢弃，--keep-no-digest 可关掉过滤用于排查。
    if not args.keep_no_digest:
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
        evergreen = _load_evergreen(Path(args.evergreen), args.evergreen_top)
        if not evergreen:
            html = _empty_page(date_str, "当前无有效热点信号。运行 hot-scanner 扫描后再生成。")
        else:
            html = build_html(date_str, [], evergreen)
    else:
        evergreen = _load_evergreen(Path(args.evergreen), args.evergreen_top)
        html = build_html(date_str, topics, evergreen)

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
          f"({len(topics)} 选题"
          + (f" + {args.evergreen_top} 常青" if args.evergreen_top else "")
          + f", {len(html):,} 字节)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
