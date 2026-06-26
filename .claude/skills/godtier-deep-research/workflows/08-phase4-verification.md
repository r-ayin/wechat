- 总字数：10000-15000字

---

### 阶段4：质量验证与幻觉检测（10分钟）

**编排组件**：`executor.phase4_verify()` → `executor.phase4_complete()`

**模型：hunter-alpha**（继承父session）

**执行步骤**：
```python
# 1. 获取验证配置
verify_config = executor.phase4_verify()
# verify_config["detectors"] = 检测器路径列表
# verify_config["article_path"] = 文章路径
# verify_config["report_path"] = 报告输出路径

# 2. 运行三层幻觉检测（见下方检查清单）
# 主Agent逐项检查 + 运行Python检测器

# 3. 完成（自动验证 overall=PASS）
executor.phase4_complete("analysis_dir/hallucination_report.json")
```

**强制检查清单（逐项打勾）**：

```
【Layer 1: 数字级验证】
□ 文章中所有精确数字是否有来源URL？
□ 所有计算结果是否有脚本执行记录？
□ 是否存在无来源的精确数字？（如"增长了37.2%"但无来源）
□ 数字单位是否明确？
□ 时间范围是否明确？
□ 是否有超出合理范围的数字？（PE>200? 增长率>500%?）
□ 同一数字在不同段落是否一致？

【Layer 2: 逻辑级验证】
□ 每个因果推论是否有传导机制？
□ 是否存在相关≠因果的推论？
□ 是否存在幸存者偏差？
□ 是否存在确认偏差（只引用支持结论的证据）？
□ 每个核心结论是否有证伪条件？
□ 是否考虑了反面证据？

【Layer 3: 全文级验证】
□ 随机抽查10%的URL是否可访问？
□ 数字单位是否全文一致？
□ 时间范围是否全文一致？
□ 五模块结构是否完整？
□ 105个信源是否覆盖了主要类别？
□ 文章是否可独立理解（不依赖外部上下文）？
```

**输出幻觉检测报告**：
```json
{
  "hallucination_check": {
    "layer1": {
      "total_numbers": 0,
      "sourced": 0,
      "computed": 0,
      "cross_verified": 0,
      "flags": [],
      "status": "PASS"
    },
    "layer2": {
      "total_claims": 0,
      "causal_claims": 0,
      "falsifiable": 0,
      "flags": [],
      "status": "PASS"
    },
    "layer3": {
      "url_health": "90%",
      "consistency": "PASS",
      "falsifiability": "PASS",
      "flags": [],
      "status": "PASS"
    },
    "overall": "PASS"
  }
}
```

