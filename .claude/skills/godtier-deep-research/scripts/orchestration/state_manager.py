#!/usr/bin/env python3
"""Godtier Deep Research - 状态管理器

管理研究任务的断点续传、Agent状态追踪和阶段门验证。
用法:
    from state_manager import ResearchState
    state = ResearchState("topic_name", "2026-03-13")
    state.start_phase("phase1_collection")
    state.register_agent("金融数据", model="qwen3.5-plus")
    state.complete_agent("金融数据", output_file="output/金融_data.json")
    state.verify_phase_gate("phase1_collection")  # 检查是否可以进入下一阶段
    state.save()
"""

import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# 状态文件根目录
STATE_DIR = os.environ.get(
    "GODTIER_STATE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output", "godtier-research", "states")
)


class AgentStatus:
    """单个Agent的状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RETRYING = "retrying"

    def __init__(self, name: str, model: str = "inherit", expected_minutes: int = 40):
        self.name = name
        self.model = model
        self.expected_minutes = expected_minutes
        self.status = self.PENDING
        self.started_at: Optional[str] = None
        self.completed_at: Optional[str] = None
        self.output_file: Optional[str] = None
        self.error: Optional[str] = None
        self.retry_count = 0
        self.max_retries = 1

    def start(self):
        self.status = self.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()

    def complete(self, output_file: str = None):
        self.status = self.COMPLETED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.output_file = output_file

    def fail(self, error: str):
        self.status = self.FAILED
        self.error = error
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def timeout(self):
        self.status = self.TIMEOUT
        self.completed_at = datetime.now(timezone.utc).isoformat()

    def retry(self):
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            self.status = self.RETRYING
            self.error = None
            self.started_at = None
            self.completed_at = None
            return True
        return False

    def is_overdue(self) -> bool:
        """检查是否超时（运行时间超过预期1.5倍）"""
        if self.status != self.RUNNING or not self.started_at:
            return False
        start = datetime.fromisoformat(self.started_at)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds() / 60
        return elapsed > self.expected_minutes * 1.5

    def is_critical_overdue(self) -> bool:
        """检查是否严重超时（超过预期2倍，需要kill）"""
        if self.status != self.RUNNING or not self.started_at:
            return False
        start = datetime.fromisoformat(self.started_at)
        elapsed = (datetime.now(timezone.utc) - start).total_seconds() / 60
        return elapsed > self.expected_minutes * 2.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "expected_minutes": self.expected_minutes,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "output_file": self.output_file,
            "error": self.error,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentStatus":
        agent = cls(data["name"], data.get("model", "inherit"), data.get("expected_minutes", 40))
        agent.status = data.get("status", cls.PENDING)
        agent.started_at = data.get("started_at")
        agent.completed_at = data.get("completed_at")
        agent.output_file = data.get("output_file")
        agent.error = data.get("error")
        agent.retry_count = data.get("retry_count", 0)
        return agent


class ResearchState:
    """研究任务的完整状态管理"""

    PHASES = [
        "phase0_planning",
        "phase1_collection",
        "phase2_analysis",
        "phase3_writing",
        "phase4_verification",
        "phase5_output",
    ]

    # 每个阶段的最低完成要求（用于门验证）
    PHASE_GATES = {
        "phase0_planning": {
            "required_outputs": ["research_plan.json"],
            "description": "规划报告已生成",
        },
        "phase1_collection": {
            "required_agent_statuses": ["completed"],
            "min_completed_agents": 3,  # 至少3个采集Agent完成
            "required_outputs": [],  # 由Agent输出文件决定
            "description": "数据采集完成（至少3个Agent成功）",
        },
        "phase2_analysis": {
            "required_agent_statuses": ["completed"],
            "min_completed_agents": 3,  # 至少3个分析Agent完成
            "description": "深度分析完成（至少3个Agent成功）",
        },
        "phase3_writing": {
            "required_outputs": ["article.md"],
            "min_article_bytes": 5000,  # 文章至少5KB
            "description": "文章撰写完成（至少5000字节）",
        },
        "phase4_verification": {
            "required_outputs": ["hallucination_report.json"],
            "must_pass": True,  # 幻觉检测必须PASS
            "description": "质量验证通过",
        },
        "phase5_output": {
            "required_outputs": ["final_article.md"],
            "description": "最终输出已生成",
        },
    }

    def __init__(self, topic: str, date: str = None, analysis_dir: str = None):
        self.topic = topic
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at

        # 分析输出目录
        if analysis_dir:
            self.analysis_dir = analysis_dir
        else:
            safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:50])
            self.analysis_dir = os.path.join(
                os.path.dirname(STATE_DIR), f"{safe_topic}_{self.date}"
            )

        self.current_phase = None
        self.phases_completed = []
        self.phases_failed = []
        self.agents: dict[str, AgentStatus] = {}  # phase -> list of agent names, keyed by "phase:name"
        self.phase_outputs: dict[str, list] = {}  # phase -> list of output files
        self.mode = "full"  # full/quick/risk/compete
        self.metadata = {}

    def start_phase(self, phase: str):
        """开始一个新阶段"""
        if phase not in self.PHASES:
            raise ValueError(f"Unknown phase: {phase}")
        self.current_phase = phase
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        print(f">> 阶段开始: {phase}")

    def register_agent(self, name: str, model: str = "inherit", expected_minutes: int = 40) -> AgentStatus:
        """注册一个Agent到当前阶段"""
        if not self.current_phase:
            raise ValueError("No active phase. Call start_phase() first.")
        key = f"{self.current_phase}:{name}"
        agent = AgentStatus(name, model, expected_minutes)
        self.agents[key] = agent
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return agent

    def start_agent(self, name: str):
        """标记Agent开始运行"""
        key = f"{self.current_phase}:{name}"
        if key in self.agents:
            self.agents[key].start()
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def complete_agent(self, name: str, output_file: str = None):
        """标记Agent完成"""
        key = f"{self.current_phase}:{name}"
        if key in self.agents:
            self.agents[key].complete(output_file)
            if output_file:
                self.phase_outputs.setdefault(self.current_phase, []).append(output_file)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()

    def fail_agent(self, name: str, error: str):
        """标记Agent失败"""
        key = f"{self.current_phase}:{name}"
        if key in self.agents:
            self.agents[key].fail(error)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()

    def get_running_agents(self) -> list[AgentStatus]:
        """获取当前正在运行的Agent"""
        return [a for a in self.agents.values() if a.status == AgentStatus.RUNNING]

    def get_overdue_agents(self) -> list[AgentStatus]:
        """获取超时的Agent"""
        return [a for a in self.agents.values() if a.is_overdue()]

    def get_critical_agents(self) -> list[AgentStatus]:
        """获取严重超时的Agent（需要kill）"""
        return [a for a in self.agents.values() if a.is_critical_overdue()]

    def get_phase_agents(self, phase: str = None) -> list[AgentStatus]:
        """获取某阶段的所有Agent"""
        phase = phase or self.current_phase
        prefix = f"{phase}:"
        return [a for k, a in self.agents.items() if k.startswith(prefix)]

    def get_phase_summary(self, phase: str = None) -> dict:
        """获取某阶段的执行摘要"""
        agents = self.get_phase_agents(phase)
        return {
            "phase": phase or self.current_phase,
            "total": len(agents),
            "completed": sum(1 for a in agents if a.status == AgentStatus.COMPLETED),
            "failed": sum(1 for a in agents if a.status == AgentStatus.FAILED),
            "running": sum(1 for a in agents if a.status == AgentStatus.RUNNING),
            "pending": sum(1 for a in agents if a.status == AgentStatus.PENDING),
        }

    def verify_phase_gate(self, phase: str = None) -> tuple[bool, str]:
        """验证阶段门：检查是否满足进入下一阶段的条件"""
        phase = phase or self.current_phase
        gate = self.PHASE_GATES.get(phase)
        if not gate:
            return True, f"No gate defined for {phase}"

        # 检查Agent完成度
        if "min_completed_agents" in gate:
            agents = self.get_phase_agents(phase)
            completed = sum(1 for a in agents if a.status == AgentStatus.COMPLETED)
            min_req = gate["min_completed_agents"]
            if completed < min_req:
                return False, f"阶段{phase}：只有{completed}/{len(agents)}个Agent完成，需要至少{min_req}个"

        # 检查必需输出文件
        if "required_outputs" in gate:
            for output in gate["required_outputs"]:
                output_path = os.path.join(self.analysis_dir, output)
                if not os.path.exists(output_path):
                    return False, f"阶段{phase}：缺少必需输出文件 {output}"

        # 检查文章大小
        if "min_article_bytes" in gate:
            article_path = os.path.join(self.analysis_dir, "article.md")
            if os.path.exists(article_path):
                size = os.path.getsize(article_path)
                if size < gate["min_article_bytes"]:
                    return False, f"阶段{phase}：文章大小 {size} bytes，需要至少 {gate['min_article_bytes']} bytes"

        # 检查幻觉检测结果
        if gate.get("must_pass"):
            report_path = os.path.join(self.analysis_dir, "hallucination_report.json")
            if os.path.exists(report_path):
                try:
                    with open(report_path, "r") as f:
                        report = json.load(f)
                    if report.get("overall") != "PASS":
                        return False, f"阶段{phase}：幻觉检测未通过 (overall={report.get('overall')})"
                except (json.JSONDecodeError, KeyError):
                    return False, f"阶段{phase}：幻觉检测报告格式错误"

        return True, gate.get("description", "OK")

    def complete_phase(self, phase: str = None):
        """完成当前阶段，验证门条件"""
        phase = phase or self.current_phase
        passed, msg = self.verify_phase_gate(phase)
        if not passed:
            self.phases_failed.append(phase)
            self.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()
            raise ValueError(f"阶段门验证失败: {msg}")

        self.phases_completed.append(phase)
        self.current_phase = None
        self.updated_at = datetime.now(timezone.utc).isoformat()
        self.save()
        print(f"[OK] 阶段完成: {phase} — {msg}")

    def get_checkpoint(self) -> dict:
        """生成checkpoint数据"""
        return {
            "topic": self.topic,
            "date": self.date,
            "mode": self.mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_phase": self.current_phase,
            "phases_completed": self.phases_completed,
            "phases_failed": self.phases_failed,
            "agents": {k: v.to_dict() for k, v in self.agents.items()},
            "phase_outputs": self.phase_outputs,
            "analysis_dir": self.analysis_dir,
            "metadata": self.metadata,
        }

    def get_resume_instructions(self) -> str:
        """生成恢复指令（人类可读）"""
        lines = [
            f"# 研究任务恢复指令",
            f"主题: {self.topic}",
            f"日期: {self.date}",
            f"模式: {self.mode}",
            f"",
            f"## 已完成阶段",
        ]
        for p in self.phases_completed:
            lines.append(f"- [OK] {p}")
        for p in self.phases_failed:
            lines.append(f"- [X] {p}")

        if self.current_phase:
            lines.append(f"")
            lines.append(f"## 当前阶段: {self.current_phase}")
            summary = self.get_phase_summary()
            lines.append(f"- 完成: {summary['completed']}/{summary['total']}")
            lines.append(f"- 失败: {summary['failed']}")
            lines.append(f"- 运行中: {summary['running']}")

            # 列出失败的Agent（需要重试）
            for a in self.get_phase_agents():
                if a.status == AgentStatus.FAILED:
                    lines.append(f"  - [X] {a.name}: {a.error} (重试 {a.retry_count}/{a.max_retries})")

        return "\n".join(lines)

    def save(self):
        """保存状态到文件"""
        os.makedirs(STATE_DIR, exist_ok=True)
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in self.topic[:50])
        state_file = os.path.join(STATE_DIR, f"{safe_topic}_{self.date}.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(self.get_checkpoint(), f, ensure_ascii=False, indent=2)
        # 同时保存到分析目录
        analysis_state = os.path.join(self.analysis_dir, "checkpoint.json")
        os.makedirs(self.analysis_dir, exist_ok=True)
        with open(analysis_state, "w", encoding="utf-8") as f:
            json.dump(self.get_checkpoint(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, topic: str, date: str = None) -> "ResearchState":
        """从文件加载状态"""
        date = date or datetime.now().strftime("%Y-%m-%d")
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:50])
        state_file = os.path.join(STATE_DIR, f"{safe_topic}_{date}.json")
        if not os.path.exists(state_file):
            raise FileNotFoundError(f"State file not found: {state_file}")
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = cls(data["topic"], data["date"], data.get("analysis_dir"))
        state.mode = data.get("mode", "full")
        state.current_phase = data.get("current_phase")
        state.phases_completed = data.get("phases_completed", [])
        state.phases_failed = data.get("phases_failed", [])
        state.metadata = data.get("metadata", {})
        state.phase_outputs = data.get("phase_outputs", {})
        for k, v in data.get("agents", {}).items():
            state.agents[k] = AgentStatus.from_dict(v)
        return state

    @classmethod
    def load_latest(cls, topic: str) -> "ResearchState":
        """加载最新的状态文件（自动找日期）"""
        safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:50])
        pattern = f"{safe_topic}_"
        if not os.path.exists(STATE_DIR):
            raise FileNotFoundError(f"State dir not found: {STATE_DIR}")
        files = [f for f in os.listdir(STATE_DIR) if f.startswith(pattern) and f.endswith(".json")]
        if not files:
            raise FileNotFoundError(f"No state files found for topic: {topic}")
        latest = sorted(files)[-1]
        date = latest.replace(pattern, "").replace(".json", "")
        return cls.load(topic, date)


# CLI 接口
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python state_manager.py <command> <topic> [date]")
        print("Commands: status, resume, agents, gate")
        sys.exit(1)

    cmd = sys.argv[1]
    topic = sys.argv[2]
    date = sys.argv[3] if len(sys.argv) > 3 else None

    try:
        state = ResearchState.load(topic, date) if date else ResearchState.load_latest(topic)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if cmd == "status":
        print(f"Topic: {state.topic}")
        print(f"Current phase: {state.current_phase}")
        print(f"Completed: {state.phases_completed}")
        print(f"Failed: {state.phases_failed}")
        summary = state.get_phase_summary() if state.current_phase else {}
        if summary:
            print(f"Agents: {summary['completed']}/{summary['total']} completed")
    elif cmd == "resume":
        print(state.get_resume_instructions())
    elif cmd == "agents":
        for a in state.get_phase_agents():
            print(f"  {a.name}: {a.status} (retry={a.retry_count})")
    elif cmd == "gate":
        passed, msg = state.verify_phase_gate()
        print(f"Gate: {'PASS' if passed else 'FAIL'} — {msg}")
    else:
        print(f"Unknown command: {cmd}")
