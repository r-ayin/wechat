#!/usr/bin/env python3
"""MIN-05：executor 路径解析与实例化测试（可移植，无硬编码路径）。

旧实现硬编码 Windows 路径 E:\\openclaw\\... 且只验证构造不抛错。
现用 __file__ 相对定位技能根，并增加 skill_dir、output_dir、模式检测断言。
"""
import os
import sys

_SKILL_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_SKILL_ROOT, "scripts", "orchestration"))

from executor import GodtierExecutor  # noqa: E402


def test_instantiation_and_paths():
    e = GodtierExecutor("测试选题", mode="quick", research_mode="general")
    # skill_dir 应解析到技能根（含 detectors/ workflows/）
    assert os.path.basename(e.skill_dir) == "godtier-deep-research", \
        f"skill_dir 解析错误: {e.skill_dir}"
    assert os.path.isdir(os.path.join(e.skill_dir, "detectors")), "detectors 目录缺失"
    assert os.path.isdir(os.path.join(e.skill_dir, "workflows")), "workflows 目录缺失"
    assert e.research_mode == "general"
    assert os.path.isdir(e.output_dir), "output_dir 未创建"
    return e


def test_mode_detection():
    e_fin = GodtierExecutor("英伟达财报分析", research_mode="auto")
    assert e_fin.research_mode == "finance", f"应检测为 finance，实际 {e_fin.research_mode}"
    e_gen = GodtierExecutor("高考改革对社会流动的影响", research_mode="auto")
    assert e_gen.research_mode == "general", f"应检测为 general，实际 {e_gen.research_mode}"


if __name__ == "__main__":
    e = test_instantiation_and_paths()
    test_mode_detection()
    print("Executor OK — skill_dir:", e.skill_dir)
    print("mode detection OK")
