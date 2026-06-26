# 鲁班打磨评估报告 (2026-06-15)

## 结论摘要

- **过尺总分：** 53/107（打磨前基线）
- **最大短板：** description 为空 + 模型名硬编码 + 未曾在当前环境完整跑通
- **推荐方向：** 方案B — 精雕，打「可信度」差异化牌

## 7个同类对标 (访行)

| 项目 | URL | ⭐ | 定位 |
|------|-----|----|------|
| deep-financial-research | github.com/Lunatic16/deep-financial-research | 3 | MCP接入实时行情的财经研究Skill |
| FoundationalResearch/deepdive | github.com/FoundationalResearch/deepdive | 0 | 6-stage DAG pipeline深度分析 |
| ClarityFinance | github.com/cooragent/ClarityFinance | 58 | 6 Agent多维金融分析系统 |
| MoneyAtlas | github.com/ElmatadorZ/MoneyAtlas-ClaudeSkill-Agent | 43 | 3步思维管线+四维推理框架 |
| super-hedge-fund-skill | github.com/StanleyChanH/super-hedge-fund-skill | 4 | 8 Agent对冲基金分析 |
| standardhuman deep-research | github.com/standardhuman/deep-research-skill | 20 | 7阶段+GoT研究系统 |
| tonyazhuuki deep-research | github.com/tonyazhuuki/deep-research-skill | 19 | 3-Cycle多Agent对抗研究 |

## 关键差距

- 脚本计算强制层是最大差异点（所有竞品依赖LLM纯文字推理）
- 三层幻觉检测是结构性优势（竞品均缺失）
- 安装摩擦高于同类（npx一键安装 vs 手动配模型）
- 暂无快速体验路径

## 推荐的第一轮改动优先级

1. 修frontmatter ✅（已做）
2. 加模型配置说明 ✅（已做）
3. 加Hermes runtime迁移指南 ✅（已做）
4. 加快速体验模式（5分钟出结果）
5. 加对比表 vs 同类
