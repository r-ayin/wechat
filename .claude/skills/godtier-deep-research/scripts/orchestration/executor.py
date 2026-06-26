#!/usr/bin/env python3
"""Godtier Deep Research - 编排执行器

主Agent的执行手册。不是自动运行的脚本，而是主Agent按步骤执行的指南。
每个函数对应一个执行步骤，主Agent调用后获得明确的下一步指令。

用法（主Agent读取此文件后按指示执行）：
    from orchestration.executor import GodtierExecutor
    executor = GodtierExecutor("英伟达财报分析")
    plan = executor.phase0_analyze("分析英伟达2025Q4财报对AI芯片市场的影响")
    # → 返回规划JSON，主Agent展示给用户审批
    executor.phase1_collect(plan)
    # → 并行启动采集Agent，等待完成
    executor.phase2_analyze(plan)
    # → 并行启动分析Agent，等待完成
    ...
"""

import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# 状态管理器
import sys
sys.path.insert(0, os.path.dirname(__file__))
from state_manager import ResearchState, AgentStatus


# 模式检测关键词
FINANCE_KEYWORDS = [
    "财报", "股价", "估值", "IPO", "并购", "融资", "行业竞争",
    "上市公司", "市盈率", "净利润", "营收", "资产负债表",
    "stock", "revenue", "market cap", "investment", "VC", "PE fund",
]


def _detect_mode(topic: str) -> str:
    """根据主题关键词检测研究模式（finance / general）"""
    topic_lower = topic.lower()
    for kw in FINANCE_KEYWORDS:
        if kw.lower() in topic_lower:
            return "finance"
    return "general"


