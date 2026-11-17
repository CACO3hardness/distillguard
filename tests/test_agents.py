# -*- coding: utf-8 -*-
"""Multi-agent integration tests for declaration and gate handoffs."""

import json
from pathlib import Path
import tempfile
import unittest

from agents.coordinator import MultiAgentCoordinator
from agents.declaration_agent import DeclarationAgent
from agents.gate_agent import GateAgent
from agents.runtime import SharedWorkspace


BASE = Path(__file__).resolve().parent.parent
EX = BASE / "examples"
ANSWERS = EX / "agent"


class DeclarationAgentCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = SharedWorkspace(Path(self.tmp.name) / "workspace")
        self.workspace.initialize("测试申报 Agent", EX / "case_pass" / "raw")

    def test_survey_creates_draft_and_questions(self):
        agent = DeclarationAgent(self.workspace)
        result = agent.survey(EX / "case_pass" / "raw")
        self.assertEqual(len(result.materials), 2)
        self.assertTrue(result.draft_path.exists())
        self.assertTrue(result.questions_path.exists())
        self.assertEqual(self.workspace.state()["stage"], "declaration_awaiting_answers")

    def test_build_sends_handoff_message(self):
        agent = DeclarationAgent(self.workspace)
        agent.survey(EX / "case_pass" / "raw")
        result = agent.build(ANSWERS / "pass_answers.yaml")
        self.assertTrue(result.ok)
        self.assertTrue(result.manifest_path.exists())
        messages = self.workspace.state()["messages"]
        self.assertEqual(messages[-1]["sender"], "declaration_agent")
        self.assertEqual(messages[-1]["recipient"], "gate_agent")
        self.assertEqual(messages[-1]["kind"], "handoff")


class GateAgentCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def agent(self, src):
        workspace = SharedWorkspace(self.root / "workspace")
        workspace.initialize("测试闸门 Agent", src)
        return GateAgent(workspace), workspace

    def test_approved_result(self):
        agent, workspace = self.agent(EX / "case_pass" / "raw")
        result = agent.evaluate(
            EX / "case_pass" / "materials.yaml",
            EX / "case_pass" / "raw",
            self.root / "run-pass",
        )
        self.assertEqual(result.decision, "approved")
        self.assertEqual(result.summary["approved"], 2)
        self.assertEqual(workspace.state()["stage"], "gate_approved")

    def test_pending_routes_back_to_declaration(self):
        agent, workspace = self.agent(EX / "case_pending" / "raw")
        result = agent.evaluate(
            EX / "case_pending" / "materials.yaml",
            EX / "case_pending" / "raw",
            self.root / "run-pending",
        )
        self.assertEqual(result.decision, "pending")
        message = workspace.state()["messages"][-1]
        self.assertEqual(message["sender"], "gate_agent")
        self.assertEqual(message["recipient"], "declaration_agent")
        self.assertEqual(message["kind"], "revision_request")

    def test_blocked_does_not_route_for_retry(self):
        agent, workspace = self.agent(EX / "case_block" / "raw")
        result = agent.evaluate(
            EX / "case_block" / "materials.yaml",
            EX / "case_block" / "raw",
            self.root / "run-block",
        )
        self.assertEqual(result.decision, "partial_blocked")
        message = workspace.state()["messages"][-1]
        self.assertEqual(message["recipient"], "coordinator")
        self.assertEqual(message["kind"], "gate_result")


class CoordinatorCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def run_case(self, case, answers):
        coordinator = MultiAgentCoordinator(self.root / case, EX / case / "raw")
        return coordinator, coordinator.run(
            answers=ANSWERS / answers,
            output_fn=lambda _text: None,
        )

    def test_end_to_end_approved(self):
        coordinator, result = self.run_case("case_pass", "pass_answers.yaml")
        self.assertEqual(result.decision, "approved")
        state = coordinator.workspace.state()
        self.assertEqual(state["stage"], "gate_approved")
        self.assertEqual(
            state["agents"]["declaration_agent"]["status"], "handoff_ready"
        )
        self.assertEqual(state["agents"]["gate_agent"]["status"], "approved")
        self.assertTrue((self.root / "case_pass" / "agent_messages.jsonl").exists())
        self.assertTrue((self.root / "case_pass" / "agent_tools.jsonl").exists())

    def test_end_to_end_pending_requests_revision(self):
        coordinator, result = self.run_case("case_pending", "pending_answers.yaml")
        self.assertEqual(result.decision, "pending")
        state = coordinator.workspace.state()
        self.assertEqual(state["stage"], "awaiting_consent_or_revision")
        self.assertEqual(
            state["agents"]["declaration_agent"]["status"], "revision_requested"
        )

    def test_pending_can_resume_in_round_two(self):
        coordinator, first = self.run_case("case_pass", "revision_initial.yaml")
        self.assertEqual(first.round, 1)
        self.assertEqual(first.decision, "pending")

        second = coordinator.revise(
            ANSWERS / "revision_corrected.yaml",
            output_fn=lambda _text: None,
        )
        self.assertEqual(second.round, 2)
        self.assertEqual(second.decision, "approved")
        state = coordinator.workspace.state()
        self.assertEqual(state["round"], 2)
        self.assertEqual(len(state["gate_history"]), 2)
        self.assertTrue(
            (self.root / "case_pass" / "declaration" / "round-1" / "materials.yaml").exists()
        )
        self.assertTrue(
            (self.root / "case_pass" / "declaration" / "round-2" / "materials.yaml").exists()
        )
        self.assertTrue(
            (self.root / "case_pass" / "gate" / "round-1" / "run.json").exists()
        )
        self.assertTrue(
            (self.root / "case_pass" / "gate" / "round-2" / "run.json").exists()
        )
        self.assertTrue(
            all(message["thread_id"] == state["thread_id"] for message in state["messages"])
        )

    def test_end_to_end_blocked_is_terminal(self):
        coordinator, result = self.run_case("case_block", "block_answers.yaml")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(coordinator.workspace.state()["stage"], "gate_blocked")
        summary = json.loads(
            (self.root / "case_block" / "gate_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["summary"]["blocked"], 2)
        self.assertEqual(summary["summary"]["approved"], 1)

    def test_approved_workspace_rejects_revision(self):
        coordinator, result = self.run_case("case_pass", "pass_answers.yaml")
        self.assertEqual(result.decision, "approved")
        with self.assertRaisesRegex(RuntimeError, "不允许修订"):
            coordinator.revise(
                ANSWERS / "revision_corrected.yaml",
                output_fn=lambda _text: None,
            )


if __name__ == "__main__":
    unittest.main()
