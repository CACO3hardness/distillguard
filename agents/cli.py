"""Command-line entry point for the two-agent DistillGuard flow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .coordinator import MultiAgentCoordinator
from .declaration_agent import DeclarationAgent
from .gate_agent import GateAgent
from .runtime import SharedWorkspace


def print_result(result) -> None:
    payload = GateAgent.summary_payload(result)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_run(args) -> int:
    coordinator = MultiAgentCoordinator(args.workspace, args.src)
    answers = Path(args.answers) if args.answers else None
    result = coordinator.run(answers=answers)
    print(f"\nAgent 状态：{coordinator.workspace.state_path}")
    print_result(result)
    return result.exit_code


def cmd_revise(args) -> int:
    state_workspace = SharedWorkspace(args.workspace)
    state = state_workspace.state()
    coordinator = MultiAgentCoordinator(args.workspace, state["src"])
    result = coordinator.revise(Path(args.answers))
    print(f"\nAgent 状态：{coordinator.workspace.state_path}")
    print_result(result)
    return result.exit_code


def cmd_survey(args) -> int:
    workspace = SharedWorkspace(args.workspace)
    workspace.initialize("扫描材料并准备申报", args.src)
    agent = DeclarationAgent(workspace)
    result = agent.survey(args.src)
    print(f"已生成问卷：{result.questions_path}")
    print(f"已生成草稿：{result.draft_path}")
    return 0


def cmd_gate(args) -> int:
    workspace = SharedWorkspace(args.workspace)
    workspace.initialize("对现有材料清单执行入库闸", args.src)
    agent = GateAgent(workspace)
    result = agent.evaluate(args.manifest, args.src, workspace.root / "gate")
    print(f"Agent 状态：{workspace.state_path}")
    print_result(result)
    return result.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DistillGuard 多 Agent：申报 Agent → 闸门 Agent"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="执行申报和过闸；无 --answers 时进入交互问答")
    run.add_argument("--src", required=True)
    run.add_argument("--workspace", required=True)
    run.add_argument("--answers", help="已有 answers.yaml；省略则逐题提问")
    run.set_defaults(func=cmd_run)

    revise = sub.add_parser("revise", help="对 pending 工作区提交下一轮材料事实")
    revise.add_argument("--workspace", required=True)
    revise.add_argument("--answers", required=True)
    revise.set_defaults(func=cmd_revise)

    survey = sub.add_parser("survey", help="只运行申报 Agent 并生成问卷")
    survey.add_argument("--src", required=True)
    survey.add_argument("--workspace", required=True)
    survey.set_defaults(func=cmd_survey)

    gate = sub.add_parser("gate", help="只运行闸门 Agent")
    gate.add_argument("--manifest", required=True)
    gate.add_argument("--src", required=True)
    gate.add_argument("--workspace", required=True)
    gate.set_defaults(func=cmd_gate)
    return parser


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (RuntimeError, ValueError) as exc:
        print(f"Agent 运行中止：{exc}", file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
