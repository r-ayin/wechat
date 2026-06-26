
﻿### 阶段1：多维度数据采集（5-8个Agent并行，40分钟）

**编排组件**：`executor.phase1_collect()` → `executor.phase1_check()` → `executor.phase1_complete()`

**🚨 并行执行铁律**：
- 所有Agent必须在同一个响应中同时启动
- 绝对不要在for循环里串行调用sessions_spawn
- 正确做法：一次性生成所有sessions_spawn调用，让它们并行运行
- 每5分钟调用 `executor.phase1_check()` 监控状态

**执行步骤**：
```python
# 1. 获取Agent配置
agent_configs = executor.phase1_collect()

# 2. 同时启动所有Agent（一次性调用！）
delegate_task(tasks=[{"goal": config["prompt"], "toolsets": ["web"]} for config in agent_configs])
# ↑ 这些调用必须在同一个响应中完成

# 3. 每5分钟检查（使用cron或手动）
status = executor.phase1_check()
# → overdue: 警告
# → critical: kill + retry
# → all_done: 进入下一步

# 4. 所有Agent完成后
executor.phase1_complete()  # 门验证：至少3个Agent完成
```

**模型分配策略（按任务难度）**：
- `glm-5`：深度推理（残差Alpha、反向证伪、系统约束、激励机制、信息博弈、对手盘、时间动态、终局推演）
- `bailian/kimi-k2.5`：信息整合（行为心理+定量模型）
- `bailian/qwen3.5-plus`：常规任务（数据采集、幻觉检测）
- 脚本计算不经过任何LLM，直接执行Python
- 本地兜底：`ollama/qwen3.5-opus-distilled`


每个Agent的模型选择：
- 默认模型：继承父session模型（当前 openrouter/openrouter/hunter-alpha）
- 备用模型：ollama/qwen3.5-opus-distilled
- 快速验证：同默认模型（继承父session）
- 本地兜底：ollama/qwen3.5-opus-distilled

#### Agent 1：金融数据搜集

```python
delegate_task(
    goal="搜集{topic}的金融数据：股价走势与估值指标(P/E/P/B/EV/EBITDA/P/S)、财务报表关键数据(收入/利润/现金流/ROE/ROIC/毛利率)、机构持仓、投行评级、并购融资IPO动态。输出JSON，每个数据点必须有source_url。",
    toolsets=["web"]
)
```

#### Agent 2：技术动态搜集

```python
delegate_task(
    goal="搜集{topic}的技术动态：最新论文与研究成果(arXiv/顶级会议)、开源项目与代码发布(GitHub/Hugging Face)、产品更新、技术突破与benchmarks、专利申请与技术路线。优先近6个月。输出JSON，每个数据点必须有source_url。",
    toolsets=["web"]
)
```

#### Agent 3：政策监管搜集

```python
delegate_task(
    goal="搜集{topic}的政策监管动态：最新法规与政策发布、合规要求与审查、伦理争议与社会影响、国际监管对比(美/欧/中)、行业标准与认证。区分已生效/提案中政策，引用具体法规编号。输出JSON。",
    toolsets=["web"]
)
```

#### Agent 4：市场情报搜集

```python
delegate_task(
    goal="搜集{topic}的市场情报：融资轮次与估值变化、并购交易与战略投资、独角兽动态与IPO pipeline、市场份额与竞争格局、投资者情绪与资金流向。标注交易状态(confirmed/rumored/speculated)。输出JSON。",
    toolsets=["web"]
)
```

#### Agent 5：学术前沿搜集

```python
delegate_task(
    goal="搜集{topic}的学术前沿：顶级会议最新论文(NeurIPS/ICML/ACL/CVPR)、研究趋势与热点转移、学术-产业转化动态、专家观点与预测、技术路线图与里程碑。优先高引用论文。输出JSON。",
    toolsets=["web"]
)
```

#### Agent 6：宏观趋势搜集（可选）

```python
delegate_task(
    goal="搜集{topic}的宏观趋势：技术周期与adoption curve、地缘政治与供应链影响、宏观经济关联性、长期结构性变化、范式转移信号。输出JSON。",
    toolsets=["web"]
)
```

