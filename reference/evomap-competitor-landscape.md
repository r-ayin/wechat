# EvoMap 竞品全景 — Agent 自动经验收集与复用赛道

> **生成时间**：2026-06-19 | **调研方式**：多轮 WebSearch + 信源交叉验证
> **调研起因**：EvoMap 深度研究原文称"没有竞品"→ 用户质疑 → 实际存在大量同类工具
> **核心修正**：该赛道已拥挤，且真实 PMF 在**企业端**而非 A2A/2C

---

## 一、赛道定义的精确化

### ❌ 不是"技能商店"（我们不做比较的）

这些是 App Store 模式——人写技能上传卖，不是自动从行为中提取：

| 平台 | 公司 | 本质 |
|------|------|------|
| 虾小宝 JVS Claw | 阿里 | 技能市场驱动云消耗 |
| 扣子 + Find Skill | 字节 | 消费者+企业双轨 |
| SkillHub | 腾讯 | 微信生态技能分发 |
| 觅游 + xia345 | 美团 | 社区技能市场 |
| ClawHub / OpenClaw | 社区 | 最大开放技能注册中心 |

### ✅ "自动经验收集+复用"赛道（精确竞争范围）

核心特征：Agent 完成任务后，**自动**从行为轨迹中提取可复用的知识/技能/模式。

---

## 二、精确竞品地图

### 🥇 第一梯队：工程化最成熟

| 项目 | Hivemind | EverOS | Acontext |
|------|----------|--------|----------|
| **团队** | Activeloop (YC W25) | EverMind AI (盛大投资) | memodb-io |
| **定位** | 编码 Agent 持续学习层 | 自进化记忆层 | Agent 经验蒸馏管道 |
| **捕获方式** | 自动 Trace Capture → Skill Codification → SkillOpt 优化 → 传播 | 自动 Case 提取 → 聚类 → 蒸馏为 SOP | Capture → Task Extraction → Distillation → Markdown |
| **跨框架** | ✅ Claude/Codex/Cursor/OpenClaw/Hermes/pi | ✅ Claude/Codex/OpenClaw/Hermes/Cursor/Gemini CLI | ✅ OpenClaw 原生+跨平台 |
| **开源** | ✅ Apache 2.0 | ✅ Apache 2.0 | ✅ |
| **基准** | +19.1pts Claude, +24.8pts Codex, 25% 降本 | +234.8% 任务成功率 | — |
| **Stars** | 618 | — | 18.5k |
| **发布时间** | 2026 初 | 2026-04 (公测), 06-06 (1.0.0) | 2025-2026 |
| **核心差异** | SkillOpt 文本空间优化，YC 背书 | ACL 2026 双论文，本地优先 | 社区验证最强 |

### 🥈 第二梯队：有独特角度

| 项目 | Ultron (魔搭) | 飞书 aily SkillHub | PowerMem | skillrl |
|------|---------------|-------------------|----------|---------|
| **团队** | 阿里/魔搭社区 | 字节跳动/飞书 | 独立开发者 | 独立开发者 |
| **定位** | 群体智能基础设施 | 企业技能治理平台 | 持久记忆+蒸馏 | 编码 Agent 蒸馏 CLI |
| **核心机制** | 记忆自动蒸馏→结晶→再结晶 | 从飞书上下文自动提炼 Skill | 双层 Experience+Skill 蒸馏 | Distillation→Retrieval→Evolution |
| **跨框架** | ✅ OpenClaw/Nanobot/Hermes | ❌ 飞书生态 | ✅ MCP/HTTP/SDK | ✅ Claude/Cursor/Kiro/OpenClaw |
| **数据** | 2000 记忆+8 万外部技能 | 飞书企业数据源 | 87.79% LoCoMo 基准 | SQLite 向量索引 |
| **独特优势** | 阿里云生态，群体智能 | 大厂数据源，企业治理 | 遗忘曲线+混合检索 | 轻量 MCP 集成 |

### 🥉 学术界（追赶中，但可能很快工程化）

| 论文 | 核心贡献 | 会议 | 发布时间 |
|------|----------|------|---------|
| **SkillClaw** | 跨用户轨迹聚合→技能自动进化 | arXiv | 2026-04 |
| **Skill-Pro** | 非参数 PPO，跨 Agent 技能复用 | ICML 2026 Spotlight | 2026-02 |
| **MUSE-Autoskill** | 技能级记忆+全生命周期管理 | arXiv | 2026-05 |
| **Memento-Skills** | Agent 设计 Agent，结构化 Markdown 技能 | arXiv | 2026-03 |
| **COLLEAGUE.SKILL** | 专家知识蒸馏→自动技能生成 | arXiv | 2026-05 |
| **SkillRL** | 递归强化学习，技能库与策略共进化 | arXiv | 2026-02 |
| **ClawTrace** | 成本感知 Trace→Skill 蒸馏 | arXiv | 2026-04 |

---

## 三、EvoMap 在这张图里的位置

```
EvoMap 自述位置：        "Agent 进化层的 TCP/IP" → 去中心化 A2A 标准
实际产品位置：       一个混淆发布的 GEP 协议实现 + 中心化 Hub
可验证数据：         GitHub 8.7k Stars · 128K Agent · 但 98% 胶囊零复用
```

### 它与竞品的差异

