---
name: wechat-pipeline
description: 微信公众号长文管线 — 六阶段强制流水线。Phase 0 竞品→1 选题→2 godtier研究→3 persona重写→3.5 QA→4 输出。门禁脚本强制执行，不可跳阶段。
triggers:
  - 跑管线
  - 开始写
---

# WeChat Pipeline — 六阶段强制流水线

## 硬规则

1. **不可跳阶段** — 每阶段必须产出对应文件，pipeline-gate.sh 验证通过才能进入下一阶段
2. **persona 全量注入** — Phase 3 写作前必须先读 `persona/SOUL.md` + `persona/STYLE.md` + `persona/PERSONA.md`
3. **QA 门禁强制** — Phase 3.5 必须跑 script-verifier（extract → WebSearch → judge），FALSIFIED=0 才算通过
4. **对标写法** — 每篇文章必须包含：具体的人+具体场景+可验证数据+热点钩子+理论引用服务于解释现象，不单独展开（比例由 persona/STYLE.md 风格分析自然确定）
5. **严禁脏话** — persona 文件中的粗口是内部人格标记，不是发表用语

## 六阶段流水线

### Phase 0: 竞品风格蒸馏
**产出**: `output/research/{slug}_competitor-style_{date}.md`
**内容**: 搜竞品文章（数量取决于竞品格局密度，默认≥5篇）→ 五维拆解（切口/论点/人物/证据/差异化）→ 提取对标写法 → **必须包含竞对情感温度评估（0-10）**
**门禁**: 文件 ≥2000 bytes && 包含五维标签 && 包含情感温度数字

**Phase 0 完成后，运行情感温度计算**:
```bash
python ../persona/adapters/emotion_calculator.py \
  --personal-file persona/STYLE.md \
  --competitor-file output/research/{slug}_competitor-style_{date}.md
```
结果（三向加权：差距≤1→加成 / ≤3→保持个人 / >3→加权平均 个人×0.6+竞对×0.4）写入 Phase 3 写作参数。禁止再使用硬编码的 2/10。

### Phase 1: 研究简报
**产出**: `output/research/{slug}_brief_{date}.md`
**内容**: 核心论点+要推翻的误解+非共识角度+数据素材+对标竞品盲区
**门禁**: 文件 ≥1500 bytes

### Phase 2: godtier 13层深度分析
**产出**: `output/research/{slug}_analysis_{date}.md`
**内容**: L-1前提挑战→L0反向证伪→L1范式谬误→...→L10综合断言。每层锚定具体数据。
**门禁**: 文件 ≥45000 bytes (对应 CLAUDE.md 深度长文 15000汉字 × 3 bytes/char ≈ 45000 bytes) && 包含 ≥10层

### Phase 3: persona 人格化重写
**前置**: 必须先读 persona/SOUL.md + persona/STYLE.md + persona/PERSONA.md
**产出**: `output/wechat_articles/{category}/{标题}_{date}.md`
**铁律**:
- 开头：具体的人+具体场景（不用抽象问题/宣言式开头）
- 主体：人物故事→结构分析(数据/理论支撑)→回到人物
- 结尾：回到场景/人物/开放式问题，不给简单答案
- 情感温度：读取 persona/STYLE.md（禁止硬编码固定值）
- 格式：无 Markdown 小标题(##)、无列表(-)、无加粗(**)
- 长度：15000-30000字（CLAUDE.md 深度长文标准）
- **禁止**：脏话、粗口、空洞理论堆叠、政治口号、"治愈""正常""客观""正能量"
- **Persona 标记**：在文章 frontmatter 中添加 `SOUL+STYLE+PERSONA 全量注入`（管道门禁检查此标记），但正文中不出现该字符串

### Phase 3.5: QA 四步门禁
1. **搜证**: 事实性修改前先 WebSearch
2. **逻辑一致性审查**: 五问自查（结构性/一致性/自洽/诚实/人物处境）
3. **L4 验证**（三步，不可合并）:
   - Step A: `python script-verifier/verifier.py extract {article} -o plan.json`
   - Step B: Agent 逐条 WebSearch 搜证，写入 results.json
   - Step C: `python script-verifier/verifier.py judge plan.json --results results.json -o report.json`
4. **迭代修复**: FALSIFIED 立即修，最多 N 轮（默认3，可在 pipeline-gate.sh 调整）
**产出**: `output/research/{slug}_QA_{date}.md`
**通过条件**: FALSIFIED=0（或 grep -cE 'FALSIFIED.*0|门禁通过|GATE:.*PASS' report.json）

### Phase 4: 输出
更新 PROGRESS.md、提交 git、推送到 GitHub

## 管线门禁命令

```bash
# 检查前置 checkpoint（Phase N 开始前必须通过）
bash scripts/pipeline-gate.sh check {phase} {slug} {date}

# 验证当前阶段产出质量
bash scripts/pipeline-gate.sh verify {phase} {slug} {date}

# 查看管线状态
bash scripts/pipeline-gate.sh status
```

## 阶段推进流程

```
用户: "做一期关于XXX"
         │
         ▼
Phase 0: 竞品蒸馏 ──→ gate.sh verify 0
         │
         ▼
Phase 1: 研究简报 ──→ gate.sh verify 1
         │
         ▼
Phase 2: godtier分析 ──→ gate.sh verify 2
         │
         ▼
读 persona/SOUL.md + STYLE.md + PERSONA.md
         │
         ▼
Phase 3: persona重写 ──→ gate.sh verify 3
         │
         ▼
Phase 3.5: QA ──→ gate.sh verify 3.5 (FALSIFIED=0)
         │
         ▼
Phase 4: git commit + push
```

## 严禁的操作

- 跳过任何阶段直接写文章
- 在 Phase 3 之前开始写作
- 不读 persona 文件就写
- 使用脏话或粗口
- 写抽象问题开头（应写具体人物+场景）
- 使用 Markdown 小标题、列表、加粗
- QA 未通过就提交
