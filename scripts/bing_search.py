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

# 重试策略（WM-M-004 audit-2026-07-01-004）：复用 brave_search.py 的瞬时错误重试模式。
# Bing SERP 抓取同样会遭遇 5xx / 网络抖动，单次失败直接丢 query 会让长文模式漏抓严重。
# 仅重试瞬时错误；4xx 客户端错误不重试（重试也不会变）。
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 2          # 初次失败后最多再试 2 次（共 3 次尝试）
_RETRY_BASE_SLEEP = 2.0   # 退避基数；第 n 次重试前 sleep base * 2^n（2s, 4s）

# b_algo 结果块
_BLOCK_RE = re.compile(r'<li class="b_algo".*?</li>', re.S)
_H2_RE = re.compile(r'<h2[^>]*>(.*?)</h2>', re.S)
_P_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')
# 外部结果 URL（排除 bing 自家域名）
_LINK_RE = re.compile(
    r'<a[^>]+href="(https?://(?!r\.bing\.com|www\.bing\.com|bing\.com'
    r'|go\.microsoft|r\.www\.bing|www\.microsoft)[^"]+)"[^>]*>([^<]*)',
    re.S)

# 抓页面长文时剥除的噪音块
_STRIP_BLOCKS_RE = re.compile(
    r'<(script|style|nav|footer|header|aside|noscript|iframe|svg)[ >].*?</\1>',
    re.S | re.I)
# 主文文本节点
_TEXT_BLOCK_RE = re.compile(
    r'<(p|h[1-6]|li|article|section)[^>]*>(.*?)</\1>', re.S | re.I)
_WS_RE = re.compile(r'\s+')

# 字典/字源/百科/导航内容模式（出现任一即整块跳过：Bing 对抽象查询词常返回字源解释）
_DICT_PATTERNS = (
    # 字典/字源
    "汉语文字", "汉字词典", "_百度百科", "的拼音是", "的拼音为",
    "字Unicode", "字五行属", "部首为", "笔顺为", "笔画为",
    "字形结构为", "五笔为", "仓颉码", "Unicode码", "Unicode编码",
    "字属《", "多音字", "古字形", "形声字", "造字法为", "可拆字为",
    "汉语形容词", "汉语动词", "汉语名词", "属褒义词", "属贬义词",
    # 单字解释页常见词（无「为」后缀也跳）
    "笔顺", "笔划", "笔画顺序", "总画数", "字的基本信息", "字怎么写",
    "注音", "部首:", "部首：", "字属于", "字的笔顺", "字Unicode码",
    # 字源学/古文字
    "字源", "字形演变", "甲骨文", "金文", "说文", "小篆", "西周金文",
    "象形", "形声", "会意", "本义", "引申义",
    # 知乎/百度知道/字典站常见模式
    "_百度知道", "是什么意思", "近义词", "反义词", "例句：",
    "人族", "人属", "亚族", "黑猩猩", "灵长目",
    # 营销/教程/导航页
    "AI对话助手", "千问是", "阿里Qwen", "菜鸟教程", "App Store",
    "开发者:", "开发者：", "Web site created using",
)


def _is_dict_content(text: str) -> bool:
    if not text:
        return False
    return any(p in text for p in _DICT_PATTERNS)


# 不抓长文的域名（百科/字典/导航/登录页 之类对热点选题没用的源）
_SKIP_DOMAINS = (
    "baike.baidu.com", "wapbaike.baidu.com", "zdic.net", "hanyuguoxue.com",
    "dict.cn", "m.baidu.com", "m.bing.com", "sina.com.cn", "qq.com",
    "weibo.com", "weibo.cn", "passport.baidu.com", "login.", "passport.",
    "sh.wikipedia.org", "zh.wikipedia.org", "en.wikipedia.org",
    "baike.sogou.com", "baike.so.com", "youdao.com", "fanyi.baidu.com",
    "translate.google", "microsoft.com", "ad.doubleclick",
    "hancibao.com", "strokeorder.cc", "newdu.com", "gushici.net",
    "chaziwang.com", "zdish.com", "qhanzi.com", "huohao.name",
    "5ihanzi.com", "shuofanzi.com", "mofangju.com",
    # 视频/外卖/社交平台首页（对热点选题无价值）
    "iqiyi.com", "youku.com", "v.qq.com", "bilibili.com", "douyin.com",
    "meituan.com", "ele.me", "waimai.meituan.com",
    "x.com", "twitter.com", "facebook.com", "instagram.com",
    # 技术博客/营销页（对劳动/社会议题无价值）
    "csdn.net", "juejin.cn", "qcloud.com", "aliyun.com", "alibaba.com",
    "qianwen.aliyun", "tongyi.aliyun", "baidu.com/link",
    # AI 工具导航/教程站
    "qianwen.aigc.cn", "ai-bot.cn", "ai-kit.cn", "runoob.com", "runoob.cn",
    "hello-algo.com", "hellowac.net", "baikedazhishi.com", "baida.com",
    "chazidian.com", "chinazidian.com", "9785.com", "tianyantech",
)


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


