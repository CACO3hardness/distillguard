"""Message router connecting the declaration and gate agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .declaration_agent import DeclarationAgent
from .gate_agent import GateAgent, GateResult
from .runtime import SharedWorkspace


class MultiAgentCoordinator:
    """Route messages while leaving material decisions to the specialist agents."""

    def __init__(self, workspace: Path | str, src: Path | str):
        self.workspace = SharedWorkspace(workspace)
        self.workspace.initialize("将离职材料申报并送入 DistillGuard 闸门", src)
        self.declaration = DeclarationAgent(self.workspace)
        self.gate = GateAgent(self.workspace)

    def run(
        self,
        answers: dict[str, Any] | Path | str | None = None,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> GateResult:
        state = self.workspace.state()
        if state["stage"] != "initialized":
            raise RuntimeError(
                f"工作区已经运行过，当前阶段为 {state['stage']}；"
                "如需待补项重跑，请使用 revise。"
            )
        src = state["src"]
        self.workspace.send(
            "coordinator",
            "declaration_agent",
            "task",
            {"goal": state["objective"], "src": src},
        )
        survey = self.declaration.survey(src)
        output_fn(f"申报 Agent 扫描到 {len(survey.materials)} 份材料。")

        if answers is None:
            answers = self.collect_answers(survey.materials, input_fn, output_fn)
        manifest = self.declaration.build(answers)
        if not manifest.ok:
            output_fn(manifest.output.strip())
            raise RuntimeError("材料申报尚未完成")

        output_fn("申报完成，已移交给闸门 Agent。")
        result = self._evaluate_gate(manifest.manifest_path, src)
        self._report_result(result, output_fn)
        return result

    def revise(
        self,
        answers: dict[str, Any] | Path | str,
        output_fn: Callable[[str], None] = print,
    ) -> GateResult:
        state = self.workspace.state()
        if state["stage"] != "awaiting_consent_or_revision":
            raise RuntimeError(
                f"当前阶段 {state['stage']} 不允许修订；"
                "只有闸门挂起后才能提交下一轮材料。"
            )
        draft = self.workspace.root / "declaration" / "draft.yaml"
        if not draft.exists():
            raise RuntimeError("找不到上一轮申报草稿，无法继续修订")

        round_number = self.workspace.begin_round()
        self.workspace.update_agent(
            self.declaration.name,
            status="revising",
            revision_round=round_number,
        )
        self.workspace.send(
            "coordinator",
            self.declaration.name,
            "revision_task",
            {"round": round_number, "request": "只补充上一轮 pending 项所需事实"},
        )
        manifest = self.declaration.build(answers)
        if not manifest.ok:
            raise RuntimeError("修订后的材料清单仍未完成")

        output_fn(f"申报 Agent 已提交第 {round_number} 轮材料清单。")
        result = self._evaluate_gate(manifest.manifest_path, state["src"])
        self._report_result(result, output_fn)
        return result

    def _evaluate_gate(self, manifest: Path, src: Path | str) -> GateResult:
        round_number = int(self.workspace.state()["round"])
        run_dir = self.workspace.root / "gate" / f"round-{round_number}"
        return self.gate.evaluate(manifest, src, run_dir)

    def _report_result(
        self,
        result: GateResult,
        output_fn: Callable[[str], None],
    ) -> None:
        summary = result.summary
        output_fn(
            f"第 {result.round} 轮闸门结果："
            f"总计 {summary['total']} 份，approved {summary['approved']}，"
            f"pending {summary['pending']}，blocked {summary['blocked']}。"
        )

        if result.decision == "pending":
            output_fn(self.declaration.respond_to_feedback(
                self.gate.summary_payload(result)
            ))
        elif result.explanation:
            output_fn(result.explanation)

        self.workspace.send(
            "coordinator",
            "user",
            "final",
            self.gate.summary_payload(result),
        )

    @staticmethod
    def collect_answers(
        materials: list[dict[str, Any]],
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
    ) -> dict[str, dict[str, str]]:
        answers: dict[str, dict[str, str]] = {}
        choices = {
            "author": ("只有我", "只有别人", "我和别人都有"),
            "third_party": ("有", "没有", "不确定"),
            "nature": ("流程或公开资料", "个人判断或方法", "私人或与工作无关"),
        }
        values = {
            "author": ("self", "other", "mixed"),
            "third_party": ("yes", "no", "unsure"),
            "nature": ("process", "personal", "private"),
        }
        questions = {
            "author": "这份材料是谁写的？",
            "third_party": "里面有没有别人的话、姓名、联系方式或隐私？",
            "nature": "这份材料主要是什么内容？",
        }

        for material in materials:
            output_fn(f"\n{material['id']}  {material['path']}")
            entry: dict[str, str] = {}
            for key in ("author", "third_party", "nature"):
                output_fn(questions[key])
                for index, label in enumerate(choices[key], 1):
                    output_fn(f"  {index}. {label}")
                raw = input_fn("请选择 1-3：").strip()
                if raw not in ("1", "2", "3"):
                    raise ValueError(f"{material['id']} 的 {key} 必须选择 1-3")
                entry[key] = values[key][int(raw) - 1]
            answers[material["id"]] = entry
        return answers