#### Agent 7：竞争情报搜集（可选）

```python
delegate_task(
    goal="搜集{topic}的竞争情报：主要竞争对手及市场份额、竞争对手战略动向、替代品和颠覆性威胁、行业进入壁垒、竞争格局变化趋势。输出JSON。",
    toolsets=["web"]
)
```

#### Agent 8：历史类比搜集（可选）

```python
delegate_task(
    goal="搜集与{topic}类似的历史事件：结构类似的历史事件(泡沫/崩盘/转型/颠覆)、当时市场环境和关键变量、传导机制和时间线、最终结果和长期影响、与当前事件的关键差异。输出JSON格式的历史事件对比数据。",
    toolsets=["web"]
)
```

**并行执行规则**：
- 所有Agent同时启动（不要串行！）
- 每5分钟检查一次所有Agent状态
- 运行时间超过40分钟的Agent标记为超时
- 失败的Agent自动重试1次
- 所有Agent完成后才能进入阶段2

---

## General Mode — Collection Agents

通用模式使用以下8个采集Agent。所有Agent并行启动，每5分钟检查一次状态。

**通用模式信源列表**（来自config.yaml `modes.general.data_sources`）：
- 热搜平台：百度热搜(top.baidu.com)、微博热搜(weibo.com/hot/search)、知乎热榜(zhihu.com/hot)、B站热榜(bilibili.com/v/popular/rank/all)
- 新闻媒体：36氪(36kr.com)、财新(caixin.com)、Reuters(reuters.com)、The Guardian(theguardian.com)、Bloomberg(bloomberg.com)
- 学术数据库：Google Scholar(scholar.google.com)、arXiv(arxiv.org)、CNKI(cnki.net)
- 公共数据：国家统计局(stats.gov.cn)、世界银行(data.worldbank.org)、Wikipedia(wikipedia.org)

#### Agent 1：事件基础数据

```python
delegate_task(
    goal="搜集{topic}的事件基础数据：完整时间线(关键节点+持续时间)、事件规模与影响范围(人数/金额/地域)、核心参与者及角色、关键事实核查(区分已确认/待确认/争议信息)、事件起因与演变路径。输出JSON，每个数据点必须有source_url，标注信息置信度(高/中/低)。",
    toolsets=["web"]
)
```

**搜索策略**：
- 百度热搜 + 微博热搜 → 获取事件热度峰值时间点
- Wikipedia + 百度百科 → 获取结构化背景
- 新闻媒体(Reuters/财新/36氪) → 交叉验证关键事实
- 信源要求：至少5个独立来源交叉验证核心事实

**输出格式**：
```json
{
  "timeline": [{"time": "ISO", "event": "描述", "source_url": "URL", "confidence": "high"}],
  "scale": {"affected_people": "数字", "financial_impact": "数字", "geographic_scope": "描述"},
  "key_actors": [{"name": "名称", "role": "角色", "affiliation": "所属"}],
  "fact_check": [{"claim": "声明", "status": "confirmed/disputed/unverified", "sources": ["URL"]}]
}
```

#### Agent 2：技术/科学视角

```python
delegate_task(
    goal="搜集{topic}相关的技术/科学背景：核心技术原理(用通俗语言解释)、技术成熟度(TRL评级1-9)、相关学术研究(arXiv/Google Scholar/CNKI近2年论文)、技术瓶颈与突破点、专家观点与技术争议。优先高引用论文和权威专家。输出JSON，每个数据点必须有source_url。",
    toolsets=["web"]
)
```

**搜索策略**：
- arXiv + Google Scholar → 近2年相关论文，按引用数排序
- CNKI → 中文文献补充
- 科普平台(果壳/知乎) → 获取通俗解释参考
- 技术博客/GitHub → 获取工程实践视角

**输出格式**：
```json
{
  "tech_background": {"principle": "通俗解释", "trl": "1-9评级", "maturity": "描述"},
  "academic_research": [{"title": "论文标题", "year": 2025, "citations": 100, "key_finding": "核心发现", "source_url": "URL"}],
  "bottlenecks": [{"bottleneck": "瓶颈描述", "severity": "高/中/低"}],
  "expert_opinions": [{"expert": "姓名", "affiliation": "机构", "viewpoint": "观点", "source_url": "URL"}]
}
```

