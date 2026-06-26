# wechat — 质量门禁

## 🔴 CRITICAL（不通过则不得产出）

- [ ] **统一编排入口** — 管线经 `scripts/pipeline.py` agent-loop 驱动，主上下文不手动推进阶段
- [ ] **主上下文只持 step 元数据** — task_file 内容/子 agent 产出/文章体不得读入主上下文
- [ ] **长文通过 QA 四步门禁** — 搜证 + 逻辑一致性审查 + L4 防幻觉验证 + 迭代修复
- [ ] **逻辑一致性审查通过** — 不能出现"结构问题→个体方案"矛盾
- [ ] FALSIFIED = 0（长文级别）
- [ ] SOUL+STYLE+PERSONA 三件套已注入
- [ ] 反AI特征 ≥ 7/10
- [ ] 深度研究数据可追溯到信源
- [ ] PROGRESS.md 已更新
- [ ] 无硬编码密钥/令牌

## 🟡 IMPORTANT（不通过需注释原因）

- [ ] 任何事实性修改前先 WebSearch — 搜证先于动笔
- [ ] 竞争格局声明须有可验证信源
- [ ] 内容发布前有人工审核环节
- [ ] 热点数据有去重机制
- [ ] 人格盲测"这像你写的" > 70%
- [ ] **风格指纹 advisory** — `style_fingerprint.py` 句长/括号/破折号密度对照 STYLE.md 基线（gate verify 3 自动跑，初值告警不阻断）
- [ ] **结尾反模式 advisory** — `ending_detector.py` 检测"结构问题→个体方案"矛盾与简单答案
- [ ] **逻辑一致性代码化 advisory** — `structural_consistency_checker.py` 论点维度 vs 结尾方案维度比对
- [ ] **写作前 outline** — Phase 3 `3.outline` 产 section-level 大纲（节数≥5/总字数/论点齐全）再写

## 🟢 NICE（尽量满足）

- [ ] 内容发布后有效果数据回传（`pipeline.py tool feedback_collector ingest ...`）
- [ ] 选题到发布的端到端耗时被记录（`pipeline.py tool metrics_panel`）
- [ ] 竞品分析定期更新（每月至少一次，`competitor_analyzer.py` 产出确定性 metrics）
- [ ] QA 报告归档保存
- [ ] 发布反馈驱动 STYLE.md 进化（`style_evolution.py evolve`，PD-01）
- [ ] 跨文章 persona drift 监控（`persona_drift.py`，PD-02）
- [ ] 预测性选题（`predictive_scanner.py`，HS-04）
- [ ] 研究缓存/知识沉淀（`research_cache.py` / `knowledge_base.py`，A2/A4）
- [ ] 多平台派生（`multi_platform.py`，A3）
