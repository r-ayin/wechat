# Hermes Runtime Migration Guide

本 Skill 原基于 OpenClaw runtime，使用以下原语。迁移到 Hermes 时需替换：

## sessions_spawn → delegate_task

```python
# OpenClaw 模式（原）
sessions_spawn(model="qwen3.5-plus", task="采集数据...")

# Hermes 模式
delegate_task(goal="采集数据...", context="...", toolsets=["web", "terminal"])
```

## subagents → delegate_task (batch mode)

```python
# OpenClaw 模式
subagents(list=["Agent1 prompt", "Agent2 prompt"])

# Hermes 模式
delegate_task(tasks=[
    {"goal": "Agent1任务", "toolsets": ["web"]},
    {"goal": "Agent2任务", "toolsets": ["web"]},
])
```

## 模型名映射

| 原模型名 | 在当前环境的替代方案 |
|----------|-------------------|
| glm-5 | deepseek-v4-pro (主模型) |
| qwen3.5-plus | deepseek-v4-flash (轻量) |
| kimi-k2.5 | deepseek-v4-pro (主模型) |
| hunter-alpha | deepseek-v4-pro (撰写模型) |
| ollama/qwen3.5-opus-distilled | 如无本地Ollama，用flash替代 |

## 修改方式

在 `config.yaml` 中找到 `models` 段，将 `primary` 改为 `inherit`（沿用当前模型），或指定具体模型名。
