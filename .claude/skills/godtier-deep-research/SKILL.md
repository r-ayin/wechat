---
name: godtier-deep-research
description: |-
  双模式深度研究系统（财经 + 通用热点）。13层分析架构 + 脚本计算强制层（所有数字由Python执行，消除LLM幻觉）+ 三层主动幻觉检测 + URL锚定信源。输出双格式（文章版+分析结构版），每份分析可验证、可溯源。支持 --mode finance（13层财经框架）和 --mode general（13层通用框架，适配任何热点话题）。
tags: [deep-research, finance, general-topics, hot-topics, analysis, hallucination-detection, dual-mode]
triggers:
  - 深度分析 [公司/行业/主题/热点]
  - 做[公司名/事件名]的深度研究
  - 写一份关于[主题]的深度分析报告
  - 用13层框架分析[主题]
  - 分析[热点事件]的来龙去脉
  - 残差Alpha扫描[标的]
  - 评估[公司]的竞争格局
---

# GODTIER Deep Research — 双模式深度研究系统

> **finance** 模式：13层财经分析（L-1残差Alpha + WACC/DCF/蒙特卡洛 + 105+金融信源）
> **general** 模式：13层通用分析（盲点检测 + 利益相关者 + 三情景推演 + 全网信源）

使用13层分析架构（含L-1残差Alpha层）、105+顶级信源、脚本计算强制层和三层幻觉检测，生成具有认知穿透力的深度财经分析。每次输出**两版**：连贯叙事文章版 + 模块化分析结构版。

## ⚠️ 执行前须知

**模型配置：** 深度分析主笔使用 `deepseek-v4-pro`，数据采集使用 `deepseek-v4-flash`。如果当前环境模型名不同，在 `config.yaml` 中修改后执行。

**Runtime 适配：** 本 Skill 已适配 Hermes `delegate_task`。工作流文件中用 `delegate_task` 替代原 `sessions_spawn`。

## 文档结构

本文档已拆分为多个子文件：

| 文件 | 内容 | 说明 |
|------|------|------|
| [workflows/00-overview.md](workflows/00-overview.md) | 技能概述 + 13层分析框架 + 六维评价体系 | 先读这个 |
| [workflows/01-principles.md](workflows/01-principles.md) | 核心原则（URL锚定/脚本计算/幻觉检测/前提挑战/叙事标签） | 强制执行 |
| [workflows/02-preflight.md](workflows/02-preflight.md) | 前置校验（工具+文件+脚本检查） | 执行前必读 |
| [workflows/03-architecture.md](workflows/03-architecture.md) | 三层执行架构（规划/执行/验证+数据流转+Agent守护） | 理解执行模型 |
| [workflows/04-phase0-planning.md](workflows/04-phase0-planning.md) | 阶段0：需求分析与主题解构 | 规划模板在这里 |
| [workflows/05-phase1-collection.md](workflows/05-phase1-collection.md) | 阶段1：多维度数据采集（8个Agent完整prompt） | 最大的文件 |
| [workflows/06-phase2-analysis.md](workflows/06-phase2-analysis.md) | 阶段2：深度分析与洞察生成（7个Agent完整prompt） | 核心分析层 |
| [workflows/07-phase3-writing.md](workflows/07-phase3-writing.md) | 阶段3：文章撰写与整合（13层文章模板 + 双输出格式） | 输出模板 |
| [workflows/08-phase4-verification.md](workflows/08-phase4-verification.md) | 阶段4：质量验证与幻觉检测 | 质量关卡 |
| [workflows/09-phase5-output.md](workflows/09-phase5-output.md) | 阶段5：输出与存档 | 最终交付 |
| [workflows/10-reliability.md](workflows/10-reliability.md) | 可靠性保障（Agent监控/质量控制/自动修复） | 容错机制 |
| [references/premise-challenge-framework.md](references/premise-challenge-framework.md) | 前提挑战四问法 | 防止框架绑架和确认偏误 |

## 其他文件

