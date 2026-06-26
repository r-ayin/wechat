# wechat — 微信公众号深度长文

> 遵循项目协议 [PROTOCOL.md](PROTOCOL.md)

## 项目身份
- **名称**：被压迫者小组 — 信息差平权者
- **核心主张**：用深度研究内容帮普通人磨平 AI 时代的信息差
- **内容形态**：微信公众号深度长文（15000-30000 字/篇）
- **人格系统**：SOUL.md + STYLE.md + PERSONA.md 三件套全量注入
- **情感温度**：2/10（冷峻克制、数据密集、具体人物叙事、结构性批判）
- **技术栈**：godtier-deep-research（共享技能）+ persona 引擎
- **状态**：🟢 活跃生产

## 🔴 管线强制规则（不可跳过）

> 违反视为流程违规。任何文章产出必须经过完整六阶段管线。

1. **写任何文章 → 必须先加载 `wechat-pipeline` Skill**
   - Skill 位置：`.claude/skills/wechat-pipeline/SKILL.md`
   - 触发词：做一期关于 / 跑管线 / 写一篇 / 开始写 / 深度研究这个

2. **不可跳阶段** — Phase 0→1→2→3→3.5→4 严格顺序
   - 每阶段用 `bash scripts/pipeline-gate.sh verify {phase}` 门禁检查
   - 产出文件不通过门禁 → 不可进入下一阶段

3. **Phase 3 写作前 → 强制读取 persona 三件套**
   - `persona/SOUL.md` — 核心信念与世界観
   - `persona/STYLE.md` — 15维风格指纹
   - `persona/PERSONA.md` — 紧凑人设卡
   - 未读 persona 就开始写 → 视为违规

4. **严禁脏话和粗口**
   - "我草""我靠""他妈的""傻逼"等绝不出现在发表文章中
   - persona 文件中出现的此类词汇是内部人格标记，不是发表用语

5. **对标写法铁律** — 每篇文章必须包含：
   - 一个有名有姓的真实人物（化名可）+ 具体故事
   - 一处具体场景描写（时间+地点+环境）
   - 一组可验证的数据或事实
   - 一个当前热点事件作为钩子
   - 理论引用 ≤ 全文 20%

6. **QA 门禁** — Phase 3.5 必须跑 script-verifier
   - `python script-verifier/verifier.py extract → WebSearch → judge`
   - FALSIFIED=0 才算通过
   - 最多 3 轮迭代修复

7. **Persona 同步** — 每次写作前（如果在 x-tool 工作区中）：
   ```bash
   # x-tool 工作区模式：从 persona 引擎同步最新文件
   python ../persona/adapters/wechat_bridge.py sync 2>/dev/null || echo "跳过: 独立克隆模式，使用 wechat/persona/ 内置文件"
   ```
   确保 persona 文件与引擎最新版一致。独立克隆时 wechat/persona/ 自包含。

8. **Git 策略** — Phase 4 提交后自动 push：
   - Remote: `origin` | Branch: `main`
   - `git add output/wechat_articles/ && git commit -m "feat: ..." && git push origin main`

## 🔀 模式路由

| 触发词 | 模式 | 行为 |
|--------|------|------|
| `做一期关于XX` / `分析XX` | 🚀 **自动** | 直接跑管线 |
| `聊一下XX` / `咨询XX` / `帮我挖一下XX` / `聊选题` | 🎯 **手动** | Dankoe 八问采访 → brief → 管线 |
| `深挖XX` / `深度研究XX`（歧义） | ⚠️ **消歧** | 追加确认「先聊方向还是直接研究？」 |

## 内容管线（全景）

```
                      📥 选题输入
                         │
                         ▼
              ┌──────────────────────┐
              │   🔀 模式路由         │
              │ 🚀 自动 → 直接进管线  │  🎯 手动 → Dankoe 需求采访
              └──────┬───────────────┘
                     │
                     ▼
              ┌──────────────────────────────────┐
              │ 🆕 Phase 0.5: Dankoe 需求采访     │
              │   (仅手动模式) 八问 → brief → 确认 │
              └──────────────┬───────────────────┘
                             │
                             ▼
① 热点选题 (对标驱动·hot-scanner 每 4h 扫描)
       │
       ▼
② godtier-deep-research 深度研究
   ← 手动模式受 pipeline_brief.md 约束
       │
       ▼
③ persona 人格化重写 (三步迁移法)
   ← SOUL.md 世界观 + STYLE.md 风格指纹 + PERSONA.md 人设卡 全量注入
       │
       ▼
🛡️ ③.5 QA 长文质量保障 (四步强制门禁)
   ├── 步骤1: 搜证 — 事实性修改前先 WebSearch
   ├── 步骤2: 逻辑一致性审查 — 检测"结构问题→个体方案"矛盾
   ├── 步骤3: L4 防幻觉验证 — claim_extractor → WebSearch → fact_checker
   └── 步骤4: 迭代修复 — FALSIFIED 立即修，最多3次
       │
       ▼
④ 输出 → output/wechat_articles/ (evergreen/ + hot/)
```

