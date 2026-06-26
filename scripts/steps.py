#!/usr/bin/env python3
"""steps.py — 微信管线步骤模板物化器（运行时无关，纯 Python）

为 pipeline.py 提供各 phase 的确定性步骤清单。每个步骤是一份自包含任务规格：
  - gate_check / gate_verify / code:  主 agent 直接 bash 执行的 cmd
  - subagent:                          task_file（物化后落盘）+ output 路径

设计原则：
  - 不 import 任何 Claude/Agent 运行时（可移植到 WorkBuddy 等）。
  - task_spec 写入磁盘文件，主 agent 只传 task_file 路径给子 agent → 主上下文不接触内容。
  - code 步骤（QA extract/judge）直跑 verifier，无需子 agent，不依赖模型能力。
  - Phase 3.5 的 article 路径在 init 时未知（标题由 Phase 3 子 agent 决定），
    用 __ARTICLE__ 占位符，由 pipeline.py next 在该步发射前解析填充。

被 pipeline.py 调用：build_steps(slug, date, brief_path, mode, min_bytes) -> list[step]
"""

from __future__ import annotations
from pathlib import Path
import os

# 项目根（scripts/ 的父目录）
_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _ROOT / "output" / "state"


def _state_file(slug: str, date: str) -> Path:
    return _STATE_DIR / f"{slug}_{date}.json"


def _task_file(slug: str, step_id: str) -> Path:
    return _STATE_DIR / f"{slug}_task_{step_id}.md"


def _research(slug: str, date: str, kind: str) -> str:
    """output/research/{slug}_{kind}_{date}.md"""
    return f"output/research/{slug}_{kind}_{date}.md"


def _article_glob(slug: str, date: str) -> str:
    """Phase 3 文章可能落在 hot/ 或 evergreen/，文件名含中文标题。"""
    return f"output/wechat_articles/*/{slug}_*_{date}.md"


def _write_task(slug: str, step_id: str, content: str) -> str:
    p = _task_file(slug, step_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p.relative_to(_ROOT))


# =========================================================================
# 各 phase subagent task_spec 模板（物化后落盘）
# =========================================================================

def _task_phase0(slug, date, brief_path, min_bytes) -> str:
    brief_line = f"如有 brief，读取 {brief_path} 的「对标参考」字段用于差异化空间定位。\n" if brief_path else ""
    return f"""# Phase 0 子 agent 任务：竞品风格蒸馏

选题: {slug}  日期: {date}

## 输入（从磁盘读）
- benchmark/accounts_database.md — 对标账号库（Tier1-3 账号、爆款写法、改写铁律五条）
- reference/evomap-competitor-landscape.md — 五维拆解 + 信源表格式标杆
{brief_line}
## 执行
1. 搜狗微信搜索竞品文章：https://weixin.sogou.com/weixin?type=2&query={{关键词}} （≥5 篇）
2. 五维拆解：维度1选题切口 / 维度2核心论点 / 维度3人物选择 / 维度4证据链 / 维度5对标差异化
3. 竞对情感温度评估（X/10，必填）
4. 情感温度内联计算（INCONSIST-04，禁止硬编码 2/10）：
   P = persona/STYLE.md 第 15 维评分；C = 上面竞对温度
   |P-C|≤1 → max(P,C)；1<|P-C|≤3 → P；|P-C|>3 → P*0.6+C*0.4

## 输出（只写这一个文件，不回传内容）
写入 {_research(slug, date, 'competitor-style')}
门禁要求：≥2000 bytes && 含「维度1..5 或 五维」&& 含 X/10 情感温度数字。
"""


