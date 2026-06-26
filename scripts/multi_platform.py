#!/usr/bin/env python3
"""multi_platform.py — A3 多平台输出复用

从微信长文 Markdown 派生其他平台形态，只做结构拆分，不改写事实。

支持平台：
  - douyin：拆分为60s口播脚本段（每段<200字，开头钩子+3-5个论点段+结尾CTA），
    输出 [{segment, text}]
  - xiaohongshu：产图文卡片（标题<20字、3-5个要点每点<50字、tag列表），
    输出 {title, points, tags}

CLI:
  python multi_platform.py <article.md> --platform <douyin|xiaohongshu> [--json]

退出码：0（纯工具脚本，始终 exit 0）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 项目根 = scripts/ 的父目录
_ROOT = Path(__file__).resolve().parent.parent

# =========================================================================
# 文本工具函数
# =========================================================================

# Markdown 标题正则（# ~ ######）
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# 常见 Markdown 格式标记，用于清理
_MD_CLEAN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),   # 标题标记
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),            # 粗体
    (re.compile(r"\*(.+?)\*"), r"\1"),                # 斜体
    (re.compile(r"`(.+?)`"), r"\1"),                  # 行内代码
    (re.compile(r"!\[.*?\]\(.*?\)"), ""),              # 图片
    (re.compile(r"\[(.+?)\]\(.*?\)"), r"\1"),          # 链接（保留文字）
    (re.compile(r"^>\s?", re.MULTILINE), ""),          # 引用标记
    (re.compile(r"^[-*+]\s", re.MULTILINE), ""),       # 无序列表标记
    (re.compile(r"^\d+\.\s", re.MULTILINE), ""),       # 有序列表标记
    (re.compile(r"^---+$", re.MULTILINE), ""),         # 分隔线
]


def _clean_markdown(text: str) -> str:
    """去除 Markdown 格式标记，保留纯文本内容。"""
    result = text
    for pattern, repl in _MD_CLEAN_PATTERNS:
        result = pattern.sub(repl, result)
    # 合并多余空行
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _split_sections(text: str) -> list[dict[str, str]]:
    """按 Markdown 标题拆分文章为 [{heading, body}] 段落列表。

    无标题的开头文本也会作为第一段（heading 为空字符串）。
    """
    headings = list(_HEADING_RE.finditer(text))

    if not headings:
        # 无标题，整篇作为一段
        return [{"heading": "", "body": _clean_markdown(text)}]

    sections: list[dict[str, str]] = []

    # 第一个标题之前的内容
    pre_text = text[: headings[0].start()].strip()
    if pre_text:
        sections.append({"heading": "", "body": _clean_markdown(pre_text)})

    for i, match in enumerate(headings):
        heading_text = match.group(2).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[start:end].strip()
        sections.append({
            "heading": heading_text,
            "body": _clean_markdown(body),
        })

    return sections


def _extract_sentences(text: str) -> list[str]:
    """将文本按句号/问号/感叹号分句，返回非空句子列表。"""
    parts = re.split(r"(?<=[。！？\n])", text)
    return [s.strip() for s in parts if s.strip()]


# =========================================================================
# 抖音口播脚本：拆分为60s段（每段<200字）
# =========================================================================

_DOUYIN_SEGMENT_MAX_CHARS = 200  # 每段上限


def _build_douyin_segments(sections: list[dict[str, str]]) -> list[dict[str, str]]:
    """将文章段落拆分为口播脚本段。

    策略：
      1. 收集所有段落的纯文本句子
      2. 第一段作为"开头钩子"
      3. 中间段按200字上限切分，形成3-5个论点段
      4. 最后一段作为"结尾CTA"
      5. 如果总段数不足，将中间内容均匀分配
    """
    # 收集所有句子，保留段落归属
    all_sentences: list[str] = []
    for sec in sections:
        body = sec["body"]
        if body:
            sentences = _extract_sentences(body)
            all_sentences.extend(sentences)

    if not all_sentences:
        return [{"segment": 1, "text": "（文章内容为空）"}]

    # 合并全部文本后按字数拆分为段
    segments: list[str] = []
    current_segment: list[str] = []
    current_len = 0

    for sent in all_sentences:
        sent_len = len(sent)
        # 如果当前段加上这句超过上限，先保存当前段
        if current_len + sent_len > _DOUYIN_SEGMENT_MAX_CHARS and current_segment:
            segments.append("".join(current_segment))
            current_segment = []
            current_len = 0
        current_segment.append(sent)
        current_len += sent_len

    # 保存最后一段
    if current_segment:
        segments.append("".join(current_segment))

    if not segments:
        return [{"segment": 1, "text": "（文章内容为空）"}]

    # 标注段落角色：开头钩子 + 论点段 + 结尾CTA
    result: list[dict[str, str]] = []

    if len(segments) == 1:
        # 只有一段时，整段输出
        result.append({"segment": 1, "text": segments[0]})
    elif len(segments) == 2:
        # 两段：钩子 + CTA
        result.append({"segment": 1, "text": f"【开头钩子】{segments[0]}"})
        result.append({"segment": 2, "text": f"【结尾CTA】{segments[1]}"})
    else:
        # 三段及以上：钩子 + N个论点段 + CTA
        result.append({"segment": 1, "text": f"【开头钩子】{segments[0]}"})
        for i, seg_text in enumerate(segments[1:-1], start=2):
            result.append({"segment": i, "text": f"【论点{i - 1}】{seg_text}"})
        result.append({
            "segment": len(segments),
            "text": f"【结尾CTA】{segments[-1]}",
        })

    return result


def generate_douyin(text: str) -> list[dict[str, str]]:
    """生成抖音口播脚本段列表。"""
    sections = _split_sections(text)
    return _build_douyin_segments(sections)


# =========================================================================
# 小红书图文卡片：标题 + 要点 + 标签
# =========================================================================

# 标签提取：常见关键词模式
_TAG_CANDIDATES_RE = re.compile(
    r"(?:AI|人工智能|大模型|ChatGPT|互联网|算法|资本|阶层|社保|医保|"
    r"公积金|996|35岁|内卷|躺平|职场|教育|房价|消费|投资|理财|"
    r"打工人|自由职业|副业|创业|裁员|失业|经济|通胀|GDP|"
    r"养老|退休|生育|人口|城市化|乡村|医疗|住房|贷款)"
)


def _extract_title(sections: list[dict[str, str]], full_text: str) -> str:
    """提取或生成小红书标题（<20字）。

    优先取第一个 Markdown 标题；如果没有标题或标题过长，
    取第一句话并截断到20字。
    """
    # 尝试取第一个非空标题
    for sec in sections:
        heading = sec["heading"]
        if heading:
            if len(heading) <= 20:
                return heading
            # 标题过长，截断
            return heading[:17] + "..."

    # 无标题，取第一句话
    sentences = _extract_sentences(_clean_markdown(full_text))
    if sentences:
        first = sentences[0]
        if len(first) <= 20:
            return first
        return first[:17] + "..."

    return "文章要点整理"


def _extract_points(sections: list[dict[str, str]]) -> list[str]:
    """从各段落提取3-5个核心要点（每点<50字）。

    策略：优先取每个段落的标题（heading），不足时取段落首句。
    """
    points: list[str] = []

    for sec in sections:
        if len(points) >= 5:
            break

        # 优先用标题
        heading = sec["heading"]
        body = sec["body"]

        if heading:
            point = heading if len(heading) <= 50 else heading[:47] + "..."
            points.append(point)
        elif body:
            # 取首句
            sentences = _extract_sentences(body)
            if sentences:
                first = sentences[0]
                point = first if len(first) <= 50 else first[:47] + "..."
                points.append(point)

    # 如果不足3个，尝试从剩余段落的首句补充
    if len(points) < 3:
        for sec in sections:
            if len(points) >= 3:
                break
            body = sec["body"]
            if body:
                sentences = _extract_sentences(body)
                for sent in sentences:
                    if len(points) >= 5:
                        break
                    candidate = sent if len(sent) <= 50 else sent[:47] + "..."
                    if candidate not in points:
                        points.append(candidate)

    # 确保3-5个
    return points[:5] if len(points) > 5 else points


def _extract_tags(text: str) -> list[str]:
    """从全文提取话题标签列表（去重）。"""
    matches = _TAG_CANDIDATES_RE.findall(text)
    # 去重并保持顺序
    seen: set[str] = set()
    tags: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            tags.append(f"#{m}")
    # 如果一个标签都没匹配到，给一个通用标签
    if not tags:
        tags = ["#深度思考", "#长文精华"]
    return tags


def generate_xiaohongshu(text: str) -> dict:
    """生成小红书图文卡片数据。"""
    sections = _split_sections(text)
    title = _extract_title(sections, text)
    points = _extract_points(sections)
    tags = _extract_tags(text)

    return {
        "title": title,
        "points": points,
        "tags": tags,
    }


# =========================================================================
# CLI 入口
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="A3 多平台输出复用 — 从微信长文派生抖音口播脚本 / 小红书图文卡片",
        epilog="退出码: 0（纯工具脚本，始终 exit 0）",
    )
    parser.add_argument(
        "article",
        type=str,
        help="输入的微信长文 Markdown 文件路径",
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=["douyin", "xiaohongshu"],
        help="目标平台：douyin（抖音口播脚本）或 xiaohongshu（小红书图文卡片）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        default=True,
        help="输出 JSON 格式（默认开启）",
    )

    args = parser.parse_args()

    # 读取文章文件
    article_path = Path(args.article).expanduser().resolve()
    if not article_path.is_file():
        print(
            json.dumps({"error": f"文件不存在: {article_path}"}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        sys.exit(1)

    text = article_path.read_text(encoding="utf-8")
    if not text.strip():
        print(
            json.dumps({"error": "文件内容为空"}, ensure_ascii=False, indent=2),
            file=sys.stderr,
        )
        sys.exit(1)

    # 根据平台生成对应输出
    if args.platform == "douyin":
        result = generate_douyin(text)
    else:
        result = generate_xiaohongshu(text)

    # 输出 JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0)


if __name__ == "__main__":
    main()
