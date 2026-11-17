"""Gate agent: invoke deterministic checks and interpret the result."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .runtime import SCRIPTS, SharedWorkspace, ToolRunner


@dataclass
class GateResult:
    decision: str
    exit_code: int
    run_dir: Path
    summary: dict[str, int]
    approved: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    blocked: list[dict[str, Any]]
    explanation: str = ""
    round: int = 1


class GateAgent:
    """Owns gate execution and remediation messages, never overrides rules."""

    name = "gate_agent"

    def __init__(self, workspace: SharedWorkspace):
        self.workspace = workspace
        self.tools = ToolRunner(workspace)

    def evaluate(self, manifest: Path | str, src: Path | str, run_dir: Path | str) -> GateResult:
        self.workspace.update_agent(self.name, status="evaluating")
        if self.workspace.state()["stage"] == "initialized":
            self.workspace.transition(
                "manifest_ready", "gate_started_with_external_manifest"
            )
        run_dir = Path(run_dir).resolve()
        result = self.tools.run(
            self.name,
            SCRIPTS / "guard.py",
            [
                "gate",
                "--manifest",
                str(Path(manifest).resolve()),
                "--src",
                str(Path(src).resolve()),
                "--out",
                str(run_dir),
            ],
        )

        run_file = run_dir / "run.json"
        rows = []
        if run_file.exists():
            rows = json.loads(run_file.read_text(encoding="utf-8")).get("materials", [])
        approved = [row for row in rows if row.get("result") == "approved"]
        pending = [row for row in rows if row.get("result") == "pending"]
        blocked = [row for row in rows if row.get("result") == "blocked"]
        summary = {
            "total": len(rows),
            "approved": len(approved),
            "pending": len(pending),
            "blocked": len(blocked),
        }

        if result.exit_code == 0:
            decision = "approved"
            stage = "gate_approved"
        elif result.exit_code == 3:
            decision = "pending"
            stage = "gate_pending"
        elif result.exit_code == 2:
            decision = "blocked" if not approved else "partial_blocked"
            stage = "gate_blocked"
        else:
            decision = "error"
            stage = "gate_error"

        explanation = ""
        if result.exit_code in (2, 3):
            explain = self.tools.run(
                self.name,
                SCRIPTS / "guide.py",
                ["explain", "--run", str(run_dir)],
            )
            explanation = explain.stdout.strip()

        gate_result = GateResult(
            decision=decision,
            exit_code=result.exit_code,
            run_dir=run_dir,
            summary=summary,
            approved=approved,
            pending=pending,
            blocked=blocked,
            explanation=explanation,
            round=int(self.workspace.state()["round"]),
        )
        payload = self.summary_payload(gate_result)
        summary_path = self.workspace.root / "gate_summary.json"
        summary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.workspace.update_artifact("gate_run", run_dir)
        self.workspace.update_artifact("gate_summary", summary_path)
        self.workspace.transition(stage, f"gate_{decision}")
        self.workspace.record_gate(payload)
        self.workspace.update_agent(
            self.name,
            status=decision,
            exit_code=result.exit_code,
            summary=summary,
        )

        if decision == "pending":
            self.workspace.send(self.name, "declaration_agent", "revision_request", payload)
        else:
            self.workspace.send(self.name, "coordinator", "gate_result", payload)
        return gate_result

    @staticmethod
    def summary_payload(result: GateResult) -> dict[str, Any]:
        return {
            "decision": result.decision,
            "exit_code": result.exit_code,
            "round": result.round,
            "summary": result.summary,
            "approved": [
                {"id": row["id"], "path": row["path"], "tier": row.get("tier")}
                for row in result.approved
            ],
            "pending": [
                {
                    "id": row["id"],
                    "path": row["path"],
                    "gaps": row.get("gaps", []),
                    "flags": row.get("flags", []),
                }
                for row in result.pending
            ],
            "blocked": [
                {
                    "id": row["id"],
                    "path": row["path"],
                    "flags": row.get("flags", []),
                    "tier_reason": row.get("tier_reason", ""),
                }
                for row in result.blocked
            ],
            "explanation": result.explanation,
        }