def _task_phase1(slug, date, brief_path, mode) -> str:
    dankoe = ""
    if mode == "manual" and brief_path:
        dankoe = f"- 手动模式：读取 {brief_path}（Dankoe 八问采访产出），消费其全部字段\n"
    return f"""# Phase 1 子 agent 任务：研究简报

选题: {slug} 日期: {date}
{dankoe}
## 输入
- Phase 0 产出 {_research(slug, date, 'competitor-style')}
- planning/requirements.md — brief 字段定义

## 执行
产出研究简报，必含字段：
- 核心论点
- 要推翻的误解（非共识角度）
- 数据素材（可验证）
- 对标竞品盲区
- 受众画像 / 情感锚点 / 个人关联 / 行动导向 / 认知层级 / 内容象限（供下游穿透）

## 输出
写入 {_research(slug, date, 'brief')}
门禁：≥1500 bytes。
"""


def _task_phase2(slug, date, min_bytes) -> str:
    return f"""# Phase 2 子 agent 任务：godtier 13 层深度分析

选题: {slug} 日期: {date}

## 执行（复用 godtier 引擎，不要自创流程）
1. 运行 `python .claude/skills/godtier-deep-research/scripts/orchestration/executor.py plan {slug} --mode auto`
2. 按 phase1 agent_list 并行 delegate_task 8 个采集 Agent（prompt 模板见 .claude/skills/godtier-deep-research/workflows/05-phase1-collection.md）
3. 按 phase2 agent_list 并行 delegate_task 7 个分析 Agent（模板见 workflows/06-phase2-analysis.md，强制调用 scripts/computation/* 脚本计算，禁止心算）
4. 整合为 13 层（L-1 到 L10）分析长文

## 输出
写入 {_research(slug, date, 'analysis')}
门禁：≥{min_bytes} bytes && ≥10 个 `## L` 层标题。
若本环境 WECHAT_MIN_BYTES 已降为 draft 档，相应放宽。
"""


def _task_phase3(slug, date, brief_path, min_bytes) -> str:
    brief_line = f"消费 brief：受众画像(语言复杂度)、情感锚点(温度参数)、个人关联(独特视角)、行动导向(CTA)。\n" if brief_path else ""
    return f"""# Phase 3 子 agent 任务：persona 人格化重写

选题: {slug} 日期: {date}

## 输入（强制读取三件套，未读即违规）
- persona/SOUL.md  核心信念与世界観
- persona/STYLE.md 15 维风格指纹 + 情感温度
- persona/PERSONA.md 紧凑人设卡
- Phase 2 分析 {_research(slug, date, 'analysis')}
- Phase 0 竞品 {_research(slug, date, 'competitor-style')}（标题规律参考）
{brief_line}
## 执行（三步迁移法）
1. 提取 godtier 分析的纯结构骨架
2. SOUL.md 作为世界观约束注入
3. STYLE.md 15 维风格指纹控制文风
4. 标题：基于 Phase 0 竞品标题规律（不是A是B / 冒号对照 / 引号反讽 / 身份词前置）
5. 摘要：100-150 字，含具体数字/场景/人物
6. 文末 frontmatter 含标记：`SOUL+STYLE+PERSONA 全量注入`
铁律：有名有姓人物 + 具体场景 + 可验证数据 + 热点钩子；理论引用≤20%；无 ## 小标题/列表/加粗；无脏话。

## 输出
写入 output/wechat_articles/hot/{slug}_<标题>_{date}.md  （热点选题放 hot/，常青选题放 evergreen/；文件名须以 {slug}_ 开头、以 _{date}.md 结尾）
门禁：≥{min_bytes} bytes && 含 `SOUL+STYLE+PERSONA` && 含「摘要」 && 标题 8-35 字。
"""


def _task_phase35_search(slug, date) -> str:
    return f"""# Phase 3.5 子 agent 任务：QA 搜索取证

选题: {slug} 日期: {date}

## 输入
- 声明计划 output/state/{slug}_qa_plan.json （verifier.py extract 已产出，含 claims 数组与搜索查询）

## 执行
对 plan 中每条 claim 的 query 逐条 WebSearch，把搜索摘要写入 output/state/{slug}_qa_results.json：
格式 {{ "<claim_id>": "搜索摘要文本" }}
- 精确数字无来源 / 政策报告名 → 高优先级，必须搜
- 官方/权威信源（gov.cn/xinhuanet/who.int 等）加分
- 找不到信源的可留空字符串，但不要编造

## 输出
只写 output/state/{slug}_qa_results.json，不回传内容。
"""


