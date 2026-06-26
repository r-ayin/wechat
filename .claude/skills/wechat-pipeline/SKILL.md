---
name: wechat-pipeline
description: 微信公众号长文管线 — 统一编排入口。通过 scripts/pipeline.py 确定性引擎驱动六阶段（0竞品→1简报→2godtier→3persona→3.5QA→4输出），agent-loop 严格执行，门禁代码强制，每步子 agent 隔离，主上下文不持内容。
triggers:
  - 跑管线
  - 开始写
  - 做一期关于
  - 从Phase
  - 继续管线
---

# WeChat Pipeline — 统一编排入口（agent-loop）

> 本 Skill 是**薄入口**：只描述调用契约。阶段逻辑、门禁、prompt 全部在
> `scripts/pipeline.py` + `scripts/steps.py`（确定性代码）里，不依赖本 LLM 的理解能力。
> 任何 agent（Claude Code / WorkBuddy / 其他）按下方循环调用即可。

## 铁律

1. **统一入口** — 所有管线推进经 `python scripts/pipeline.py`，**禁止**主上下文手动决定阶段、手动跑门禁、手动写阶段产出。
2. **主上下文只持 step 元数据** — `id` / `kind` / `cmd` / `task_file` / `output` + pass/fail。**禁止**把 `task_file` 内容、子 agent 产出、persona/analysis 文章体读入主上下文。
3. **门禁是代码** — pass/fail 由 `pipeline-gate.sh` exit code 决定，不靠 LLM 判断。gate 失败即停。
4. **每步子 agent 隔离** — `kind=subagent` 的步骤派发隔离子 agent 执行（子 agent 读 `task_file` + 磁盘输入，写 `output` 文件，不回传内容）。
5. **代码子步直跑** — `kind=gate_*` / `kind=code` 的步骤主 agent 直接 `bash cmd`（不占 LLM 上下文，无需子 agent）。

## 调用契约（agent-loop）

```
1. 初始化/恢复：
   python scripts/pipeline.py init <topic> [--slug S] [--mode auto|manual] [--brief P] [--draft] [--from <phase>] [--date D]

2. 循环（直到 done）：
   STEP = $(python scripts/pipeline.py next <topic> [--date D])     # JSON

   若 STEP.done == true：
     若 STEP.halted == true → 报告失败步骤 STEP.failed_step，结束
     否则 → 管线完成，结束

   若 STEP.kind == "gate_check" 或 "gate_verify" 或 "code"：
     bash "$STEP.cmd"        # 主 agent 直接跑（cmd 已含 WECHAT_MIN_BYTES 前缀，draft 档自动生效）
     按退出码判定（CONTRACT-01：verifier.py judge 在 PASS_WITH_CAVEATS 时 exit 2，非失败）：
       exit 0 或 2 → completed（exit 2 时 --note "PASS_WITH_CAVEATS"）
       exit 1（或其它非 0/2）→ failed
     python scripts/pipeline.py mark <topic> <STEP.step_id> <completed|failed> [--note "..."]

   若 STEP.kind == "subagent"：
     派发一个隔离子 agent，goal = "读取 <STEP.task_file> 并执行，产出写入 <STEP.output>"
     （子 agent 完成后不把产出内容读回主上下文）
     python scripts/pipeline.py mark <topic> <STEP.step_id> <completed|failed> [--note "..."]
```

### 模式路由（决定 init 参数）
- 🚀 自动模式（`做一期关于XX` / `分析XX`）→ `init <topic> --mode auto`
- 🎯 手动模式（`聊一下XX` / `选题咨询`）→ 先 Dankoe 八问（`prompts/dankoe-interview.md`）产出 brief，再 `init <topic> --mode manual --brief <brief路径>`
- 从中途恢复（`从Phase 3继续`）→ `init <topic> --from 3`（自动跳过已通过门禁的阶段）