| 维度 | EvoMap | Hivemind/EverOS/Acontext |
|------|--------|--------------------------|
| **经验传播范围** | 跨 Agent 网络（Hub 分发） | 单机/团队（限信任域） |
| **资产格式** | Gene/Capsule（专有 GEP 协议） | SKILL.md / Markdown（开放格式） |
| **质量门禁** | 声明式 GDI 评分 | 验证+Peer review |
| **核心代码** | ❌ 混淆发布（GPL-3.0） | ✅ 完全开源 |
| **标准竞争** | 自创 GEP | 兼容 MCP/A2A/OpenSharing |

### EvoMap 唯一真正的差异化

1. **网络级传播**：其他工具都是"单机蒸馏"，EvoMap 的 GEP 协议在概念上允许 Capsule 在 Agent 网络中传播和进化
2. **抄袭争议叙事**：带来了巨大的媒体关注度（但也树敌）

---

## 四、关键战略洞察：为什么这类工具应该做企业，而非 A2A/2C？

### 4.1 "自动经验收集"的真实 PMF 在企业场景

| 维度 | 企业/团队场景 | A2A/消费者场景 |
|------|-------------|---------------|
| **信任** | ✅ 已知同事，可放心共享 | ❌ 陌生人的 Capsule，谁敢执行？|
| **上下文** | ✅ 相同代码库/工具链/规范 | ❌ 环境千差万别，技能迁移无效 |
| **质量** | ✅ Peer review + 管理员审批 | ❌ 开放网络无有效门禁（84% 空测试）|
| **安全** | ✅ 可审计的访问控制 | ❌ node -e 沙箱绕过=病毒式传播 |
| **ROI** | ✅ 新人上手时间/错误率下降→可量化 | ❌ 用户为什么要花时间贡献技能？|
| **冷启动** | ✅ 团队已有协作数据 | ❌ 网络效应，先有鸡还是先有蛋 |

### 4.2 EvoMap 的 A2A/2C 叙事有三大不可能三角

```
               去中心化（开放网络）
                   / \
                  /   \
                 /     \
                /       \
               /         \
        安全可审计 ──── 质量可保证
                （不可能同时实现）
```

1. **信任不可能**：开放网络中无法保证 Capsule 安全，沙箱绕过漏洞使恶意代码可像病毒一样传播
2. **质量不可能**：去中心化审核=无审核（EvoMap 自己的数据已证明：84% 资产用空测试绕过质检）
3. **标准不可能**：OpenSharing (Linux Foundation, Jun 2026) + MCP (Anthropic) + A2A (Google) 已经瓜分了标准层——EvoMap 的 GEP 没有立足空间

### 4.3 那 EvoMap 为什么坚持 A2A/2C 叙事？

1. **VC 融资需要**："去中心化 Agent 进化网络"比"企业知识管理工具"的故事性感 10 倍
2. **避开正面竞争**：如果定位企业，直接面对飞书、微软、Salesforce — 毫无胜算
3. **协议梦**：想成为 TCP/IP 级的标准——但协议赢家通常是基金会/大厂，不是创业公司

### 4.4 对内容赛道的含义

如果我们要做 EvoMap 相关的内容，这个"叙事 vs 现实"的差距就是绝佳的切入角度：

- **角度 1**：被神话的中国 AI 项目——EvoMap 的竞品到底有多少？
- **角度 2**：为什么 Agent"自我进化"还是 PPT？98% 零复用的冷酷现实
- **角度 3**：从 EvoMap 看 AI 创业的叙事泡沫——当故事比代码跑得快
- **角度 4**：真正的 Agent 经验复用在哪里？企业级工具全景解读

---

## 五、信源清单

| # | 信源 | URL | 验证状态 |
|---|------|-----|---------|
| 1 | Hivemind YC Launch | https://www.ycombinator.com/launches/Qio-hivemind-continual-learning-for-coding-agents | ✅ 已验证 |
| 2 | EverOS GitHub | https://github.com/EverMind-AI/EverOS | ✅ 已验证 |
| 3 | Acontext GitHub | https://github.com/memodb-io/Acontext | ✅ 已验证 |
| 4 | PowerMem PyPI | https://pypi.org/project/powermem/ | ✅ 已验证 |
| 5 | Ultron 量子位报道 | https://hub.baai.ac.cn/view/54298 | ✅ 已验证 |
| 6 | 飞书 SkillHub 指南 | https://www.feishu.cn/content/article/7646699294103292898 | ✅ 已验证 |
| 7 | Skill-Pro (ICML 2026) | https://arxiv.org/abs/2602.01869 | ✅ 已验证 |
| 8 | SkillRL GitHub | https://github.com/aiming-lab/SkillRL | ✅ 已验证 |
| 9 | ClawTrace arXiv | https://arxiv.org/abs/2604.23853 | ✅ 已验证 |
| 10 | OpenSharing LF | https://www.linuxfoundation.org/press/linux-foundation-announces-opensharing-project-to-standardize-ai-asset-and-data-exchange | ✅ 已验证 |
| 11 | EvoMap 学术审计 | https://arxiv.org/abs/2605.25815 | ✅ 已验证（独立第三方） |
| 12 | skillrl npm | https://www.npmjs.com/package/skillrl | ✅ 已验证 |
| 13 | Claude Self-Improving | https://github.com/UniM0cha/claude-self-improving-skills | ✅ 已验证 |
| 14 | COLLEAGUE.SKILL | https://arxiv.org/abs/2605.31264 | ✅ 已验证 |