### Brief 穿透全管线（手动模式）

| brief 字段 | 消费者 | 约束方式 |
|-----------|--------|---------|
| 核心误解 + 非共识 | Phase ② godtier | 重点反驳方向 |
| 认知层级 | Phase ② godtier | 研究深度参数 |
| 内容象限 | Phase ② godtier | 类比维度选择 |
| 受众画像 | Phase ③ persona | 语言复杂度锚定 |
| 情感锚点 | Phase ③ persona | STYLE.md 情感温度 |
| 个人关联 | Phase ③ persona | 独特视角注入 |
| 行动导向 | Phase ③ persona | CTA 设计 |
| 对标参考 | Phase ① 对标发现 | 差异化空间定位 |

> ⚠️ brief 存在时，每个管线阶段必须消费对应字段。跳过视为流程违规。

## QA 门禁规则（Phase ③.5 强制执行）

### 触发条件

| 触发 | 动作 |
|------|------|
| persona 重写产出新长文 | 完整四步 QA |
| 对已有长文做事实性修改 | 搜证 → 逻辑审查 → L4 |
| 对已有长文做结构性重写 | 搜证 → 逻辑审查 → L4 |
| 仅修改错别字/格式 | 跳过 |

### 四步流程

**步骤 1: 先搜证，再动笔** — 事实性修改前必先 WebSearch 收集数据。

**步骤 2: 逻辑一致性审查** — 自查清单：
1. 核心论点维度是结构性还是个体性？
2. 结尾方案与论点维度是否一致？
3. 有没有"前文证明不可能，后文建议去做"？
4. 结尾是诚实承认困难，还是假装有简单答案？
5. 故事人物的处境与给他们的建议是否自洽？

**步骤 3: L4 防幻觉验证** — `verifier.py extract → WebSearch → verifier.py judge`

**步骤 4: 迭代修复** — FALSIFIED 立即修，3次修不好→标记"事实不可验证·放弃"

## 常见反模式

| 类型 | ❌ | ✅ |
|------|----|----|
| 劳动/阶级批判 | "你只需要勇敢一点" | "一个人做不到。找到和你处境一样的人。" |
| 系统性问题 | "只要我们还疼/愤怒" | "疼是信号。但信号需要被连接。" |
| 个体觉醒 | "取决于老赵" | "取决于老赵能不能找到其他老赵。" |

## 核心原则

1. **信息差平权** — 每期回答"普通人不了解但应该知道的事"
2. **搜证先于动笔** — 事实性修改前必先 WebSearch
3. **逻辑一致性 > 情绪感染力** — 结尾不能背叛前文论证
4. **人格一致性** — 所有文章 SOUL+STYLE+PERSONA 全量注入
5. **先聊透再研究（手动）** — 模糊选题先 Dankoe 采访
6. **引擎止于文章** — 微信公众号是最终输出形态

## 项目结构

```
wechat/
├── CLAUDE.md                ← 本文件
├── PROGRESS.md
├── GATES.md
├── persona/                 ← 🧠 人格三件套
│   ├── SOUL.md              ← 核心信念与世界観
│   ├── STYLE.md             ← 15维风格指纹
│   └── PERSONA.md           ← 紧凑人设卡
├── hotspot-entry/           ← 🎯 选题入口（双模式）
│   └── SKILL.md
├── topic-pool/              ← 🗂️ 选题池 + hot-scanner
├── benchmark/               ← 📊 对标账号数据库
├── prompts/
│   └── dankoe-interview.md  ← Dankoe 采访提示词
├── reference/               ← 📄 参考资料
├── planning/                ← 📋 规划文档
└── output/
    └── wechat_articles/     ← 📦 微信长文产出
        ├── evergreen/
        └── hot/
```

## 依赖

| 依赖 | 位置 | 用途 |
|------|------|------|
| godtier-deep-research | `.claude/skills/godtier-deep-research/` | 深度研究引擎（已内化） |
| script-verifier (L4) | `script-verifier/` | L4 防幻觉验证（已内化） |
| PROTOCOL.md | `PROTOCOL.md` | 项目协议 |

## 关联项目
- [抖音脚本项目](https://github.com/r-ayin/douyin) — 将微信长文拆分为口播脚本（独立仓库）
