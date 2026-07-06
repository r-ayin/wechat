#!/usr/bin/env python3
"""pipeline.py — 微信管线确定性编排引擎（统一入口）

被任意 agent（Claude Code / WorkBuddy / 其他）调用。纯 Python，零运行时依赖：
状态/路由/门禁调度全在此，LLM 创意工作由调用方派发隔离子 agent 完成。

agent-loop 契约：
  1. python scripts/pipeline.py init <topic> [--from N] [--draft] [--mode auto|manual] [--brief P]
  2. 循环：
     STEP = python scripts/pipeline.py next <topic>            # 首个未完成步骤
     若 STEP.done == true → 结束（看 STEP.halted 判断成败）
     若 STEP.kind in (gate_check, gate_verify, code) → bash STEP.cmd → mark
     若 STEP.kind == subagent → 派发隔离子 agent，goal="读 STEP.task_file 执行，产出写 STEP.output"
                               → 子 agent 完成后（不回传内容）→ mark
  3. python scripts/pipeline.py mark <topic> <step_id> <completed|failed> [--note "..."]

主上下文只持 step 元数据（id/kind/cmd/task_file/output + pass/fail），不接触任何内容。
"""

from __future__ import annotations
import json
import os
import hashlib
import subprocess
import sys
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path

# 项目根
_ROOT = Path(__file__).resolve().parent.parent
_STATE_DIR = _ROOT / "output" / "state"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

# 引入步骤物化器
sys.path.insert(0, str(_ROOT / "scripts"))
import steps  # noqa: E402

PHASE_ORDER = ["0", "1", "2", "3", "3.5", "4"]
# gate_verify 对这些 phase 有实质检查；phase 4 的 verify 是 no-op，不参与自动恢复
AUTORESUME_PHASES = ["0", "1", "2", "3", "3.5"]


def _slugify(topic: str) -> str:
    """topic → slug。保留 ascii 片段；纯中文/过短用 md5 确定性哈希（跨进程稳定，
    不同于内置 hash() 受 PYTHONHASHSEED 影响）。优先用 --slug 显式传入。"""
    s = topic.strip().lower()
    s = re.sub(r'[^a-z0-9\-]+', '-', s)
    s = re.sub(r'-+', '-', s).strip('-')
    if len(s) >= 3:
        return s
    h = hashlib.md5(topic.encode('utf-8')).hexdigest()[:8]
    return f"topic-{h}"


def _state_path(slug: str, date: str) -> Path:
    return _STATE_DIR / f"{slug}_{date}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(slug: str, date: str | None = None) -> dict:
    if date:
        p = _state_path(slug, date)
        if not p.exists():
            raise SystemExit(f"❌ 找不到 state: {p}（先 init）")
        return json.loads(p.read_text(encoding="utf-8"))
    # 未指定 date：取该 slug 最新 state
    matches = sorted(_STATE_DIR.glob(f"{slug}_*.json"), reverse=True)
    if not matches:
        raise SystemExit(f"❌ 找不到 {slug} 的 state（先 init）")
    return json.loads(matches[0].read_text(encoding="utf-8"))


def _save(state: dict) -> None:
    state["updated_at"] = _now()
    p = _state_path(state["slug"], state["date"])
    data = json.dumps(state, ensure_ascii=False, indent=2)
    # 原子写：tmp + fsync + os.replace，防崩溃半写致 state JSON 残缺、next/status
    # json.loads 抛错、管线恢复断链（audit-2026-07-05-001 WM-PIP-02）。init 有 .bak 但
    # _save 每 step 都调，半写窗口远大于 init；tmp 与 p 同目录保证 os.replace 原子。
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    with open(tmp, "rb") as _fh:
        os.fsync(_fh.fileno())
    os.replace(tmp, p)


def _phase_idx(phase: str) -> int:
    return PHASE_ORDER.index(phase)


def _run_gate(action: str, phase: str, slug: str, date: str,
              min_bytes: int | None = None) -> tuple[int, str]:
    """运行 pipeline-gate.sh，返回 (exit_code, stdout). 不抛异常。

    min_bytes 非 None 时注入 WECHAT_MIN_BYTES env（draft 档生效，PIPE-02 修复）。
    timeout=120s 防 pipeline-gate.sh 卡死挂住整条管线（WM-M-001 audit finding）。
    超时返回 exit_code=124 + 描述性消息，调用方按失败处理即可。
    """
    env = os.environ.copy()
    if min_bytes is not None:
        env["WECHAT_MIN_BYTES"] = str(min_bytes)
    cmd = ["bash", str(_ROOT / "scripts" / "pipeline-gate.sh"), action, phase, slug, date]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT), env=env,
                           timeout=120)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired as e:
        # 超时：stdout/stderr 可能部分可用，拼起来给调用方看；exit 124 与 GNU timeout 一致
        partial = ((e.stdout or b"").decode("utf-8", errors="replace")
                   + (e.stderr or b"").decode("utf-8", errors="replace")).strip()
        msg = f"[gate timeout after 120s] action={action} phase={phase} slug={slug}"
        if partial:
            msg += f"\n{partial}"
        return 124, msg


