## 前置校验（Pre-flight Check）

**执行任何阶段前，必须首先验证所有工具和文件可用。**

### 工具可用性检查

```
□ web_search     - 网络搜索（Brave API）
□ web_fetch      - 网页内容提取
□ delegate_task - 子Agent启动（runtime="subagent"）
□ subagents      - 子Agent管理（list/steer/kill）
□ read           - 文件读取
□ write          - 文件写入
□ edit           - 文件编辑
□ exec           - 脚本执行（Python/Powershell）
□ browser        - 浏览器控制（PDF生成、网页截图）
□ pdf            - PDF分析
□ message        - 消息发送（Discord）
□ image          - 图片分析
□ cron           - 定时任务
□ tts            - 文本转语音
```

**任一工具不可用 → 立即通知用户，等待修复后再启动。**

### 文件检查

```
□ scripts/computation/ 下所有Python脚本存在且可执行
□ detectors/ 下所有检测器存在
□ templates/ 下所有模板存在
□ output/ 目录可写
□ config.yaml 存在且格式正确
□ SKILL.md 本身可读
```

### 脚本测试

执行以下命令验证计算脚本可用：
```bash
python scripts/computation/math/basic.py --op add --a 1 --b 2
python scripts/computation/finance/wacc.py --equity_value 800 --debt_value 200 --cost_of_equity 0.12 --cost_of_debt 0.05 --tax_rate 0.25
```

**预期输出：** JSON格式，包含result/audit字段
**如果失败：** 检查Python环境和依赖，通知用户

### 编排系统检查

```
░ scripts/orchestration/state_manager.py 存在且可导入
░ scripts/orchestration/executor.py 存在且可导入
░ output/godtier-research/ 目录可写
░ output/godtier-research/states/ 目录可写（状态文件）
```

测试编排器：
```python
from scripts.orchestration.executor import GodtierExecutor
e = GodtierExecutor("test")
plan = e.phase0_analyze("test")
assert plan["topic"] == "test"
print("OK")
```

**如果失败：** 检查Python路径和模块导入，通知用户

---