- `config.yaml` - 模型配置、Agent参数、编排配置(v1.1)
- `templates/` - 文章模板
- `references/` - 参考资料（前提挑战框架、Hermes迁移指南、同类对比）
- `scripts/orchestration/executor.py` - 编排执行器(主Agent按步骤调用)
- `scripts/orchestration/state_manager.py` - 状态管理(checkpoint/Agent追踪/阶段门)
- `scripts/computation/` - Python计算脚本(22个)
  - `math/` - basic, percentage, ratio, sorting, ranking, filter
  - `stats/` - descriptive, correlation, regression, timeseries
  - `finance/` - wacc, dcf, multiples, scenario, monte_carlo, stress_test
  - `data/` - fetcher, validator, cleaner, cross_check
  - `utils/` - hash_input, format_output, audit_log
- `detectors/` - 三层幻觉检测器
  - `number_hallucination.py` - Layer 1: 数字级检测
  - `logic_hallucination.py` - Layer 2: 逻辑级检测
  - `source_hallucination.py` - Layer 3: 信源级+全文检测
  - `run_all_detectors.py` - 运行全部三层检测

## 快速导航

**第一次使用？** 按这个顺序读：
1. `00-overview.md` - 了解是什么
2. `03-architecture.md` - 了解怎么跑
3. `04-phase0-planning.md` - 学会规划

**准备执行？** 检查清单：
1. `02-preflight.md` - 验证环境
2. `01-principles.md` - 记住铁律
3. `05-phase1-collection.md` ~ `10-reliability.md` - 按阶段执行

---

## 增强特性

以下特性是在原版 13 层架构基础上增加的，贯穿所有工作流：

### 前提挑战（防框架绑架）

进入深度分析前，先用数据回答四个问题：
1. **分类挑战**：当前事件的通用叙事框架成立吗？金额/结构/对价形式是否与常规一致？如果不一致，重新定义问题。
2. **唯一性挑战**：为什么选这个标的而不是其他？列出不选的理由。
3. **反方假设**：假设这个决策是错的，最合理的反对意见是什么？列 3 条，有证据支撑。
4. **叙事标签检测**：所有「称号」「XX n 杰」「榜单」等概念必须标注来源和验证状态。

> 最致命的错误不是分析错了，而是分析了一个错误定义的问题。

### 双输出格式

每次深度分析完成后，从同一份内容生成两个版本：
- **文章版**：连贯叙事语言，适合阅读传播。13层全结构，8000-15000字
- **分析结构版**：模块化结构化呈现，适合快速查阅和对照。同一份内容，不同组织方式

两个版本都经过幻觉检测，共用同一套附录（数据来源、计算审计、检测报告）。

### 反方分析

L6-L7（对手盘博弈）阶段强制包含反方分析子任务，与正向分析并行执行，不得为"圆回来"而弱化反方论证。

### 叙事标签标注

所有称号类概念在首次出现时加脚注 `[N]` 标出来源，文末注明来源和验证状态。禁止将媒体创造的标签作为行业共识引用。

---

## 同类对比

| 项目 | Stars | 定位 | 脚本计算 | 幻觉检测 | 双输出 | 信源追溯 |
|------|:----:|------|:--------:|:--------:|:------:|:--------:|
| **本技能** | — | 13层架构+脚本强制+三层检测+双输出 | ✅ 强制 | ✅ 三层 | ✅ 文章+结构 | ✅ URL锚定 |
| [ClarityFinance](https://github.com/cooragent/ClarityFinance) | ⭐58 | 6 Agent多维金融分析 | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
| [MoneyAtlas](https://github.com/ElmatadorZ/MoneyAtlas-ClaudeSkill-Agent) | ⭐43 | 3步思维管线+四维推理 | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
| [standardhuman deep-research](https://github.com/standardhuman/deep-research-skill) | ⭐20 | 7阶段+GoT研究系统 | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
| [tonyazhuuki deep-research](https://github.com/tonyazhuuki/deep-research-skill) | ⭐19 | 3-Cycle多Agent对抗 | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
| [super-hedge-fund-skill](https://github.com/StanleyChanH/super-hedge-fund-skill) | ⭐4 | 8 Agent对冲基金分析 | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
| [deep-financial-research](https://github.com/Lunatic16/deep-financial-research) | ⭐3 | MCP接入实时行情 | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
| [FoundationalResearch/deepdive](https://github.com/FoundationalResearch/deepdive) | ⭐0 | 6-stage DAG pipeline | ❌ LLM纯推理 | ❌ 无 | ❌ | ⚠️ 无 |