def _resolve_article(slug: str, date: str) -> str:
    """解析 Phase 3 文章路径（hot/ 或 evergreen/，文件名含中文标题）。"""
    matches = sorted(_ROOT.glob(f"output/wechat_articles/*/{slug}_*_{date}*.md"))
    return str(matches[0].relative_to(_ROOT)) if matches else ""


# =========================================================================
# 命令：init
# =========================================================================

def cmd_init(args) -> None:
    topic = args.topic
    slug = args.slug or _slugify(topic)
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    min_bytes = 12000 if args.draft else int(os.environ.get("WECHAT_MIN_BYTES", "45000"))

    # 构建步骤
    step_list = steps.build_steps(slug, date, args.brief, args.mode, min_bytes)

    # --from 地板 + 传递式前置校验（G1-01：跳过之前 phase 前必须确认它们已通过 verify）
    from_idx = _phase_idx(args.from_phase) if args.from_phase else 0
    if from_idx > 0:
        for phase in PHASE_ORDER:
            if _phase_idx(phase) >= from_idx:
                break
            if phase not in AUTORESUME_PHASES:
                continue  # phase 4 不参与
            rc, out = _run_gate("verify", phase, slug, date, min_bytes)
            if rc != 0:
                print(f"❌ 前置 Phase {phase} 未通过 verify，不能从 Phase {args.from_phase} 恢复：")
                print(f"   {out}")
                print("   先完成该阶段，或 --draft 放宽字数门禁，或从更早 phase 开始。")
                sys.exit(2)
    for s in step_list:
        if _phase_idx(s["phase"]) < from_idx:
            s["status"] = "skipped"

    # 自动恢复：对 from 及之后的 phase，若 gate_verify 通过则标记该 phase 全部 completed
    for phase in PHASE_ORDER:
        if _phase_idx(phase) < from_idx:
            continue
        if phase not in AUTORESUME_PHASES:
            continue  # phase 4 不自动恢复
        rc, _ = _run_gate("verify", phase, slug, date, min_bytes)
        if rc == 0:
            for s in step_list:
                if s["phase"] == phase:
                    s["status"] = "completed"
        else:
            break  # 第一个未通过的 phase 即恢复点，其后不再检查

    state = {
        "topic": topic, "slug": slug, "date": date,
        "mode": args.mode, "brief_path": args.brief,
        "draft": args.draft, "min_bytes": min_bytes,
        "retries": 0,
        "created_at": _now(), "updated_at": _now(),
        "steps": step_list,
    }
    # 覆盖保护（PIPE-05）：旧 state 备份
    sp = _state_path(slug, date)
    if sp.exists():
        bak = sp.with_name(sp.name + ".bak")
        sp.rename(bak)
        print(f"[init] 已有 state，旧版备份到 {bak.name}")
    _save(state)
    pending = sum(1 for s in step_list if s["status"] == "pending")
    completed = sum(1 for s in step_list if s["status"] == "completed")
    skipped = sum(1 for s in step_list if s["status"] == "skipped")
    print(f"[init] {slug} {date}  mode={args.mode} draft={args.draft} min_bytes={min_bytes}")
    print(f"  steps: {len(step_list)} (completed={completed} pending={pending} skipped={skipped})")
    print(f"  state: {_state_path(slug, date).relative_to(_ROOT)}")
    print(f"  下一步: python scripts/pipeline.py next {slug}")


# =========================================================================
# 命令：next
# =========================================================================

