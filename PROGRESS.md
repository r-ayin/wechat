# wechat — 进度追踪

> 最后更新：2026-06-26

## 状态
🟢 活跃生产 — 管线运行中

## 当前里程碑
15篇微信长文已产出（11 hot + 4 evergreen），管线 v2.2 双模式就位

## 已完成
- [x] 项目从 douyin/ 拆分独立
- [x] godtier-deep-research 深度研究引擎集成
- [x] persona 人格三件套（SOUL+STYLE+PERSONA）全量注入管线
- [x] QA 四步门禁（搜证→逻辑审查→L4验证→迭代修复）
- [x] 双模式入口（🚀自动 / 🎯手动 Dankoe 采访）
- [x] 15 篇微信长文产出（11 hot + 4 evergreen）
- [x] 对标账号数据库建立
- [x] 热点扫描器 hot-scanner.py（43关键词×五支柱）
- [x] 常青选题池 + 热点监控
- [x] 2026-06-26: hot-020 全职儿女、老鼠人、烂尾娃——三个新词背后，是一代人的习得性无助 (evergreen)
- [x] 2026-06-26: 全量管线审计修复 — pipeline-gate.sh v1.1（FALSIFIED正则/摘要/严格topic/DATE）、L4验证器（中文数字/噪声过滤/重试计数）、godtier引擎（skill_dir/Pearson/GBM/DCF校验/scipy回退/sensitivity）、文档一致性、数据修正
- [x] 2026-06-26: 统一编排入口 — scripts/pipeline.py 确定性引擎 + steps.py 步骤物化器 + wechat-pipeline SKILL 薄入口（agent-loop，从任意点恢复，门禁代码强制，每步子 agent 隔离，主上下文不持内容，可移植 WorkBuddy）；gate 加 WECHAT_MIN_BYTES 可配置 + draft 档；gaokao 文章加 slug 前缀

## 当前任务
管线日常运营：选题 → 研究 → 重写 → QA → 输出

## 待办
- [ ] 对标账号 T1-T3 定期更新
- [ ] 选题池 UCB 信号优化
- [ ] persona 风格进化周期（累积≥5条发布反馈后触发）

## 阻塞项
无