def _is_skip_url(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in _SKIP_DOMAINS)


def _bing_fetch(query: str, count: int) -> list[dict]:
    """抓 Bing SERP，返回 [{title, snippet, url}] 列表。"""
    params = {"q": query, "count": str(count), "setlang": "zh-Hans",
              "cc": "CN", "form": "QBLH"}
    url = f"{_BING_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8", "replace")

    # 先用 b_algo 块取 title/snippet（保持一期行为），按块 cite 域名 + 内容模式过滤百科/字典
    results: list[dict] = []
    seen_urls: set[str] = set()
    for block in _BLOCK_RE.findall(raw):
        # 块级 cite URL：若是百科/字典/导航类，整块跳过（避免 snippet 泄漏字源/拼音文本）
        cite_m = re.search(r"<cite[^>]*>(.*?)</cite>", block, re.S)
        cite_url = _strip(cite_m.group(1)) if cite_m else ""
        # cite 文本里 bing 把 https:// 拆成 "https://... › ..."，取首段判域名
        cite_head = cite_url.split(" ")[0].split("›")[0].strip("/")
        if cite_head and _is_skip_url(cite_head):
            continue
        h2 = _H2_RE.search(block)
        p = _P_RE.search(block)
        title = _strip(h2.group(1)) if h2 else ""
        snippet = _strip(p.group(1)) if p else ""
        # 内容模式兜底：title/snippet 像字典/字源条目则整块跳过
        if _is_dict_content(title) or _is_dict_content(snippet):
            continue
        if title or snippet:
            results.append({"title": title, "snippet": snippet, "url": ""})

    # 再用 _LINK_RE 兜底补 URL（按出现顺序对齐前几个 result；对不上就独立追加）
    ext_links = [(u, _strip(t)) for u, t in _LINK_RE.findall(raw)
                 if not _is_skip_url(u) and u not in seen_urls]
    for i, (u, _t) in enumerate(ext_links):
        seen_urls.add(u)
        if i < len(results) and not results[i].get("url"):
            results[i]["url"] = u
        else:
            # 多余的链接作为无 snippet 的额外结果
            results.append({"title": "", "snippet": "", "url": u})

    return [r for r in results if r.get("title") or r.get("snippet") or r.get("url")]