### draft 档
- `--draft`：min_bytes 降至 12000（≈4000 字），供草稿流通。pipeline.py 会把 `WECHAT_MIN_BYTES` 自动注入到每个 gate/code 步骤的 cmd 前缀，无需手动设 env。
- 默认严格 45000 bytes（≈15000 汉字，CLAUDE.md 标准）。`--from N` 会传递式校验前置 phase 已通过 verify（draft 档对短文前置也放宽）。

### 优化工具（统一入口）
`python scripts/pipeline.py tool <name> [args]` 透传到 `scripts/<name>.py`：
- `style_fingerprint <article>` — 风格指纹（句长/括号/破折号 vs STYLE.md 基线）
- `competitor_analyzer <article>` — 竞品结构 NLP 五维确定性 metrics
- `title_scorer --titles '[...]'` — 标题候选评分排序
- `ending_detector <article>` — 反模式结尾检测
- `structural_consistency_checker <article>` — 逻辑一致性代码化
- `style_evolution record|evolve` — 发布反馈→STYLE.md 进化建议（PD-01）
- `persona_drift <dir>` — 跨文章人格漂移检测（PD-02）
- `predictive_scanner calendar|rising` — 预测性选题（HS-04）
- `feedback_collector ingest|report` — post-publish 反馈回传（A1）
- `research_cache get|put|diff` — 研究缓存增量（A2）
- `knowledge_base add|query|stats` — 知识沉淀（A4）
- `multi_platform <article> --platform douyin|xiaohongshu` — 多平台派生（A3）
- `metrics_panel [topic]` — 可观测性面板（A5）

gate verify 3 会自动跑 style_fingerprint/ending_detector/structural_consistency_checker 作为 advisory（只告警不阻断）。

## 阶段速览（细节在 steps.py，无需主 LLM 记忆）

| Phase | kind | 产出 | 门禁 |
|-------|------|------|------|
| 0 竞品蒸馏 | subagent | `{slug}_competitor-style_{date}.md` | ≥2000B + 五维 + X/10 |
| 1 研究简报 | subagent | `{slug}_brief_{date}.md` | ≥1500B |
| 2 godtier 13层 | subagent | `{slug}_analysis_{date}.md` | ≥min_bytes + ≥10层 |
| 3 persona 重写 | subagent | `wechat_articles/*/{slug}_*_{date}.md` | ≥min_bytes + persona标记 + 摘要 + 标题8-35字 |
| 3.5 QA | code+subagent 混合 | `{slug}_qa_report.json` | FALSIFIED=0 |
| 4 输出 | subagent | PROGRESS.md + git | verify 4 no-op |

Phase 3.5 细节：`extract`(code) → `search`(subagent WebSearch) → `judge`(code) → 若 FALSIFIED>0 自动插入 `remediation`(subagent) → `re-extract` → `re-search`(subagent 重新取证) → `re-judge` 循环，最多 3 轮，耗尽则停。re-search 必须有，否则新 claim_id 复用旧搜索结果会误判。

## 运行时适配（可移植性）

本入口运行时中立。子 agent 派发是唯一运行时接缝：
- **Claude Code**：用 Agent 工具，`prompt="读取 <task_file> 执行，产出写入 <output>"`。
- **WorkBuddy**：用其多 Agent / delegate 机制（兼容 OpenClaw Skills），同样传入 `task_file` 路径与 `output` 路径。
- **其他运行时**：任何能"派发隔离上下文子任务 + 跑 bash"的运行时均可；`pipeline.py` / `steps.py` / `pipeline-gate.sh` / `script-verifier/` / `computation/` 纯 Python/bash，零运行时依赖。

`scripts/pipeline.py` 不 import 任何 Claude/Agent 运行时，输出的 step 元数据运行时无关。

## 严禁
- 主上下文手动推进阶段、手动跑门禁、手动写阶段产出
- 把 task_file 内容或子 agent 产出读入主上下文
- 跳过 gate 失败继续推进
- QA 未通过（FALSIFIED>0）就进 Phase 4
