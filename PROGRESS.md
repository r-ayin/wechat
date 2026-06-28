# wechat — 进度追踪

> 最后更新：2026-06-28

## 状态
🟢 活跃生产 — 管线运行中

## 当前里程碑
17篇微信长文已产出（13 hot + 4 evergreen），管线 v2.2 双模式就位

## 已完成
- [x] 项目从 douyin/ 拆分独立
- [x] godtier-deep-research 深度研究引擎集成
- [x] persona 人格三件套（SOUL+STYLE+PERSONA）全量注入管线
- [x] QA 四步门禁（搜证→逻辑审查→L4验证→迭代修复）
- [x] 双模式入口（🚀自动 / 🎯手动 Dankoe 采访）
- [x] 17 篇微信长文产出（13 hot + 4 evergreen）
- [x] 对标账号数据库建立
- [x] 热点扫描器 hot-scanner.py（43关键词×五支柱）
- [x] 常青选题池 + 热点监控
- [x] 2026-06-26: hot-020 全职儿女、老鼠人、烂尾娃——三个新词背后，是一代人的习得性无助 (evergreen)
- [x] 2026-06-26: 全量管线审计修复 — pipeline-gate.sh v1.1（FALSIFIED正则/摘要/严格topic/DATE）、L4验证器（中文数字/噪声过滤/重试计数）、godtier引擎（skill_dir/Pearson/GBM/DCF校验/scipy回退/sensitivity）、文档一致性、数据修正
- [x] 2026-06-26: 统一编排入口 — scripts/pipeline.py 确定性引擎 + steps.py 步骤物化器 + wechat-pipeline SKILL 薄入口（agent-loop，从任意点恢复，门禁代码强制，每步子 agent 隔离，主上下文不持内容，可移植 WorkBuddy）；gate 加 WECHAT_MIN_BYTES 可配置 + draft 档；gaokao 文章加 slug 前缀
- [x] 2026-06-27: 全量优化实现 — 13 个新工具脚本（style_fingerprint/competitor_analyzer/title_scorer/ending_detector/structural_consistency/style_evolution/persona_drift/predictive_scanner/feedback_collector/research_cache/knowledge_base/multi_platform/metrics_panel）；Phase 3 加 outline 步骤(W-01)；gate verify 3 加风格/结尾/逻辑 advisory(W-02/W-06/QAH-03)；fact_checker 三级信源可信度+交叉验证+时效(QAH-02/04/05)；claim_extractor data_year；hot-scanner 查询去重(HS-06)；pipeline.py tool 子命令统一包装
- [x] 2026-06-27: gaokao-score-inequality 长文产出 — 省籍彩票：你的高考从出生那天就被判了分（hot）
- [x] 2026-06-27: marriage-unbundling 长文产出 — 婚姻没有被抛弃，是被拆成了零件（hot，45688 bytes，QA FALSIFIED=0）
- [x] 2026-06-28: 今日选题更新 — WebSearch(百度真实抓取)→consume→注入 evergreen-pool，新增 6 条可溯源热点选题 hot-032~037（47→53），覆盖五支柱：①高考志愿985/211反转 ②1270万毕业生43.9%offer率学历倒挂 ③最低工资31省破2000上海2740 ④AI标注工4分钱一个框AI富士康 ⑤房价跌房租涨租客占收入65% ⑥人均ADHD赛博诊断。scan-results.json 同步替换(6-23旧版备份 scan-results-2026-06-23.bak.json)
- [x] 2026-06-28: hot-scanner.py consume 双缺陷修复(HS-009) — ①`_extract_title` 改为 query 优先(旧实现对无换行长摘要截前80字致标题碎片化)；②新增 `_match_pillar` 替换"首个token命中即break"内联匹配：query+摘要合并文本、按命中token字符长度计分(长特定token如ADHD/最低工资权重高、争议/收入等短噪声token权重低)、关键词组全命中×2加权、token小写比对(修 ADHD/AI 大小写失配)。6条今日选题回归全归类正确(scan/event-scan/report 不受影响)
- [x] 2026-06-28: hot-033 1270万毕业生，43.9%拿到offer：学历倒挂时代，文凭为什么失灵了 (hot)
- [x] 2026-06-28: hot-034 最低工资2740元：这条线下面，是谁在替整个系统兜底 (hot)
- [x] 2026-06-28: hot-035 AI富士康里的标注工：4分钱一个框，教会徒弟饿死师傅 (hot)

## 当前任务
管线日常运营：选题 → 研究 → 重写 → QA → 输出

## 待办
- [ ] 对标账号 T1-T3 定期更新
- [ ] 选题池 UCB 信号优化（`feedback_collector` 已就绪，待接入 hot-scanner 排序）
- [ ] persona 风格进化周期（`style_evolution` 已就绪，待累积≥5条发布反馈后跑 evolve）
- [ ] PD-04：STYLE.md 15维有效性 A/B 盲测，去冗余维度
- [ ] PD-07：STYLE.md 时段加权重新蒸馏（2021/2022-23/2024-26 权重 0.2/0.3/0.5）
- [ ] style_fingerprint 阈值用已有15篇回测校准后从 advisory 收紧为阻断

## 阻塞项
无