def _fetch_page_text(url: str, timeout: int, max_chars: int) -> str:
    """抓单个 URL 的页面主文文本。失败返回空串。"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "pdf" in ctype or "image" in ctype or "video" in ctype:
                return ""
            raw = resp.read(2_000_000)  # 单页最多读 2MB
    except (urllib.error.HTTPError, urllib.error.URLError,
            TimeoutError, ConnectionError):
        return ""
    except Exception:  # noqa: BLE001
        return ""

    # 解码：优先 utf-8，再试 gbk
    text = None
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            text = raw.decode(enc, errors="strict")
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "replace")

    # 剥噪音块
    text = _STRIP_BLOCKS_RE.sub("", text)
    # 抽主文节点
    chunks = []
    total = 0
    for m in _TEXT_BLOCK_RE.finditer(text):
        body = m.group(2)
        clean = _html.unescape(_TAG_RE.sub("", body)).strip()
        clean = _WS_RE.sub(" ", clean)
        if len(clean) < 20:
            continue
        chunks.append(clean)
        total += len(clean)
        if total >= max_chars:
            break
    out = " ".join(chunks)
    return out[:max_chars]


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


def _summarize_long(results: list[dict], pages_per_query: int,
                    page_timeout: int, max_chars_per_page: int,
                    max_total: int = 5000) -> str:
    """长文 summary：SERP 摘要 + top N 结果页面正文，每页截断到 max_chars_per_page。

    页面正文抓回后再过一遍 _is_dict_content（防 SERP cite 没匹配但页面是字典）。
    最终 summary 必须含 20XX 日期模式，否则视为非新闻返回空串（让调用方丢弃）。
    """
    parts: list[str] = []
    total = 0
    fetched = 0
    for r in results:
        t = r.get("title", "").strip()
        s = r.get("snippet", "").strip()
        u = r.get("url", "").strip()
        head = ""
        if t and s:
            head = f"{t}。{s}"
        elif s:
            head = s
        elif t:
            head = t
        if head:
            parts.append(head)
            total += len(head)
        if fetched >= pages_per_query or not u:
            continue
        page = _fetch_page_text(u, page_timeout, max_chars_per_page)
        # 页面正文也跑字典/营销模式检测，避免 SERP cite 漏判
        if len(page) >= 80 and not _is_dict_content(page[:500]):
            parts.append(page)
            total += len(page)
            fetched += 1
            if total >= max_total:
                break
    out = " ".join(parts)
    out = out[:max_total]
    # 必须含 4 位年份 + 月/日 之一的日期模式才认为是新闻；否则返回空让调用方丢
    if not re.search(r"20\d{2}\s*年[\s\d月]|\b20\d{2}-\d{1,2}", out):
        return ""
    return out


def _fetch_one(query: str, count: int, long_form: bool,
               pages_per_query: int, page_timeout: int,
               max_chars_per_page: int) -> tuple[str, bool]:
    """取一条 query 的 summary。瞬时错误（429/5xx/网络）按指数退避重试 _MAX_RETRIES 次。

    WM-M-004 (audit-2026-07-01-004): 复用 brave_search._fetch_one 的重试模式，避免单次
    5xx / 网络抖动就让整条 query 丢失（长文模式下尤其昂贵，已抓的页面正文也白费）。
    """
    last_err = ""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            results = _bing_fetch(query, count)
            if long_form:
                summary = _summarize_long(
                    results, pages_per_query, page_timeout, max_chars_per_page)
            else:
                summary = _summarize(results)
            return summary, bool(results)
        except urllib.error.HTTPError as e:
            last_err = f"[{e.code}]"
            if e.code not in _RETRYABLE_HTTP_CODES:
                print(f"⚠️ [{e.code}] {query!r}", file=sys.stderr)
                break  # 客户端错误，重试无意义
        except urllib.error.URLError as e:
            last_err = f"网络错误 {e.reason}"
        except Exception as e:  # noqa: BLE001
            last_err = f"异常 {e}"
            print(f"⚠️ 异常 {query!r}: {e}", file=sys.stderr)
            break  # 未知异常不重试
        if attempt < _MAX_RETRIES:
            sleep_s = _RETRY_BASE_SLEEP * (2 ** attempt)
            print(f"  ↻ 重试 {attempt+1}/{_MAX_RETRIES} [{query!r}] "
                  f"{sleep_s:.1f}s 后重试（{last_err[:80]}）", file=sys.stderr)
            time.sleep(sleep_s)
    if last_err and "异常" not in last_err and "[" not in last_err:
        # 仅网络错误走到这里时打印（HTTPError/Exception 已在上面打印）
        print(f"⚠️ {last_err} {query!r}", file=sys.stderr)
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
        summary, good = _fetch_one(
            qt, args.count, args.long_form, args.pages_per_query,
            args.page_timeout, args.max_chars_per_page)
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
          f"({len(results)} 条 summary, long_form={args.long_form})",
          file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Bing 中国 SERP 抓取取数器（含长文模式）")
    p.add_argument("--output", default=_DEFAULT_OUTPUT)
    p.add_argument("--max-queries", type=int, default=0)
    p.add_argument("--count", type=int, default=8, help="每条 query 取结果数（默认 8）")
    p.add_argument("--pillar", default=None)
    p.add_argument("--mode", default="hybrid", choices=["hybrid", "keyword", "event"])
    p.add_argument("--sleep", type=float, default=1.0)
    p.add_argument("--long-form", action=argparse.BooleanOptionalAction,
                   default=True, help="抓 SERP top 结果页面正文（默认开）")
    p.add_argument("--pages-per-query", type=int, default=2,
                   help="长文模式每条 query 抓几个页面（默认 2）")
    p.add_argument("--page-timeout", type=int, default=8,
                   help="单页抓取超时秒（默认 8）")
    p.add_argument("--max-chars-per-page", type=int, default=2000,
                   help="单页正文截断字符数（默认 2000）")
    args = p.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
