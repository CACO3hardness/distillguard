"""Shared state, message transport and tool execution for DistillGuard agents."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
from uuid import uuid4


BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"

ALLOWED_TRANSITIONS = {
    "initialized": {"declaration_awaiting_answers", "manifest_ready"},
    "declaration_awaiting_answers": {
        "manifest_ready",
        "declaration_needs_more_answers",
    },
    "declaration_needs_more_answers": {"manifest_ready"},
    "manifest_ready": {"gate_approved", "gate_pending", "gate_blocked", "gate_error"},
    "gate_pending": {"awaiting_consent_or_revision"},
    "awaiting_consent_or_revision": {"manifest_ready"},
    "gate_blocked": set(),
    "gate_error": set(),
    "gate_approved": set(),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class ToolResult:
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str


class ToolRunner:
    """Run existing DistillGuard CLIs and record every call."""

    def __init__(self, workspace: "SharedWorkspace"):
        self.workspace = workspace

    def run(self, agent: str, script: Path, args: list[str], cwd: Path | None = None) -> ToolResult:
        command = [sys.executable, str(script), *map(str, args)]
        proc = subprocess.run(
            command,
            cwd=str(cwd or BASE),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        result = ToolResult(command, proc.returncode, proc.stdout, proc.stderr)
        self.workspace.record_tool(agent, result)
        return result


class SharedWorkspace:
    """A small append-only message log plus an atomically updated state file."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "agent_state.json"
        self.messages_path = self.root / "agent_messages.jsonl"
        self.tools_path = self.root / "agent_tools.jsonl"

    def initialize(self, objective: str, src: Path | str) -> None:
        if self.state_path.exists():
            return
        run_id = f"AG-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:6]}"
        self._write_state({
            "run_id": run_id,
            "thread_id": run_id,
            "round": 1,
            "objective": objective,
            "src": str(Path(src).resolve()),
            "stage": "initialized",
            "stage_history": [
                {"stage": "initialized", "created_at": now_iso(), "reason": "run_created"}
            ],
            "agents": {
                "declaration_agent": {"status": "idle"},
                "gate_agent": {"status": "idle"},
            },
            "artifacts": {},
            "gate": {},
            "gate_history": [],
            "messages": [],
        })

    def state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            raise RuntimeError("Agent workspace has not been initialized")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state.setdefault("thread_id", state.get("run_id"))
        state.setdefault("round", 1)
        state.setdefault("stage_history", [])
        state.setdefault("gate_history", [])
        return state

    def update(self, **values: Any) -> dict[str, Any]:
        state = self.state()
        state.update(values)
        self._write_state(state)
        return state

    def update_agent(self, agent: str, **values: Any) -> dict[str, Any]:
        state = self.state()
        state.setdefault("agents", {}).setdefault(agent, {}).update(values)
        self._write_state(state)
        return state

    def transition(self, stage: str, reason: str) -> dict[str, Any]:
        state = self.state()
        current = state["stage"]
        if stage == current:
            return state
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if stage not in allowed:
            raise RuntimeError(f"非法 Agent 状态迁移：{current} -> {stage}")
        state["stage"] = stage
        state.setdefault("stage_history", []).append({
            "stage": stage,
            "created_at": now_iso(),
            "reason": reason,
        })
        self._write_state(state)
        return state

    def begin_round(self) -> int:
        state = self.state()
        state["round"] = int(state.get("round", 1)) + 1
        self._write_state(state)
        return state["round"]

    def update_artifact(self, name: str, path: Path | str) -> None:
        state = self.state()
        state.setdefault("artifacts", {})[name] = str(Path(path).resolve())
        self._write_state(state)

    def record_gate(self, payload: dict[str, Any]) -> None:
        state = self.state()
        state["gate"] = payload
        state.setdefault("gate_history", []).append(payload)
        self._write_state(state)

    def send(
        self,
        sender: str,
        recipient: str,
        kind: str,
        content: dict[str, Any] | str,
    ) -> dict[str, Any]:
        message = {
            "id": f"MSG-{uuid4().hex[:10]}",
            "created_at": now_iso(),
            "thread_id": self.state()["thread_id"],
            "round": self.state()["round"],
            "sender": sender,
            "recipient": recipient,
            "kind": kind,
            "content": content,
        }
        state = self.state()
        state.setdefault("messages", []).append(message)
        self._write_state(state)
        with self.messages_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        return message

    def record_tool(self, agent: str, result: ToolResult) -> None:
        entry = {
            "created_at": now_iso(),
            "agent": agent,
            **asdict(result),
        }
        with self.tools_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _write_state(self, state: dict[str, Any]) -> None:
        temp = self.state_path.with_name(self.state_path.name + ".tmp")
        temp.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, self.state_path)