#### Agent 3：政策/法规/治理

```python
delegate_task(
    goal="搜集{topic}相关的政策/法规/治理动态：现行法律法规(引用具体条款)、最新政策公告(区分已发布/征求意见/传闻)、监管机构立场与执法动态、国际对比(中/美/欧/日等主要经济体政策差异)、行业标准与自律规范、未来政策走向预判依据。输出JSON，每条信息标注生效状态和source_url。",
    toolsets=["web"]
)
```

**搜索策略**：
- 政府官网(各部委/省级网站) → 原始政策文件
- 法律数据库 → 法规原文
- 公报与新闻发布会记录 → 官方解读
- 国际机构(IEA/WHO/UN) → 国际标准对比

**输出格式**：
```json
{
  "laws_regulations": [{"title": "法规名称", "article": "具体条款", "status": "effective/proposed/draft", "source_url": "URL"}],
  "policy_announcements": [{"date": "日期", "issuer": "发布机构", "content": "内容摘要", "impact_assessment": "影响评估"}],
  "regulatory_stance": {"domestic": "立场描述", "international": [{"country": "国家", "stance": "立场", "source_url": "URL"}]},
  "future_trend": [{"direction": "预判方向", "evidence": ["依据1", "依据2"]}]
}
```

#### Agent 4：行业/商业动态

```python
delegate_task(
    goal="搜集{topic}的行业/商业影响：产业链上下游影响分析、相关企业动态(股价/营收/战略调整)、市场份额变化预测、商业模式创新或冲击、投资者与资本市场反应、行业协会/商会表态。标注信息源类型(一手/二手/推测)。输出JSON。",
    toolsets=["web"]
)
```

**搜索策略**：
- 36氪 + 财新 + Bloomberg → 商业影响报道
- 行业研究报告 → 产业链分析
- 公司公告/年报 → 企业官方表态
- 天眼查/企查查 → 企业关联关系

**输出格式**：
```json
{
  "industry_chain_impact": {"upstream": "上游影响", "midstream": "中游影响", "downstream": "下游影响"},
  "company_reactions": [{"company": "公司名", "action": "行动", "impact": "影响程度", "source_url": "URL"}],
  "market_share_shift": [{"sector": "领域", "before": "之前", "after_estimated": "之后估算"}],
  "investor_sentiment": {"summary": "概述", "indicators": [{"metric": "指标", "value": "值", "source_url": "URL"}]}
}
```

#### Agent 5：社会舆论/公众情绪

```python
delegate_task(
    goal="搜集{topic}的社会舆论与公众情绪：主要社交媒体平台讨论热度与趋势(微博/知乎/B站/抖音/小红书)、公众情绪分类(愤怒/担忧/支持/冷漠及占比)、舆论关键节点与转折、意见领袖(KOL)观点及传播力、语言分析(核心叙事框架/高频词/隐喻)。区分不同群体的态度差异(年龄/地域/教育)。输出JSON。",
    toolsets=["web"]
)
```

**搜索策略**：
- 微博热搜 + 评论抽样 → 情绪分类
- 知乎热榜 + 高赞回答 → 深度观点
- B站/B站评论区 → 年轻群体视角
- 各平台话题广场 → 横向对比

**输出格式**：
```json
{
  "heat_timeline": [{"date": "日期", "platform": "平台", "heat_index": "热度值", "top_topics": ["话题1"]}],
  "sentiment_distribution": {"anger": "X%", "concern": "X%", "support": "X%", "indifferent": "X%", "methodology": "抽样说明"},
  "opinion_leaders": [{"name": "名称", "platform": "平台", "followers": "粉丝数", "stance": "立场", "influence_score": "影响力评分"}],
  "narrative_frames": [{"frame": "叙事框架", "frequency": "出现频次", "example": "典型表达"}],
  "demographic_split": [{"group": "群体", "stance": "立场特征", "reason": "原因分析"}]
}
```

#### Agent 6：宏观背景/历史脉络