def _task_phase35_remediation(slug, date, attempt) -> str:
    return f"""# Phase 3.5 子 agent 任务：FALSIFIED 修复（第 {attempt} 轮，最多 3 轮）

选题: {slug} 日期: {date}

## 输入
- QA 报告 output/state/{slug}_qa_report.json（含 falsified_claims 与 remediation_hints）
- 原文章：用 glob `output/wechat_articles/*/{slug}_*_{date}*.md` 定位（pipeline.py 已保证文件存在）

## 执行
1. 对每条 FALSIFIED 声明 WebSearch 找真实替代数据
2. 基于真实数据重写文章中对应段落（只改事实性内容，不动结构与文风）
3. 严禁编造；找不到替代 → 删除该段落或降级为「据公开资料」表述

## 输出
直接修改原文章文件（in-place）。修复后 pipeline.py 会重新 extract→search→judge（重新取证，不复用旧搜索结果）。
"""


def _task_phase4(slug, date) -> str:
    return f"""# Phase 4 子 agent 任务：输出与归档

选题: {slug} 日期: {date}

## 执行
1. 更新 PROGRESS.md：加一行 `- [x] {date}: {slug} 长文产出`
2. git add output/wechat_articles/ && git commit -m "feat: {slug} 长文 ({date})" && git push origin main
   （若非 git 仓库或无 remote，跳过 push 并在 PROGRESS.md 注明）

## 输出
PROGRESS.md 更新 + git 提交。门禁 verify 4 直接通过。
"""


# =========================================================================
# 步骤清单构建
# =========================================================================

def build_steps(slug: str, date: str, brief_path: str | None, mode: str,
                min_bytes: int) -> list[dict]:
    """构建完整 happy-path 步骤清单（Phase 3.5 修复循环由 pipeline.py 动态插入）。"""
    steps: list[dict] = []
    mb = str(min_bytes)

    def add(sid, phase, kind, **kw):
        s = {"id": sid, "phase": phase, "kind": kind, "status": "pending"}
        s.update(kw)
        steps.append(s)

    # Phase 0
    add("0.check", "0", "gate_check",
        cmd=f"bash scripts/pipeline-gate.sh check 0 {slug} {date}")
    add("0.work", "0", "subagent",
        task_file=_write_task(slug, "0.work", _task_phase0(slug, date, brief_path, mb)),
        output=_research(slug, date, "competitor-style"))
    add("0.verify", "0", "gate_verify",
        cmd=f"bash scripts/pipeline-gate.sh verify 0 {slug} {date}")

    # Phase 1
    add("1.check", "1", "gate_check",
        cmd=f"bash scripts/pipeline-gate.sh check 1 {slug} {date}")
    add("1.work", "1", "subagent",
        task_file=_write_task(slug, "1.work", _task_phase1(slug, date, brief_path, mode)),
        output=_research(slug, date, "brief"))
    add("1.verify", "1", "gate_verify",
        cmd=f"bash scripts/pipeline-gate.sh verify 1 {slug} {date}")

    # Phase 2
    add("2.check", "2", "gate_check",
        cmd=f"bash scripts/pipeline-gate.sh check 2 {slug} {date}")
    add("2.work", "2", "subagent",
        task_file=_write_task(slug, "2.work", _task_phase2(slug, date, mb)),
        output=_research(slug, date, "analysis"))
    add("2.verify", "2", "gate_verify",
        cmd=f"bash scripts/pipeline-gate.sh verify 2 {slug} {date}")

    # Phase 3
    add("3.check", "3", "gate_check",
        cmd=f"bash scripts/pipeline-gate.sh check 3 {slug} {date}")
    add("3.work", "3", "subagent",
        task_file=_write_task(slug, "3.work", _task_phase3(slug, date, brief_path, mb)),
        output=f"output/wechat_articles/*/{slug}_*_{date}.md")
    add("3.verify", "3", "gate_verify",
        cmd=f"bash scripts/pipeline-gate.sh verify 3 {slug} {date}")

    # Phase 3.5 QA：extract(code) → search(subagent) → judge(code) → verify
    plan_json = f"output/state/{slug}_qa_plan.json"
    results_json = f"output/state/{slug}_qa_results.json"
    report_json = f"output/state/{slug}_qa_report.json"
    add("3.5.check", "3.5", "gate_check",
        cmd=f"bash scripts/pipeline-gate.sh check 3.5 {slug} {date}")
    add("3.5.extract", "3.5", "code",
        cmd=f"python script-verifier/verifier.py extract __ARTICLE__ -o {plan_json}",
        output=plan_json)
    add("3.5.search", "3.5", "subagent",
        task_file=_write_task(slug, "3.5.search", _task_phase35_search(slug, date)),
        output=results_json)
    add("3.5.judge", "3.5", "code",
        cmd=f"python script-verifier/verifier.py judge {plan_json} --results {results_json} -o {report_json}",
        output=report_json,
        is_judge=True)  # pipeline.py 据此在失败时动态插入修复循环
    add("3.5.verify", "3.5", "gate_verify",
        cmd=f"bash scripts/pipeline-gate.sh verify 3.5 {slug} {date}")

    # Phase 4
    add("4.check", "4", "gate_check",
        cmd=f"bash scripts/pipeline-gate.sh check 4 {slug} {date}")
    add("4.work", "4", "subagent",
        task_file=_write_task(slug, "4.work", _task_phase4(slug, date)),
        output="PROGRESS.md")
    add("4.verify", "4", "gate_verify",
        cmd=f"bash scripts/pipeline-gate.sh verify 4 {slug} {date}")

    return steps