def cmd_next(args) -> None:
    state = _load(args.topic, args.date)

    # 任一 failed → 停止
    failed = [s for s in state["steps"] if s["status"] == "failed"]
    if failed:
        print(json.dumps({"done": True, "halted": True,
                          "failed_step": failed[0]["id"],
                          "note": failed[0].get("note", "")},
                         ensure_ascii=False))
        return

    # 首个 pending
    step = next((s for s in state["steps"] if s["status"] == "pending"), None)
    if step is None:
        total = len(state["steps"])
        completed = sum(1 for s in state["steps"] if s["status"] == "completed")
        print(json.dumps({"done": True, "halted": False,
                          "summary": {"total": total, "completed": completed}},
                         ensure_ascii=False))
        return

    out = {"step_id": step["id"], "phase": step["phase"], "kind": step["kind"],
           "output": step.get("output")}
    if step["kind"] in ("gate_check", "gate_verify", "code"):
        cmd = step["cmd"]
        if "__ARTICLE__" in cmd:
            art = _resolve_article(state["slug"], state["date"])
            if not art:
                # WM-PIP-01：文章未解析到时阻断，不让 __ARTICLE__ 裸字面进 bash
                #（否则 argparse 读不到文件 / 残留占位符被 shell 当普通 token 执行）。
                raise SystemExit(f"❌ Phase 3 文章未找到，无法解析 __ARTICLE__：slug={state['slug']} date={state['date']}")
            # WM-PIP-01：art 来自 LLM 命名的文件名（含中文标题），可能含空格/;/$() 等元字符。
            # 裸 replace 进 bash STEP.cmd 会导致参数断裂或命令注入，必须 shell-quote。
            cmd = cmd.replace("__ARTICLE__", shlex.quote(art))
        out["cmd"] = cmd
        # PIPE-02 / H-002 fix：WECHAT_MIN_BYTES 通过 env dict 传递，不再 f-string 拼到
        # shell cmd 前缀（避免 state JSON 被污染时触发命令替换注入）。调用方（agent-loop）
        # 需用 STEP.env 设置子进程环境变量；pipeline-gate.sh 仍读 ${WECHAT_MIN_BYTES:-45000}。
        try:
            mb = int(state.get("min_bytes", 45000))
        except (TypeError, ValueError):
            mb = 45000
        out["env"] = {"WECHAT_MIN_BYTES": str(mb)}
    elif step["kind"] == "subagent":
        out["task_file"] = step["task_file"]
    print(json.dumps(out, ensure_ascii=False))


# =========================================================================
# 命令：mark
# =========================================================================

def cmd_mark(args) -> None:
    state = _load(args.topic, args.date)
    step = next((s for s in state["steps"] if s["id"] == args.step_id), None)
    if step is None:
        raise SystemExit(f"❌ 未知 step_id: {args.step_id}")

    step["status"] = args.result
    if args.note:
        step["note"] = args.note
    step["marked_at"] = _now()

    # judge 失败 → 动态插入修复循环（最多 3 轮）
    if step.get("is_judge") and args.result == "failed":
        state["retries"] = state.get("retries", 0) + 1
        if state["retries"] <= 3:
            # 可恢复失败：改 retrying，让 next 继续到刚插入的修复步骤
            step["status"] = "retrying"
            rem = steps.build_remediation_steps(state["slug"], state["date"], state["retries"])
            # 插入到 3.5.verify 之前
            v_idx = next((i for i, s in enumerate(state["steps"])
                          if s["id"] == "3.5.verify"), len(state["steps"]))
            for j, r in enumerate(rem):
                state["steps"].insert(v_idx + j, r)
            print(f"[mark] {args.step_id} retrying → 插入第 {state['retries']} 轮修复循环 "
                  f"({len(rem)} 步)")
        else:
            # 重试耗尽：保持 failed，管线停止
            step["note"] = (step.get("note", "") + " | 3 轮修复耗尽，FALSIFIED 未清零").strip()
            print(f"[mark] {args.step_id} failed → 3 轮修复耗尽，管线在此停止")
    else:
        print(f"[mark] {args.step_id} → {args.result}")

    _save(state)


# =========================================================================
# 命令：status
# =========================================================================

def cmd_status(args) -> None:
    if not args.topic:
        # 无 topic：列出所有 state
        for p in sorted(_STATE_DIR.glob("*.json")):
            print(f"  {p.name}")
        return
    state = _load(args.topic, args.date)
    print(f"\n{'='*60}\n  管线状态  {state['slug']} {state['date']}  "
          f"mode={state['mode']} draft={state['draft']}\n{'='*60}")
    for phase in PHASE_ORDER:
        psteps = [s for s in state["steps"] if s["phase"] == phase]
        if not psteps:
            continue
        statuses = [s["status"] for s in psteps]
        if all(st == "completed" for st in statuses):
            mark = "✅"
        elif any(st == "failed" for st in statuses):
            mark = "❌"
        elif all(st == "skipped" for st in statuses):
            mark = "⏭️"
        elif any(st == "pending" for st in statuses):
            mark = "⏳"
        else:
            mark = "🔄"
        pending = sum(1 for st in statuses if st == "pending")
        print(f"  {mark} Phase {phase}: {statuses.count('completed')}/{len(statuses)} done"
              + (f" ({pending} pending)" if pending else ""))
    print()


# =========================================================================
# 命令：plan
# =========================================================================

