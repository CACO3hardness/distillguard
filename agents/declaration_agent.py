"""Declaration agent: collect material facts and produce a gate-ready manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .runtime import SCRIPTS, SharedWorkspace, ToolRunner


@dataclass
class SurveyResult:
    draft_path: Path
    questions_path: Path
    materials: list[dict[str, Any]]


@dataclass
class ManifestResult:
    ok: bool
    manifest_path: Path
    exit_code: int
    output: str


class DeclarationAgent:
    """Owns only material intake and manifest construction.

    It cannot approve or block a material. Once the manifest is complete it
    hands control to the gate agent.
    """

    name = "declaration_agent"

    def __init__(self, workspace: SharedWorkspace):
        self.workspace = workspace
        self.tools = ToolRunner(workspace)
        self.out_dir = workspace.root / "declaration"

    def survey(self, src: Path | str) -> SurveyResult:
        self.workspace.update_agent(self.name, status="surveying")
        result = self.tools.run(
            self.name,
            SCRIPTS / "guide.py",
            ["survey", "--src", str(Path(src).resolve()), "--out", str(self.out_dir)],
        )
        if result.exit_code != 0:
            self.workspace.update_agent(
                self.name,
                status="error",
                exit_code=result.exit_code,
                error=result.stderr or result.stdout,
            )
            raise RuntimeError(result.stderr or result.stdout)

        draft_path = self.out_dir / "draft.yaml"
        questions_path = self.out_dir / "questions.md"
        draft = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
        materials = draft.get("materials", [])
        self.workspace.update_agent(
            self.name,
            status="awaiting_answers",
            material_count=len(materials),
        )
        self.workspace.transition("declaration_awaiting_answers", "survey_completed")
        self.workspace.update_artifact("draft", draft_path)
        self.workspace.update_artifact("questions", questions_path)
        return SurveyResult(draft_path, questions_path, materials)

    def build(self, answers: dict[str, Any] | Path | str) -> ManifestResult:
        self.workspace.update_agent(self.name, status="building_manifest")
        round_number = int(self.workspace.state()["round"])
        round_dir = self.out_dir / f"round-{round_number}"
        round_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(answers, dict):
            answers_path = round_dir / "answers.yaml"
            answers_path.write_text(
                yaml.safe_dump(answers, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        else:
            answers_path = Path(answers).resolve()

        manifest_path = round_dir / "materials.yaml"
        result = self.tools.run(
            self.name,
            SCRIPTS / "guide.py",
            [
                "build",
                "--draft",
                str(self.out_dir / "draft.yaml"),
                "--answers",
                str(answers_path),
                "--out",
                str(manifest_path),
            ],
        )
        if result.exit_code != 0:
            self.workspace.update_agent(
                self.name,
                status="needs_more_answers",
                exit_code=result.exit_code,
                output=result.stdout,
            )
            self.workspace.transition(
                "declaration_needs_more_answers", "manifest_fields_missing"
            )
            return ManifestResult(False, manifest_path, result.exit_code, result.stdout)

        self.workspace.update_agent(
            self.name,
            status="handoff_ready",
            exit_code=0,
        )
        self.workspace.transition("manifest_ready", "manifest_completed")
        self.workspace.update_artifact("answers", answers_path)
        self.workspace.update_artifact("manifest", manifest_path)
        self.workspace.send(
            self.name,
            "gate_agent",
            "handoff",
            {
                "manifest": str(manifest_path),
                "round": round_number,
                "message": "材料已申报，请执行入库闸；不得替用户补填未知事实。",
            },
        )
        return ManifestResult(True, manifest_path, 0, result.stdout)

    def respond_to_feedback(self, gate_result: dict[str, Any]) -> str:
        pending = gate_result.get("pending", [])
        if not pending:
            return "闸门没有返回需要申报 Agent 处理的挂起项。"

        lines = ["闸门返回了需要补充的材料，下一轮只补充下列事实："]
        for item in pending:
            gaps = "、".join(item.get("gaps", [])) or "核查同意证据"
            lines.append(f"- {item['id']} {item['path']}：{gaps}")
        text = "\n".join(lines)
        self.workspace.update_agent(
            self.name,
            status="revision_requested",
            pending_ids=[item["id"] for item in pending],
        )
        self.workspace.transition(
            "awaiting_consent_or_revision", "gate_requested_revision"
        )
        self.workspace.send(
            self.name,
            "coordinator",
            "user_action_required",
            {"message": text, "pending": pending},
        )
        return text