```python
delegate_task(
    goal="搜集{topic}的宏观背景与历史脉络：事件发生的历史渊源与演变过程、地缘政治/社会经济宏观背景、类似历史事件及结果对比(至少3个类比案例)、长期结构性因素(人口/技术/制度)、国际环境与格局变化。区分直接原因、深层原因和导火索。输出JSON。",
    toolsets=["web"]
)
```

**搜索策略**：
- Wikipedia → 历史脉络
- 学术论文 → 深层结构化分析
- 世界银行/国家统计局 → 宏观数据
- 书籍/纪录片引用 → 历史类比

**输出格式**：
```json
{
  "historical_context": {"timeline": "历史脉络", "root_causes": ["深层原因1"], "trigger": "导火索"},
  "macro_background": {"geopolitical": "地缘背景", "economic": "经济背景", "social": "社会背景"},
  "historical_analogies": [
    {"event": "类比事件", "similarity": "相似点", "difference": "关键差异", "outcome": "历史结果", "lesson": "教训"}
  ],
  "structural_factors": [{"factor": "结构性因素", "trend": "趋势方向", "data_source": "URL"}]
}
```

#### Agent 7：竞争/替代视角

```python
delegate_task(
    goal="搜集{topic}的竞争与替代视角：主流叙事以外的对立观点(至少5个独立来源)、被忽视的利益相关方声音、边缘化群体的视角、国际媒体与国内媒体的报道差异(框架/用词/强调点)、学界与业界/官方与民间的观点分歧。不要做价值判断，只客观收集并标注来源立场。输出JSON。",
    toolsets=["web"]   
)
```

**搜索策略**：
- 不同政治立场媒体(Reuters vs Xinhua, Guardian vs Global Times) → 报道框架对比
- 学术批评文章 → 学理反驳
- 社交媒体小V/普通用户 → 草根视角
- 国际组织报告 → 第三方视角

**输出格式**：
```json
{
  "opposing_views": [{"viewpoint": "对立观点", "proponent": "提出者", "evidence": ["证据1"], "source_url": "URL"}],
  "marginalized_voices": [{"group": "被忽视群体", "perspective": "视角描述", "why_ignored": "为何被忽视"}],
  "media_framing_comparison": [
    {"outlet": "媒体名", "country": "国家", "frame": "框架名称", "keywords": ["关键词"], "emphasis": "强调重点"}
  ],
  "viewpoint_divergence": [{"dimension": "分歧维度", "official": "官方立场", "academic": "学界立场", "public": "公众立场"}]
}
```

#### Agent 8：跨领域类比

```python
delegate_task(
    goal="搜集{topic}的跨领域类比模式：从其他领域寻找结构性相似的案例或模式(如用生物学解释社会现象、用物理学类比经济规律、用历史学预测技术趋势)。至少覆盖3个不同领域。识别可迁移的通用规律和领域特有的差异。警惕类比陷阱(表面相似本质不同)。输出JSON。",
    toolsets=["web"]
)
```

**搜索策略**：
- 跨学科研究论文(complexity science/systems theory) → 通用模式
- TED Talks/科普著作 → 公众可理解的类比
- 智库跨领域报告 → 系统性类比
- 注意：类比用于启发而非替代分析

**输出格式**：
```json
{
  "cross_domain_analogies": [
    {
      "source_domain": "来源领域(如生态学)",
      "analogy": "类比描述",
      "structural_similarity": "结构相似性",
      "key_difference": "关键差异",
      "transferable_insight": "可迁移洞察",
      "validity_caveat": "类比局限警告"
    }
  ],
  "universal_patterns": [{"pattern": "通用模式名", "description": "描述", "domains_observed": ["领域1", "领域2"]}],
  "analogy_health_warning": "所有类比均有局限，不替代直接分析"
}
```

**通用模式采集并行执行规则**：
- 8个Agent同时启动（不要串行！）
- 每5分钟检查一次所有Agent状态
- 运行时间超过40分钟的Agent标记为超时
- 失败的Agent自动重试1次
- 通用模式最低门槛：至少5个Agent完成才能进入阶段2（vs 财经模式3个）
- 信源多样性硬要求：通用模式每个Agent至少引用3个不同类型的信源

---
