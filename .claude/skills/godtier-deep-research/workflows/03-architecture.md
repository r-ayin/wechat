## 三层执行架构

### 架构概述

```
┌────────────────────────────────────────────────────────────┐
│ 第一层：规划层（主Agent）                                      │
│ ├── 需求分析 + 主题解构                                       │
│ ├── Agent方案设计 + 模型选择                                  │
│ └── 输出 research_plan.json → 用户审批                       │
├────────────────────────────────────────────────────────────┤
│ 第二层：执行层（多Agent并行）                                  │
│ ├── 数据采集层（5-8个Agent，qwen3.5-plus）                    │
│ ├── 深度分析层（5-7个Agent，glm-5 + kimi-k2.5）               │
│ └── 终局推演（1个Agent，glm-5）                               │
├────────────────────────────────────────────────────────────┤
│ 第三层：验证层（主Agent + 检测器）                              │
│ ├── 文章撰写与整合（hunter-alpha）                            │
│ ├── 三层幻觉检测（hunter-alpha + Python检测器）               │
│ └── 输出生成 + 存档 + 投递                                    │
└────────────────────────────────────────────────────────────┘
```

### 编排系统

**核心组件**：
- `scripts/orchestration/executor.py` — 编排执行器，主Agent按步骤调用
- `scripts/orchestration/state_manager.py` — 状态管理，断点续传 + Agent追踪 + 阶段门验证

**执行模式**：主Agent自身就是编排器。不是运行一个脚本全自动执行，而是主Agent读取executor.py的指引，分步调用delegate_task，管理状态，处理异常。

### 数据流转

```
阶段0（规划） → research_plan.json → 用户审批
     ↓
阶段1（采集） → 5-8个JSON数据文件 → analysis_dir/phase1_*.json
     ↓  ← 门验证：至少3个Agent完成
阶段2（分析） → 5-7个MD分析报告 → analysis_dir/phase2_*.md
     ↓  ← 门验证：至少3个Agent完成
阶段3（撰写） → 读取所有phase1+phase2输出 → article.md
     ↓  ← 门验证：文章≥5KB
阶段4（验证） → 运行检测器 → hallucination_report.json
     ↓  ← 门验证：overall=PASS
阶段5（输出） → final_article.md + HTML + PDF → Discord投递
```

### 并行 vs 串行 规则（强制执行）

**阶段内并行**：
- 阶段1的所有采集Agent必须同时启动（一次性调用所有delegate_task）
- 阶段2的所有分析Agent必须同时启动
- 绝对不要在for循环里串行启动Agent！

**阶段间串行**：
- 阶段1全部完成后才能启动阶段2
- 阶段2全部完成后才能开始阶段3
- 阶段3文章完成后才能进入阶段4

**阶段门（Gate）**：
- 每个阶段结束时执行verify_phase_gate()
- 门验证失败 → 重试失败的Agent或降低要求 → 重新验证
- 门验证通过 → 调用complete_phase() → 进入下一阶段

### 执行流程（主Agent操作步骤）

```python
# 导入编排器
from scripts.orchestration.executor import GodtierExecutor

# 阶段0：规划
executor = GodtierExecutor("研究主题", mode="full")
plan = executor.phase0_analyze("用户的原始需求")
# → 展示plan给用户，等待审批
executor.phase0_approve()  # 用户批准后

# 阶段1：并行采集
agent_configs = executor.phase1_collect()
for config in agent_configs:
    delegate_task(goal=config["prompt"], toolsets=["web"])
    # ↑ 所有delegate_task调用必须在同一个响应中完成（不要for循环等！）

# 每5分钟检查
status = executor.phase1_check()
# → status["overdue"] 警告超时Agent
# → status["critical"] kill + retry
# → status["all_done"] 可以进入阶段2

executor.phase1_complete()  # 门验证 + 完成

# 阶段2：并行分析（同阶段1模式）
agent_configs = executor.phase2_analyze()
for config in agent_configs:
    delegate_task(goal=config["prompt"], toolsets=["web"])

status = executor.phase2_check()
executor.phase2_complete()

# 阶段3：文章撰写（主Agent自己执行）
inputs = executor.phase3_get_inputs()
executor.phase3_start()
# → 读取所有phase1+phase2输出
# → 按照07-phase3-writing.md的模板撰写文章
# → 写入 analysis_dir/article.md
executor.phase3_complete("path/to/article.md")

# 阶段4：质量验证
verify_config = executor.phase4_verify()
# → 运行三层幻觉检测
# → 生成 hallucination_report.json
executor.phase4_complete("path/to/hallucination_report.json")

# 阶段5：输出
output_config = executor.phase5_output()
# → 生成HTML/PDF
# → 发送到Discord
executor.phase5_complete()
```

### 时间预算

| 阶段 | 时间 | 执行者 | 说明 |
|------|------|--------|------|
| 规划 | 5-10min | 主Agent | 需求分析+用户审批 |
| 数据采集 | 30-40min | 5-8 Agent并行 | web_search+web_fetch |
| 深度分析 | 25-30min | 5-7 Agent并行 | 深度推理+脚本计算 |
| 文章撰写 | 20-30min | 主Agent | 读取所有输出+整合 |
| 质量验证 | 10-15min | 主Agent+检测器 | 幻觉检测+URL抽查 |
| 输出存档 | 5min | 主Agent | 格式转换+投递 |
| **总计** | **~2h** | | full模式 |

### 模式选择

| 模式 | 采集Agent | 分析Agent | 预计耗时 | 适用场景 |
|------|----------|----------|---------|----------|
| full | 8个 | 7个 | ~2小时 | 完整13层分析 |
| quick | 4个 | 3个 | ~30分钟 | L-1+L0+L1+L10精简版 |
| risk | 5个 | 4个 | ~1小时 | L-1+L0+L6+L7+L10风险评估 |
| compete | 6个 | 5个 | ~1小时 | L3+L4+L5+L6竞争分析 |

### 工具依赖

| 阶段 | 必需工具 | 可选工具 |
|------|---------|---------|
| 规划 | read, write | - |
| 采集 | web_search, web_fetch, delegate_task | browser, pdf |
| 分析 | delegate_task, exec, read/write | browser |
| 撰写 | read, write | browser(PDF) |
| 验证 | exec, read, web_fetch | - |
| 输出 | write, message, pdf | tts |

---
