"""Audit agent: seal and inspect a package without changing its contents."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .runtime import SCRIPTS, SharedWorkspace, ToolRunner


@dataclass
class AuditResult:
    decision: str
    exit_code: int
    run_dir: Path
    package_dir: Path
    seal_exit: int
    audit_exit: int
    issue_id: str
    explanation: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "exit_code": self.exit_code,
            "run_dir": str(self.run_dir),
            "package_dir": str(self.package_dir),
            "seal_exit": self.seal_exit,
            "audit_exit": self.audit_exit,
            "issue_id": self.issue_id,
            "explanation": self.explanation,
        }


class AuditAgent:
    """Runs deterministic seal/audit commands and reports the evidence.

    The agent may explain or recommend rework, but it never edits package
    contents and cannot turn a failed audit into a pass.
    """

    name = "audit_agent"

    def __init__(self, workspace: SharedWorkspace):
        self.workspace = workspace
        self.tools = ToolRunner(workspace)

    def evaluate(self, run_dir: Path | str, package_dir: Path | str) -> AuditResult:
        state = self.workspace.state()
        if state["stage"] not in {
            "gate_approved",
            "gate_partial_blocked",
            "audit_violation",
            "audit_error",
        }:
            raise RuntimeError(
                f"当前阶段 {state['stage']} 不允许审计；"
                "审计员只接受已批准或待返工的技能包。"
            )

        run_dir = Path(run_dir).resolve()
        package_dir = Path(package_dir).resolve()
        package_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.transition("audit_pending", "audit_agent_started")
        self.workspace.update_agent(self.name, status="sealing")

        seal = self.tools.run(
            self.name,
            SCRIPTS / "guard.py",
            ["seal", "--run", str(run_dir), "--package", str(package_dir)],
        )
        if seal.exit_code != 0:
            result = AuditResult(
                decision="audit_error",
                exit_code=seal.exit_code,
                run_dir=run_dir,
                package_dir=package_dir,
                seal_exit=seal.exit_code,
                audit_exit=-1,
                issue_id="",
                explanation=seal.stdout.strip() or seal.stderr.strip(),
            )
            self._finish(result)
            return result

        self.workspace.update_agent(self.name, status="auditing")
        audit = self.tools.run(
            self.name,
            SCRIPTS / "guard.py",
            ["audit", "--run", str(run_dir), "--package", str(package_dir)],
        )
        audit_file = package_dir / "audit.json"
        issue_id = ""
        if audit_file.exists():
            try:
                issue_id = json.loads(
                    audit_file.read_text(encoding="utf-8")
                ).get("issue_id", "")
            except (json.JSONDecodeError, OSError):
                issue_id = ""

        decision = "audit_passed" if audit.exit_code == 0 else "audit_violation"
        result = AuditResult(
            decision=decision,
            exit_code=audit.exit_code,
            run_dir=run_dir,
            package_dir=package_dir,
            seal_exit=seal.exit_code,
            audit_exit=audit.exit_code,
            issue_id=issue_id,
            explanation=audit.stdout.strip() or audit.stderr.strip(),
        )
        self._finish(result)
        return result

    def _finish(self, result: AuditResult) -> None:
        payload = result.payload()
        summary_path = self.workspace.root / "audit_summary.json"
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        stage = result.decision
        self.workspace.transition(stage, result.decision)
        self.workspace.record_audit(payload)
        self.workspace.update_artifact("audit_run", result.run_dir)
        self.workspace.update_artifact("audit_summary", summary_path)
        self.workspace.update_artifact("package", result.package_dir)
        self.workspace.update_agent(
            self.name,
            status=result.decision,
            exit_code=result.exit_code,
            issue_id=result.issue_id,
        )
        self.workspace.send(self.name, "coordinator", "audit_result", payload)
