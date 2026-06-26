## 可靠性保障

### Agent监控机制

**监控组件**：`scripts/orchestration/state_manager.py` 的 `ResearchState` 类自动追踪所有Agent状态。

**检查频率**：每5分钟调用一次 `executor.phase1_check()` 或 `executor.phase2_check()`

**检查返回值处理**：
```python
status = executor.phase1_check()

# 1. 处理严重超时（kill + retry）
for agent_name in status["critical"]:
    # subagents(action="kill", target=agent_name)  # Hermes: delegate_task handles lifecycle
    # 重试：重新delegate_task
    # 如果重试次数 >= 1，标记失败，用已有数据继续

# 2. 处理一般超时（警告）
for agent_name in status["overdue"]:
    # 记录警告，但不干预
    pass

# 3. 检查是否全部完成
if status["all_done"]:
    executor.phase1_complete()  # 门验证 + 进入下一阶段
```

**超时规则**：
- 运行时间 > 预期 × 1.5 → `overdue` 列表（警告）
- 运行时间 > 预期 × 2.0 → `critical` 列表（kill + retry）
- 重试1次仍失败 → 标记 `failed`，用已有数据继续

**状态持久化**：
- 状态自动保存到 `output/godtier-research/states/{topic}_{date}.json`
- 同时保存到 `analysis_dir/checkpoint.json`
- 恢复时：`state = ResearchState.load(topic, date)` → 读取checkpoint → 继续执行

### 自动修复流程

```
Agent失败 → 检查错误类型 → 选择修复方案：
  ├─ 网络超时 → 重试（最多1次）
  ├─ 输出格式错误 → 修正prompt + 重试
  ├─ 模型错误 → 切换备用模型 + 重试
  └─ 未知错误 → 用已有数据继续 + 标记缺失
```

**模型切换策略**：
- 主模型失败 → `ollama/qwen3.5-opus-distilled`（本地兜底）
- 采集Agent失败 → 降低数据要求，用已采集的数据继续
- 分析Agent失败 → 检查是否有部分输出，有的话继续

### 阶段门验证（Gate Verification）

**每个阶段结束时强制执行**：

| 阶段 | 门条件 | 失败处理 |
|------|--------|----------|
| 阶段0 | research_plan.json 存在且有效 | 补充规划 |
| 阶段1 | ≥3个采集Agent完成 | 重试失败Agent或降低最低数 |
| 阶段2 | ≥3个分析Agent完成 | 重试失败Agent或降低最低数 |
| 阶段3 | article.md ≥ 5KB | 补充内容 |
| 阶段4 | hallucination_report.json overall=PASS | 修复幻觉后重新检测 |
| 阶段5 | final_article.md 存在 | 重新生成 |

**门验证代码**：
```python
passed, msg = state.verify_phase_gate("phase1_collection")
if not passed:
    # 门未通过，处理失败的Agent
    failed = [a for a in state.get_phase_agents() if a.status == "failed"]
    for agent in failed:
        if agent.retry(agent):  # 重试
            delegate_task(goal="重试失败Agent", toolsets=["web"])
        else:
            # 重试耗尽，用已有数据继续
            pass
    # 重新验证
    passed, msg = state.verify_phase_gate()
```

### 质量控制

**阶段间验证**：
- 阶段1→阶段2：检查数据采集是否覆盖主要类别（JSON文件数量和大小）
- 阶段2→阶段3：检查分析报告是否达到字数要求（每个MD文件≥1KB）
- 阶段3→阶段4：检查文章结构是否完整（有执行摘要+13层内容+附录）
- 阶段4→阶段5：检查幻觉检测是否全部PASS

**最终交付标准**：
- 六维评分总分 ≥ 70
- 幻觉检测 overall = PASS
- 文章字数 ≥ 8000
- 信源覆盖 ≥ 15个

### 断点续传

**自动保存点**：
- 每个Agent完成时
- 每个阶段完成时
- Agent失败时

**恢复流程**：
```python
# 从checkpoint恢复
from scripts.orchestration.state_manager import ResearchState

state = ResearchState.load("英伟达财报分析", "2026-03-13")
print(state.get_resume_instructions())
# 输出：
#   已完成: phase0_planning, phase1_collection
#   当前: phase2_analysis (3/5 completed, 1 failed)
#   需要: 重试 L4-L5信息博弈 Agent

# 重试失败的Agent
failed = [a for a in state.get_phase_agents() if a.status == "failed"]
```

### 监控配置（config.yaml）

```yaml
monitoring:
  check_interval: 5          # 分钟
  timeout_multiplier: 1.5    # overdue阈值
  critical_multiplier: 2.0   # kill阈值
  auto_retry: true
  max_retries: 1             # 每个Agent最多重试1次
  proactive_reporting: true
```

---
