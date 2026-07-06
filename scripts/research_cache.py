#!/usr/bin/env python3
"""research_cache.py -- A2 研究缓存+增量管理

对深度研究结果做本地缓存，降低同主题二次研究成本。
缓存内容：分析摘要（前 2000 字）+ 全部 URL 信源列表。

CLI 子命令：
  get  <slug>                                    查缓存
  put  <slug> --analysis <path> --sources <path>  写缓存
  diff <slug> --new-sources <path>                增量信源对比

缓存目录：output/state/research_cache/{slug}.json

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 项目根 & 缓存目录
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _ROOT / "output" / "state" / "research_cache"

# slug 安全校验：仅允许小写字母、数字、下划线、连字符，防止路径穿越
_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")


def _validate_slug(slug: str) -> str:
    """校验 slug 合法性，非法则打印错误并 exit 0（工具脚本约定）。"""
    if not _SLUG_RE.match(slug):
        print(
            f"错误：slug 仅允许 [a-z0-9_-]，收到 {slug!r}",
            file=sys.stderr,
        )
        sys.exit(0)
    return slug


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

# 匹配 URL 的正则（支持 http / https）
_URL_RE = re.compile(r"https?://[^\s\"\'\)\]>]+")


def _extract_urls(text: str) -> list[str]:
    """从文本中提取所有 URL，去重保持顺序。"""
    seen: set[str] = set()
    urls: list[str] = []
    for m in _URL_RE.finditer(text):
        url = m.group(0).rstrip(".,;:!?。，；：！？")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _read_json_file(path: Path) -> list | dict | None:
    """尝试读取 JSON 文件，返回解析后的对象；失败返回 None 并打印错误。"""
    if not path.exists():
        print(f"错误：文件不存在 -- {path}", file=sys.stderr)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"错误：JSON 解析失败 -- {path}: {e}", file=sys.stderr)
        return None


def _read_text_file(path: Path) -> str | None:
    """读取纯文本文件，失败返回 None。"""
    if not path.exists():
        print(f"错误：文件不存在 -- {path}", file=sys.stderr)
        return None
    return path.read_text(encoding="utf-8")


def _load_sources(path: Path) -> list[str] | None:
    """加载信源列表。支持两种格式：
    1. JSON 数组（字符串列表或含 url 字段的对象列表）
    2. 纯文本（每行一个 URL，或从全文提取 URL）
    """
    text = _read_text_file(path)
    if text is None:
        return None

    # 尝试 JSON 解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            urls: list[str] = []
            for item in data:
                if isinstance(item, str):
                    # 纯 URL 字符串
                    url = item.strip()
                    if url:
                        urls.append(url)
                elif isinstance(item, dict):
                    # 带 url/source/link 字段的对象
                    for key in ("url", "source", "link", "href"):
                        if key in item and isinstance(item[key], str):
                            urls.append(item[key].strip())
                            break
            return urls
        # 如果 JSON 不是数组，回退到文本提取
    except (json.JSONDecodeError, ValueError):
        pass

    # 纯文本模式：提取所有 URL
    return _extract_urls(text)


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------

def cmd_get(slug: str) -> None:
    """查询缓存：输出缓存状态。"""
    _validate_slug(slug)
    cache_path = _CACHE_DIR / f"{slug}.json"
    if not cache_path.exists():
        result = {"cached": False}
    else:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"警告：缓存文件损坏 -- {cache_path}: {e}", file=sys.stderr)
            result = {"cached": False}
        else:
            result = {
                "cached": True,
                "path": str(cache_path),
                "sources": data.get("sources", []),
                "cached_at": data.get("cached_at", ""),
            }

    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_put(slug: str, analysis_path: str, sources_path: str) -> None:
    """写入缓存：摘要取前 2000 字 + 全部 URL 信源。"""
    _validate_slug(slug)
    # 读分析摘要
    analysis_file = Path(analysis_path)
    analysis_text = _read_text_file(analysis_file)
    if analysis_text is None:
        sys.exit(0)

    # 截取前 2000 字
    summary = analysis_text[:2000]

    # 读信源列表
    sources_file = Path(sources_path)
    sources = _load_sources(sources_file)
    if sources is None:
        sys.exit(0)

    # 确保缓存目录存在
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 构造缓存对象
    cache_data = {
        "slug": slug,
        "summary": summary,
        "sources": sources,
        "source_count": len(sources),
        "summary_length": len(summary),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }

    cache_path = _CACHE_DIR / f"{slug}.json"
    cache_path.write_text(
        json.dumps(cache_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = {
        "ok": True,
        "path": str(cache_path),
        "source_count": len(sources),
        "summary_length": len(summary),
        "cached_at": cache_data["cached_at"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_diff(slug: str, new_sources_path: str) -> None:
    """增量对比：比较缓存信源与新信源，输出新增列表。"""
    _validate_slug(slug)
    # 读缓存
    cache_path = _CACHE_DIR / f"{slug}.json"
    if not cache_path.exists():
        # 无缓存时所有新信源都是"新增"
        new_file = Path(new_sources_path)
        new_sources = _load_sources(new_file)
        if new_sources is None:
            sys.exit(0)
        result = {
            "slug": slug,
            "cached": False,
            "new_sources": new_sources,
            "new_count": len(new_sources),
            "cached_count": 0,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 读缓存信源
    try:
        cached_data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"警告：缓存文件损坏 -- {cache_path}: {e}", file=sys.stderr)
        cached_sources: list[str] = []
    else:
        cached_sources = cached_data.get("sources", [])

    # 读新信源
    new_file = Path(new_sources_path)
    new_sources = _load_sources(new_file)
    if new_sources is None:
        sys.exit(0)

    # 计算差集：新增 = 新信源中不在缓存里的
    cached_set = set(cached_sources)
    added = [s for s in new_sources if s not in cached_set]

    result = {
        "slug": slug,
        "cached": True,
        "new_sources": added,
        "new_count": len(added),
        "cached_count": len(cached_sources),
        "total_new_input": len(new_sources),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="A2 研究缓存+增量 -- 缓存深度研究摘要与信源，支持增量对比",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # --- get ---
    p_get = subparsers.add_parser("get", help="查询缓存")
    p_get.add_argument("slug", help="研究主题标识符（如 ai-job-market）")

    # --- put ---
    p_put = subparsers.add_parser("put", help="写入缓存")
    p_put.add_argument("slug", help="研究主题标识符")
    p_put.add_argument(
        "--analysis", required=True, dest="analysis_path",
        help="分析摘要文件路径（纯文本/Markdown，取前 2000 字）",
    )
    p_put.add_argument(
        "--sources", required=True, dest="sources_path",
        help="信源文件路径（JSON 数组或纯文本每行一 URL）",
    )

    # --- diff ---
    p_diff = subparsers.add_parser("diff", help="增量信源对比")
    p_diff.add_argument("slug", help="研究主题标识符")
    p_diff.add_argument(
        "--new-sources", required=True, dest="new_sources_path",
        help="新信源文件路径（JSON 数组或纯文本每行一 URL）",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "get":
        cmd_get(args.slug)
    elif args.command == "put":
        cmd_put(args.slug, args.analysis_path, args.sources_path)
    elif args.command == "diff":
        cmd_diff(args.slug, args.new_sources_path)

    sys.exit(0)


if __name__ == "__main__":
    main()
