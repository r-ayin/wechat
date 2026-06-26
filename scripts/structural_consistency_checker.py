#!/usr/bin/env python3
"""
QAH-03 逻辑一致性五问代码化 — 结构性一致性检查器。

检查文章是否存在"结构问题 -> 个体方案"的反模式矛盾，以及其他逻辑一致性指标。

五项检查：
  1. 论点维度分类 — 扫前30%文本，统计结构词 vs 个人词词频 → 主论点维度
  2. 结尾方案维度 — 扫后20%文本，同样分类
  3. 一致性判定   — 论点=structural 而结尾=individual → contradiction
  4. 诚实结尾检测 — 结尾是否含诚实承认困难的表达 vs 简单答案词
  5. 理论引用比例 — 含书名号《》或专家归属的句子占比

CLI: python structural_consistency_checker.py <article.md> [--json]

退出码：0=通过(pass), 2=告警(warn), 1=阻断(block)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 项目根目录
_ROOT = Path(__file__).resolve().parent.parent


# =========================================================================
# 词表定义
# =========================================================================

# 结构性词汇：指向制度/系统/社会结构层面的分析
STRUCTURAL_WORDS: list[str] = [
    "制度", "体制", "结构", "系统", "资本", "阶层", "政策", "产业", "规训",
    "权力", "剥削", "垄断", "不平等", "阶级", "体系", "机制", "分配",
    "社会", "集体", "组织", "工会", "团结", "连接", "联合",
]

# 个人性词汇：指向个体行动/心态层面的建议
INDIVIDUAL_WORDS: list[str] = [
    "个人", "自己", "努力", "心态", "选择", "勇气", "觉醒", "改变自己",
    "坚持", "信念", "意志", "自律", "成长", "突破", "提升自己",
    "勇敢", "坚强", "独立思考", "内心",
]

# 诚实结尾词汇：承认困难、不提供简单答案
HONEST_ENDING_WORDS: list[str] = [
    "没有简单答案", "做不到", "一个人", "找到", "和你一样", "处境一样",
    "不容易", "没有捷径", "无法独自", "无解", "承认", "困难",
    "不可能靠一个人", "连接", "信号需要被连接", "找到其他",
]

# 简单答案词汇：暗示存在轻松解法
SIMPLE_ANSWER_WORDS: list[str] = [
    "答案", "秘诀", "只需", "只要你", "你只需要", "一招",
    "立刻", "马上就能", "轻松", "简单方法", "唯一的方法就是",
]

# 理论引用匹配：书名号内容 或 专家归属模式
_BOOK_TITLE_RE = re.compile(r"《[^》]+》")
_EXPERT_ATTR_RE = re.compile(
    r"(?:教授|学者|专家|院士|博士|研究员|经济学家|社会学家|哲学家|作家)"
    r"[一-鿿]{2,4}(?:说|认为|指出|表示|提出|写道|在)"
)
# 反向归属："某某教授/学者/博士 说/认为"
_EXPERT_ATTR_REV_RE = re.compile(
    r"[一-鿿]{2,4}"
    r"(?:教授|学者|专家|院士|博士|研究员|经济学家|社会学家|哲学家|作家)"
    r"(?:说|认为|指出|表示|提出|写道|曾)"
)


# =========================================================================
# 核心分析函数
# =========================================================================

def _count_words(text: str, word_list: list[str]) -> int:
    """统计文本中词表词汇的总出现次数。"""
    count = 0
    for w in word_list:
        count += text.count(w)
    return count


def classify_dimension(text: str) -> tuple[str, int, int]:
    """
    根据结构词 vs 个人词词频比对文本进行维度分类。

    返回: (维度标签, 结构词频, 个人词频)
    维度标签: "structural" / "individual" / "mixed"
    """
    s_count = _count_words(text, STRUCTURAL_WORDS)
    i_count = _count_words(text, INDIVIDUAL_WORDS)

    total = s_count + i_count
    if total == 0:
        return "mixed", s_count, i_count

    s_ratio = s_count / total
    # 结构词占比 > 60% → structural；个人词占比 > 60% → individual；否则 mixed
    if s_ratio > 0.6:
        return "structural", s_count, i_count
    elif s_ratio < 0.4:
        return "individual", s_count, i_count
    else:
        return "mixed", s_count, i_count


def check_honest_ending(ending_text: str) -> bool:
    """
    检测结尾是否为诚实结尾（承认困难，不假装有简单答案）。

    规则：存在诚实词 且 简单答案词不多于诚实词 → True
    """
    honest_count = _count_words(ending_text, HONEST_ENDING_WORDS)
    simple_count = _count_words(ending_text, SIMPLE_ANSWER_WORDS)

    if honest_count > 0 and honest_count >= simple_count:
        return True
    if simple_count > 0 and honest_count == 0:
        return False
    # 两者都为 0，不做判断，默认诚实（无明显简单答案倾向）
    return True


def compute_theory_ratio(text: str) -> float:
    """
    计算理论引用比例：含书名号《》或专家归属的句子占总句子数的比例。
    """
    # 按句号/问号/感叹号/换行 分句
    sentences = re.split(r"[。！？\n]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return 0.0

    theory_count = 0
    for sent in sentences:
        if _BOOK_TITLE_RE.search(sent):
            theory_count += 1
        elif _EXPERT_ATTR_RE.search(sent):
            theory_count += 1
        elif _EXPERT_ATTR_REV_RE.search(sent):
            theory_count += 1

    return theory_count / len(sentences)


def analyze(text: str) -> dict:
    """
    对文章全文执行五项逻辑一致性检查，返回结果字典。

    返回:
      {
        "thesis_dim": str,          # 论点维度: structural/individual/mixed
        "ending_dim": str,          # 结尾方案维度
        "contradiction": bool,      # 是否存在结构问题→个体方案矛盾
        "honest_ending": bool,      # 结尾是否诚实
        "theory_ratio": float,      # 理论引用比例
        "verdict": str,             # pass / warn / block
        "details": dict             # 详细数据（词频等）
      }
    """
    total_len = len(text)

    # 前30%文本 → 论点维度
    thesis_cutoff = int(total_len * 0.3)
    thesis_text = text[:thesis_cutoff]
    thesis_dim, thesis_s, thesis_i = classify_dimension(thesis_text)

    # 后20%文本 → 结尾方案维度
    ending_cutoff = int(total_len * 0.8)
    ending_text = text[ending_cutoff:]
    ending_dim, ending_s, ending_i = classify_dimension(ending_text)

    # 一致性判定：结构问题 → 个体方案 = contradiction
    contradiction = (thesis_dim == "structural" and ending_dim == "individual")

    # 诚实结尾检测
    honest_ending = check_honest_ending(ending_text)

    # 理论引用比例（全文）
    theory_ratio = compute_theory_ratio(text)

    # 综合判定
    verdict = "pass"
    reasons: list[str] = []

    if contradiction:
        verdict = "block"
        reasons.append("结构问题→个体方案矛盾（contradiction）")
    if theory_ratio > 0.2:
        if verdict != "block":
            verdict = "warn"
        reasons.append(f"理论引用比例过高: {theory_ratio:.1%} > 20%")
    if not honest_ending:
        if verdict != "block":
            verdict = "warn"
        reasons.append("结尾倾向简单答案，缺少诚实承认困难的表达")

    return {
        "thesis_dim": thesis_dim,
        "ending_dim": ending_dim,
        "contradiction": contradiction,
        "honest_ending": honest_ending,
        "theory_ratio": round(theory_ratio, 4),
        "verdict": verdict,
        "details": {
            "thesis_structural_count": thesis_s,
            "thesis_individual_count": thesis_i,
            "ending_structural_count": ending_s,
            "ending_individual_count": ending_i,
            "reasons": reasons,
        },
    }


# =========================================================================
# CLI 入口
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="QAH-03 逻辑一致性五问代码化 — 结构性一致性检查器",
        epilog="退出码: 0=pass, 2=warn(soft), 1=block(hard)",
    )
    parser.add_argument(
        "article",
        type=str,
        help="待检查的文章 Markdown 文件路径",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="以 JSON 格式输出结果（默认即 JSON）",
    )

    args = parser.parse_args()

    # 读取文章文件
    article_path = Path(args.article).expanduser().resolve()
    if not article_path.is_file():
        print(json.dumps({"error": f"文件不存在: {article_path}"}, ensure_ascii=False, indent=2),
              file=sys.stderr)
        sys.exit(1)

    text = article_path.read_text(encoding="utf-8")
    if not text.strip():
        print(json.dumps({"error": "文件内容为空"}, ensure_ascii=False, indent=2),
              file=sys.stderr)
        sys.exit(1)

    # 执行分析
    result = analyze(text)

    # 输出 JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 退出码映射
    verdict = result["verdict"]
    if verdict == "block":
        sys.exit(1)
    elif verdict == "warn":
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