def build_remediation_steps(slug: str, date: str, attempt: int) -> list[dict]:
    """judge 失败时动态插入的修复循环步骤（attempt 从 1 起，≤3）。

    完整循环：remediation(改文章) → reextract(抽新 claim) → re-search(为新 claim 重新取证)
    → rejudge(用新搜索结果判定)。re-search 必须有，否则 rejudge 复用旧 results.json，
    而新 claim_id 在旧结果里无对应 → 误判（STEPS-01 修复）。
    """
    plan_json = f"output/state/{slug}_qa_plan.json"
    results_json = f"output/state/{slug}_qa_results.json"
    report_json = f"output/state/{slug}_qa_report.json"
    sid = f"3.5.rem{attempt}"
    return [
        {"id": f"{sid}.remediation", "phase": "3.5", "kind": "subagent", "status": "pending",
         "task_file": _write_task(slug, f"{sid}.remediation",
                                  _task_phase35_remediation(slug, date, attempt)),
         "output": f"output/wechat_articles/*/{slug}_*_{date}.md"},
        {"id": f"{sid}.reextract", "phase": "3.5", "kind": "code", "status": "pending",
         "cmd": f"python script-verifier/verifier.py extract __ARTICLE__ -o {plan_json}",
         "output": plan_json},
        {"id": f"{sid}.research", "phase": "3.5", "kind": "subagent", "status": "pending",
         "task_file": _write_task(slug, f"{sid}.research",
                                  _task_phase35_search(slug, date).replace(
                                      "Phase 3.5 子 agent 任务：QA 搜索取证",
                                      f"Phase 3.5 子 agent 任务：QA 重新取证（修复第 {attempt} 轮）")),
         "output": results_json},
        {"id": f"{sid}.rejudge", "phase": "3.5", "kind": "code", "status": "pending",
         "cmd": f"python script-verifier/verifier.py judge {plan_json} --results {results_json} -o {report_json}",
         "output": report_json, "is_judge": True},
    ]