def cmd_plan(args) -> None:
    state = _load(args.topic, args.date)
    from_idx = _phase_idx(args.from_phase) if args.from_phase else 0
    to_idx = _phase_idx(args.to) if args.to else len(PHASE_ORDER) - 1
    rows = [s for s in state["steps"]
            if from_idx <= _phase_idx(s["phase"]) <= to_idx
            and s["status"] == "pending"]
    print(json.dumps({"topic": state["slug"], "pending_count": len(rows),
                      "steps": [{"id": s["id"], "phase": s["phase"], "kind": s["kind"]}
                                for s in rows]}, ensure_ascii=False, indent=2))


# =========================================================================
# 命令：tool（统一包装独立优化工具）
# =========================================================================

# 已知独立工具白名单（cmd_tool 仅允许调度这些，防路径遍历与未授权执行）
_ALLOWED_TOOLS = frozenset({
    "bing_search", "bocha_search", "brave_search", "competitor_analyzer",
    "daily_report", "deepseek_refine", "ending_detector", "feedback_collector",
    "knowledge_base", "mail_push", "metrics_panel", "multi_platform",
    "persona_drift", "predictive_scanner", "qq_push", "research_cache",
    "steps", "structural_consistency_checker", "style_evolution",
    "style_fingerprint", "title_scorer",
})


def cmd_tool(args) -> None:
    """运行 scripts/ 下的独立工具（metrics_panel/feedback_collector/style_evolution/...）。
    用法: python scripts/pipeline.py tool <name> [args...]，等价于 python scripts/<name>.py [args...]
    安全：name 走白名单校验（拒 .. / 路径分隔符），rest 原样透传——subprocess.run 用
    list 形式（无 shell=True），参数中即使含 `;` `|` `&` 等也只作为字面量传给子进程，
    不被任何 shell 解释，故无需（也不应）过滤 shell 元字符（旧版 dangerous-token 过滤
    属冗余 defense-in-depth，且会误伤合法参数，已移除）。
    """
    name = args.name
    if ".." in name or "/" in name or "\\" in name:
        raise SystemExit(f"❌ 非法工具名: {name!r}（含路径分隔符或 ..）")
    if name not in _ALLOWED_TOOLS:
        allowed = ", ".join(sorted(_ALLOWED_TOOLS))
        raise SystemExit(f"❌ 未知工具: {name}（允许: {allowed}）")
    script = _ROOT / "scripts" / f"{name}.py"
    if not script.exists():
        raise SystemExit(f"❌ 工具脚本缺失: {script}")
    cmd = ["python3", str(script)] + args.rest
    r = subprocess.run(cmd, cwd=str(_ROOT))
    sys.exit(r.returncode)


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse
    p = argparse.ArgumentParser(
        description="微信管线确定性编排引擎 — 统一入口（agent-loop 驱动）")
    sub = p.add_subparsers(dest="command", required=True)

    i = sub.add_parser("init", help="初始化/恢复管线状态")
    i.add_argument("topic")
    i.add_argument("--slug")
    i.add_argument("--mode", choices=["auto", "manual"], default="auto")
    i.add_argument("--brief", default=None, help="brief 文件路径（手动模式）")
    i.add_argument("--draft", action="store_true", help="draft 档（min_bytes 降至 12000）")
    i.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")
    i.add_argument("--from", dest="from_phase", default=None, choices=PHASE_ORDER, help="从指定 phase 开始")
    i.set_defaults(func=cmd_init)

    n = sub.add_parser("next", help="输出下一个未完成步骤（agent-loop 调用）")
    n.add_argument("topic")
    n.add_argument("--date", default=None)
    n.set_defaults(func=cmd_next)

    m = sub.add_parser("mark", help="标记步骤完成/失败")
    m.add_argument("topic")
    m.add_argument("step_id")
    m.add_argument("result", choices=["completed", "failed"])
    m.add_argument("--note", default=None)
    m.add_argument("--date", default=None)
    m.set_defaults(func=cmd_mark)

    st = sub.add_parser("status", help="管线状态面板")
    st.add_argument("topic", nargs="?", default=None)
    st.add_argument("--date", default=None)
    st.set_defaults(func=cmd_status)

    pl = sub.add_parser("plan", help="输出剩余 pending 步骤")
    pl.add_argument("topic")
    pl.add_argument("--date", default=None)
    pl.add_argument("--from", dest="from_phase", default=None, choices=PHASE_ORDER)
    pl.add_argument("--to", default=None, choices=PHASE_ORDER)
    pl.set_defaults(func=cmd_plan)

    t = sub.add_parser("tool", help="运行独立优化工具(metrics_panel/feedback_collector/style_evolution/...)")
    t.add_argument("name", help="工具名（scripts/<name>.py）")
    t.add_argument("rest", nargs=argparse.REMAINDER, help="透传给工具的参数")
    t.set_defaults(func=cmd_tool)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