class GodtierExecutor:
    """神级深度研究编排执行器"""

    def __init__(self, topic: str, mode: str = "full", skill_dir: str = None,
                 research_mode: str = "auto"):
        self.topic = topic
        self.mode = mode          # 深度模式: full / quick / risk / compete
        self.date = datetime.now().strftime("%Y-%m-%d")

        # 研究领域模式: finance / general / auto
        if research_mode == "auto":
            self.research_mode = _detect_mode(topic)
        else:
            self.research_mode = research_mode

        # 技能目录
        if skill_dir:
            self.skill_dir = skill_dir
        else:
            self.skill_dir = os.path.dirname(os.path.dirname(__file__))

        # 初始化状态
        self.state = ResearchState(topic, self.date)
        self.state.mode = mode

        # 输出目录
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:50])
        self.output_dir = os.path.join(
            self.skill_dir, "output", "godtier-research", f"{safe_topic}_{self.date}"
        )
        os.makedirs(self.output_dir, exist_ok=True)
        self.state.analysis_dir = self.output_dir
        self.state.save()

    # =========================================================================
    # 阶段0：需求分析与主题解构
    # =========================================================================

    def phase0_analyze(self, user_request: str) -> dict:
        """
        阶段0：分析用户需求，生成研究规划

        主Agent执行步骤：
        1. 调用此方法获取规划模板
        2. 使用glm-5分析主题，填充模板
        3. 将规划展示给用户审批
        4. 用户批准后调用 phase0_approve()

        返回：规划JSON（供主Agent填充）
        """
        self.state.start_phase("phase0_planning")

        # 生成规划模板
        plan_template = {
            "topic": self.topic,
            "mode": self.mode,
            "research_mode": self.research_mode,
            "date": self.date,
            "user_request": user_request,
            "core_questions": [],  # 主Agent填充 2-3个核心问题
            "analysis_scope": "",  # 分析范围
            "estimated_duration": self._get_duration_estimate(),
            "phases": {
                "phase0": {"name": "需求分析", "duration": "10分钟", "agents": 0},
                "phase1": {
                    "name": "多维度数据采集",
                    "duration": "40分钟",
                    "agents": self._get_agent_count("collection"),
                    "agent_list": self._get_collection_agents(),
                },
                "phase2": {
                    "name": "深度分析",
                    "duration": "30分钟",
                    "agents": self._get_agent_count("analysis"),
                    "agent_list": self._get_analysis_agents(),
                },
                "phase3": {"name": "文章撰写", "duration": "20分钟", "agents": 0},
                "phase4": {"name": "质量验证", "duration": "10分钟", "agents": 0},
                "phase5": {"name": "输出存档", "duration": "5分钟", "agents": 0},
            },
            "status": "pending_approval",
        }

        # 保存规划
        plan_path = os.path.join(self.output_dir, "research_plan.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan_template, f, ensure_ascii=False, indent=2)

        self.state.complete_agent("__planner__", plan_path)
        self.state.save()

        return plan_template

    def phase0_approve(self, plan: dict = None):
        """
        阶段0完成：用户已审批规划

        主Agent在用户说"可以"、"开始"、"批准"后调用此方法。
        规划已批准，可以进入阶段1。
        """
        if plan:
            plan_path = os.path.join(self.output_dir, "research_plan.json")
            with open(plan_path, "w", encoding="utf-8") as f:
                json.dump(plan, f, ensure_ascii=False, indent=2)

        self.state.complete_phase("phase0_planning")
        return f"规划已批准，准备进入阶段1（{self._get_agent_count('collection')}个采集Agent）"

    # =========================================================================
    # 阶段1：多维度数据采集（并行）
    # =========================================================================

    def phase1_collect(self) -> list[dict]:
        """
        阶段1：并行启动数据采集Agent

        主Agent执行步骤：
        1. 调用此方法获取Agent配置列表
        2. 对每个Agent配置，执行 sessions_spawn(task=agent["prompt"])
        3. 所有Agent同时启动（不要串行！）
        4. 每5分钟调用 phase1_check() 检查状态
        5. 所有Agent完成后调用 phase1_complete()

        返回：Agent配置列表（每个包含name, model, prompt, expected_minutes）
        """
        self.state.start_phase("phase1_collection")

        agents = self._get_collection_agents()
        agent_configs = []

        for agent_def in agents:
            # 注册Agent
            self.state.register_agent(
                agent_def["name"],
                agent_def.get("model", "bailian/qwen3.5-plus"),
                agent_def.get("expected_minutes", 40),
            )

            # 生成完整prompt
            prompt = self._build_collection_prompt(agent_def)
            agent_configs.append({
                "name": agent_def["name"],
                "model": agent_def.get("model", "bailian/qwen3.5-plus"),
                "prompt": prompt,
                "expected_minutes": agent_def.get("expected_minutes", 40),
                "output_file": os.path.join(self.output_dir, f"phase1_{agent_def['name']}.json"),
            })

        self.state.save()
        return agent_configs

    def phase1_check(self) -> dict:
        """
        检查阶段1 Agent状态（每5分钟调用一次）

        返回：状态报告 {
            "running": [...],
            "completed": [...],
            "failed": [...],
            "overdue": [...],      # 需要警告
            "critical": [...],     # 需要kill+retry
            "all_done": bool
        }
        """
        return self._check_agents("phase1_collection")

    def phase1_complete(self):
        """阶段1完成，验证门条件"""
        passed, msg = self.state.verify_phase_gate("phase1_collection")
        if not passed:
            raise ValueError(f"阶段1门验证失败: {msg}\n需要重试失败的Agent或降低最低完成要求")
        self.state.complete_phase("phase1_collection")

    # =========================================================================
    # 阶段2：深度分析（并行）
    # =========================================================================

    def phase2_analyze(self) -> list[dict]:
        """
        阶段2：并行启动深度分析Agent

        执行步骤同阶段1：
        1. 获取Agent配置
        2. 同时启动所有sessions_spawn
        3. 每5分钟检查
        4. 完成后验证门

        注意：阶段2 Agent会读取阶段1的输出文件，不需要通过attachments传递。
        """
        self.state.start_phase("phase2_analysis")

        agents = self._get_analysis_agents()
        agent_configs = []

        for agent_def in agents:
            self.state.register_agent(
                agent_def["name"],
                agent_def.get("model", "glm-5"),
                agent_def.get("expected_minutes", 30),
            )

            prompt = self._build_analysis_prompt(agent_def)
            agent_configs.append({
                "name": agent_def["name"],
                "model": agent_def.get("model", "glm-5"),
                "prompt": prompt,
                "expected_minutes": agent_def.get("expected_minutes", 30),
                "output_file": os.path.join(self.output_dir, f"phase2_{agent_def['name']}.md"),
            })

        self.state.save()
        return agent_configs

    def phase2_check(self) -> dict:
        """检查阶段2 Agent状态"""
        return self._check_agents("phase2_analysis")

    def phase2_complete(self):
        """阶段2完成"""
        passed, msg = self.state.verify_phase_gate("phase2_analysis")
        if not passed:
            raise ValueError(f"阶段2门验证失败: {msg}")
        self.state.complete_phase("phase2_analysis")

    # =========================================================================
    # 阶段3：文章撰写（主Agent执行）
    # =========================================================================

    def phase3_get_inputs(self) -> dict:
        """
        获取阶段3需要读取的所有输入文件

        返回：{
            "phase1_outputs": [...],
            "phase2_outputs": [...],
            "total_files": int
        }
        """
        phase1_files = [
            f for f in os.listdir(self.output_dir)
            if f.startswith("phase1_") and f.endswith(".json")
        ]
        phase2_files = [
            f for f in os.listdir(self.output_dir)
            if f.startswith("phase2_") and f.endswith(".md")
        ]
        return {
            "phase1_outputs": [os.path.join(self.output_dir, f) for f in phase1_files],
            "phase2_outputs": [os.path.join(self.output_dir, f) for f in phase2_files],
            "total_files": len(phase1_files) + len(phase2_files),
        }

    def phase3_start(self):
        """阶段3开始（主Agent撰写文章）"""
        self.state.start_phase("phase3_writing")

    def phase3_complete(self, article_path: str):
        """阶段3完成，验证文章"""
        if not os.path.exists(article_path):
            raise ValueError(f"文章文件不存在: {article_path}")
        size = os.path.getsize(article_path)
        if size < 5000:
            raise ValueError(f"文章太小 ({size} bytes)，需要至少5000 bytes")
        self.state.complete_phase("phase3_writing")

    # =========================================================================
    # 阶段4：质量验证
    # =========================================================================

    def phase4_verify(self) -> dict:
        """
        阶段4：生成验证检查清单

        返回：{
            "checks": [...],  # 检查项列表
            "detectors": [...]  # 需要运行的检测器
        }
        """
        self.state.start_phase("phase4_verification")

        return {
            "checks": [
                {"layer": "L1", "name": "数字级验证", "items": [
                    "所有精确数字是否有来源URL",
                    "所有计算结果是否有脚本执行记录",
                    "是否存在无来源的精确数字",
                    "数字单位是否明确一致",
                    "是否有超出合理范围的数字",
                ]},
                {"layer": "L2", "name": "逻辑级验证", "items": [
                    "每个因果推论是否有传导机制",
                    "是否存在相关≠因果的推论",
                    "每个核心结论是否有证伪条件",
                    "是否考虑了反面证据",
                ]},
                {"layer": "L3", "name": "全文级验证", "items": [
                    "随机抽查10%的URL是否可访问",
                    "数字单位是否全文一致",
                    "文章结构是否完整",
                    "信源覆盖是否充分",
                ]},
            ],
            "detectors": [
                os.path.join(self.skill_dir, "detectors", "number_hallucination.py"),
                os.path.join(self.skill_dir, "detectors", "logic_hallucination.py"),
                os.path.join(self.skill_dir, "detectors", "source_hallucination.py"),
            ],
            "article_path": os.path.join(self.output_dir, "article.md"),
            "report_path": os.path.join(self.output_dir, "hallucination_report.json"),
        }

    def phase4_complete(self, report_path: str):
        """阶段4完成，检查幻觉检测结果"""
        if os.path.exists(report_path):
            with open(report_path, "r") as f:
                report = json.load(f)
            if report.get("overall") != "PASS":
                raise ValueError(f"幻觉检测未通过: {report.get('overall')}")
        self.state.complete_phase("phase4_verification")

    # =========================================================================
    # 阶段5：输出
    # =========================================================================

    def phase5_output(self) -> dict:
        """阶段5：输出配置"""
        self.state.start_phase("phase5_output")
        return {
            "article_md": os.path.join(self.output_dir, "article.md"),
            "output_dir": self.output_dir,
            "formats": ["markdown", "html", "pdf"],
            "discord_channel": "1475075103057514496",
        }

    def phase5_complete(self):
        """阶段5完成，整个研究任务结束"""
        self.state.complete_phase("phase5_output")
        return f"[OK] 研究完成: {self.topic} ({self.date})"

    # =========================================================================
    # 内部方法
    # =========================================================================

    def _get_duration_estimate(self) -> str:
        durations = {
            "full": "~2小时",
            "quick": "~30分钟",
            "risk": "~1小时",
            "compete": "~1小时",
        }
        return durations.get(self.mode, "~2小时")

    def _get_agent_count(self, phase_type: str) -> int:
        counts = {
            "full": {"collection": 8, "analysis": 7},
            "quick": {"collection": 4, "analysis": 3},
            "risk": {"collection": 5, "analysis": 4},
            "compete": {"collection": 6, "analysis": 5},
        }
        return counts.get(self.mode, counts["full"])[phase_type]

    def _get_collection_agents(self, mode: str = None) -> list[dict]:
        """获取数据采集Agent定义

        Args:
            mode: 研究领域模式 ("finance" / "general")，默认使用 self.research_mode
        """
        if mode is None:
            mode = self.research_mode

        if mode == "general":
            all_agents = [
                {"name": "技术动态", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_tech"},
                {"name": "政策监管", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_policy"},
                {"name": "社会趋势", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_social"},
                {"name": "学术前沿", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_academic"},
                {"name": "宏观趋势", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_macro"},
                {"name": "竞争分析", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_competition"},
                {"name": "历史类比", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_historical"},
                {"name": "用户洞察", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_user_insight"},
            ]
        else:
            # finance (default, backward compatible)
            all_agents = [
                {"name": "金融数据", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_financial"},
                {"name": "技术动态", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_tech"},
                {"name": "政策监管", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_policy"},
                {"name": "市场情报", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_market"},
                {"name": "学术前沿", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_academic"},
                {"name": "宏观趋势", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_macro"},
                {"name": "竞争情报", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_competition"},
                {"name": "历史类比", "model": "bailian/qwen3.5-plus", "expected_minutes": 40,
                 "prompt_template": "phase1_historical"},
            ]
        count = self._get_agent_count("collection")
        return all_agents[:count]

    def _get_analysis_agents(self, mode: str = None) -> list[dict]:
        """获取深度分析Agent定义

        Args:
            mode: 研究领域模式 ("finance" / "general")，默认使用 self.research_mode
        """
        if mode is None:
            mode = self.research_mode

        if mode == "general":
            all_agents = [
                {"name": "L1趋势分析", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_trend", "layers": "L1"},
                {"name": "L2因果推断", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_causal", "layers": "L2"},
                {"name": "L3系统约束", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_constraints_general", "layers": "L3"},
                {"name": "L4信息博弈", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_information", "layers": "L4"},
                {"name": "L5多视角交叉", "model": "bailian/kimi-k2.5", "expected_minutes": 30,
                 "prompt_template": "phase2_crossview", "layers": "L5"},
                {"name": "L6行为定量", "model": "bailian/kimi-k2.5", "expected_minutes": 30,
                 "prompt_template": "phase2_behavioral_general", "layers": "L6"},
                {"name": "L7终局推演", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_endgame", "layers": "L7"},
            ]
        else:
            # finance (default, backward compatible)
            all_agents = [
                {"name": "L-1残差Alpha", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_residual", "layers": "L-1"},
                {"name": "L0-L1反向证伪", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_falsification", "layers": "L0-L1"},
                {"name": "L2-L3系统约束", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_constraints", "layers": "L2-L3"},
                {"name": "L4-L5信息博弈", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_information", "layers": "L4-L5"},
                {"name": "L6-L7对手盘", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_opponent", "layers": "L6-L7"},
                {"name": "L8-L9行为定量", "model": "bailian/kimi-k2.5", "expected_minutes": 30,
                 "prompt_template": "phase2_behavioral", "layers": "L8-L9"},
                {"name": "L10终局推演", "model": "glm-5", "expected_minutes": 30,
                 "prompt_template": "phase2_endgame", "layers": "L10"},
            ]
        count = self._get_agent_count("analysis")
        return all_agents[:count]

    def _build_collection_prompt(self, agent_def: dict) -> str:
        """构建采集Agent的完整prompt（包含输出路径和上下文）"""
        return f"""你是{agent_def['name']}采集专家。任务：搜集{self.topic}的{agent_def['name']}数据。

【输出要求】
- 输出文件：{os.path.join(self.output_dir, f"phase1_{agent_def['name']}.json")}
- 每个数据点必须有source_name和source_url
- 无法找到URL的数据标记verification_status="unverified"

【主题】{self.topic}
【分析目录】{self.output_dir}

详细prompt模板见：{os.path.join(self.skill_dir, 'workflows', '05-phase1-collection.md')}
请严格按照该模板中{agent_def['name']}Agent的完整prompt执行。
"""

    def _build_analysis_prompt(self, agent_def: dict) -> str:
        """构建分析Agent的完整prompt"""
        return f"""你是{agent_def['name']}分析专家。任务：对{self.topic}进行{agent_def['layers']}层深度分析。

【输入数据】
读取目录 {self.output_dir} 下所有phase1_*.json文件作为数据输入。

【输出要求】
- 输出文件：{os.path.join(self.output_dir, f"phase2_{agent_def['name']}.md")}
- 1500-2000字深度分析
- 所有计算必须调用Python脚本（scripts/computation/）
- 所有数据必须有source_url

【主题】{self.topic}

详细prompt模板见：{os.path.join(self.skill_dir, 'workflows', '06-phase2-analysis.md')}
请严格按照该模板中{agent_def['name']}Agent的完整prompt执行。
"""

    def _check_agents(self, phase: str) -> dict:
        """检查Agent状态，返回需要处理的Agent列表"""
        agents = self.state.get_phase_agents(phase)
        result = {
            "running": [],
            "completed": [],
            "failed": [],
            "overdue": [],
            "critical": [],
            "all_done": True,
        }
        for a in agents:
            if a.status == AgentStatus.RUNNING:
                result["running"].append(a.name)
                result["all_done"] = False
                if a.is_critical_overdue():
                    result["critical"].append(a.name)
                elif a.is_overdue():
                    result["overdue"].append(a.name)
            elif a.status == AgentStatus.COMPLETED:
                result["completed"].append(a.name)
            elif a.status in (AgentStatus.FAILED, AgentStatus.TIMEOUT):
                result["failed"].append(a.name)
                result["all_done"] = False
            elif a.status == AgentStatus.PENDING:
                result["all_done"] = False
        return result


# CLI 接口
if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(
        description="Godtier Deep Research - 神级深度研究编排执行器"
    )
    parser.add_argument(
        "command", choices=["plan", "status"],
        help="执行命令: plan=生成研究规划, status=查看状态"
    )
    parser.add_argument(
        "topic", help="研究主题"
    )
    parser.add_argument(
        "depth", nargs="?", default="full",
        choices=["full", "quick", "risk", "compete"],
        help="研究深度模式 (默认: full)"
    )
    parser.add_argument(
        "--mode", "-m", default="auto",
        choices=["finance", "general", "auto"],
        help="研究领域模式 (默认: auto 自动检测)"
    )

    args = parser.parse_args()

    executor = GodtierExecutor(
        args.topic,
        mode=args.depth,
        research_mode=args.mode,
    )

    if args.command == "plan":
        plan = executor.phase0_analyze(f"分析{args.topic}")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    elif args.command == "status":
        print(f"Topic: {executor.state.topic}")
        print(f"Phase: {executor.state.current_phase}")
        print(f"Research Mode: {executor.research_mode}")
        print(f"Output: {executor.output_dir}")
