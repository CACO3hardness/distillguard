# -*- coding: utf-8 -*-
"""端到端测试：直接调用命令行，覆盖四个示例与六条边界规则。

运行：python -m unittest discover -s tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GUARD = BASE / "scripts" / "guard.py"
RUN_GUARDED = BASE / "scripts" / "run_guarded.py"
HANDOFF = BASE / "scripts" / "handoff.py"
EX = BASE / "examples"


def call(script, *args, cwd=None):
    return subprocess.run(
        [sys.executable, str(script)] + [str(a) for a in args],
        capture_output=True, text=True, encoding="utf-8", cwd=cwd,
    )


class GateCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def gate(self, case, out=None):
        out = out or Path(self.tmp.name) / "run"
        return call(GUARD, "gate",
                    "--manifest", EX / case / "materials.yaml",
                    "--src", EX / case / "raw",
                    "--out", out)

    def test_pass_exit_0(self):
        self.assertEqual(self.gate("case_pass").returncode, 0)

    def test_consent_exit_0(self):
        self.assertEqual(self.gate("case_consent").returncode, 0)

    def test_block_exit_2(self):
        self.assertEqual(self.gate("case_block").returncode, 2)

    def test_pending_exit_3(self):
        self.assertEqual(self.gate("case_pending").returncode, 3)

    def test_scan_conflict_exit_2(self):
        res = self.gate("case_scan")
        self.assertEqual(res.returncode, 2)
        report = (Path(self.tmp.name) / "run" / "合规记录.md").read_text(encoding="utf-8")
        self.assertIn("RF-10", report)
        self.assertIn("手机号", report)

    def test_speaker_conflict_exit_2(self):
        """同意要件齐全，但材料里有第二个说话人，仍应拦截。"""
        res = self.gate("case_speaker")
        self.assertEqual(res.returncode, 2)
        report = (Path(self.tmp.name) / "run" / "合规记录.md").read_text(encoding="utf-8")
        self.assertIn("RF-11", report)

    def test_speaker_candidates_listed(self):
        self.gate("case_speaker")
        cand = (Path(self.tmp.name) / "run" / "watchlist_candidates.txt").read_text(encoding="utf-8")
        self.assertIn("小王", cand)

    def test_quasi_identifier_exit_3(self):
        """两份材料单独看都无害，拼起来能定位到人。"""
        res = self.gate("case_qi")
        self.assertEqual(res.returncode, 3)
        report = (Path(self.tmp.name) / "run" / "合规记录.md").read_text(encoding="utf-8")
        self.assertIn("RF-12", report)

    def test_approved_cleared_between_runs(self):
        """上一轮放行的材料不能残留到下一轮。"""
        out = Path(self.tmp.name) / "run"
        self.gate("case_block", out)
        self.assertTrue(any((out / "approved").rglob("*")))
        self.gate("case_pending", out)
        files = [p for p in (out / "approved").rglob("*") if p.is_file()]
        self.assertEqual(files, [])

    def test_expired_consent_is_pending(self):
        manifest = (EX / "case_consent" / "materials.yaml").read_text(encoding="utf-8")
        manifest = manifest.replace("2027-11-13", "2020-01-01")
        tmp_manifest = Path(self.tmp.name) / "expired.yaml"
        tmp_manifest.write_text(manifest, encoding="utf-8")
        res = call(GUARD, "gate", "--manifest", tmp_manifest,
                   "--src", EX / "case_consent" / "raw",
                   "--out", Path(self.tmp.name) / "run")
        self.assertEqual(res.returncode, 3)
        report = (Path(self.tmp.name) / "run" / "合规记录.md").read_text(encoding="utf-8")
        self.assertIn("RF-09", report)

    def test_seal_refuses_pending(self):
        out = Path(self.tmp.name) / "run"
        self.gate("case_pending", out)
        res = call(GUARD, "seal", "--run", out, "--package", Path(self.tmp.name) / "pkg")
        self.assertEqual(res.returncode, 3)
        self.assertFalse((Path(self.tmp.name) / "pkg" / "成分表.md").exists())


class AuditCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"
        self.pkg = Path(self.tmp.name) / "pkg"
        call(GUARD, "gate", "--manifest", EX / "case_block" / "materials.yaml",
             "--src", EX / "case_block" / "raw", "--out", self.run_dir)
        call(GUARD, "seal", "--run", self.run_dir, "--package", self.pkg)

    def test_identical_leak_detected(self):
        shutil.copy2(EX / "case_block" / "raw" / "聊天记录_摘录.txt", self.pkg / "leak.txt")
        res = call(GUARD, "audit", "--run", self.run_dir, "--package", self.pkg)
        self.assertEqual(res.returncode, 2)
        self.assertIn("越界", res.stdout)

    def test_rewritten_leak_detected(self):
        text = (EX / "case_block" / "raw" / "聊天记录_摘录.txt").read_text(encoding="utf-8")
        (self.pkg / "rewritten.md").write_text(text.replace("小王", "小李"), encoding="utf-8")
        res = call(GUARD, "audit", "--run", self.run_dir, "--package", self.pkg)
        self.assertEqual(res.returncode, 2)
        self.assertIn("疑似", res.stdout)

    def test_clean_package_passes(self):
        res = call(GUARD, "audit", "--run", self.run_dir, "--package", self.pkg)
        self.assertEqual(res.returncode, 0)


class WrapperCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raw = Path(self.tmp.name) / "raw"
        shutil.copytree(EX / "case_pass" / "raw", self.raw)
        self.run_dir = Path(self.tmp.name) / "run"
        self.pkg = Path(self.tmp.name) / "pkg"

    def test_default_lock_hides_and_restores(self):
        res = call(RUN_GUARDED,
                   "--manifest", EX / "case_pass" / "materials.yaml",
                   "--src", self.raw, "--workdir", self.run_dir,
                   "--package", self.pkg,
                   "--", sys.executable, EX / "probe_raw.py")
        self.assertEqual(res.returncode, 0)
        self.assertIn("原始目录不可达", res.stdout)
        self.assertTrue(self.raw.exists(), "运行结束后原始目录必须恢复")
        self.assertFalse(list(Path(self.tmp.name).glob("*.locked-*")))

    def test_no_lock_leaves_raw_visible(self):
        res = call(RUN_GUARDED,
                   "--manifest", EX / "case_pass" / "materials.yaml",
                   "--src", self.raw, "--workdir", self.run_dir,
                   "--package", self.pkg, "--no-lock",
                   "--", sys.executable, EX / "probe_raw.py")
        self.assertEqual(res.returncode, 10)
        self.assertIn("可见 2 个文件", res.stdout)

    def test_pending_never_starts_downstream(self):
        res = call(RUN_GUARDED,
                   "--manifest", EX / "case_pending" / "materials.yaml",
                   "--src", EX / "case_pending" / "raw",
                   "--workdir", self.run_dir, "--package", self.pkg,
                   "--", sys.executable, EX / "mock_distill.py", "--out", "../pkg")
        self.assertEqual(res.returncode, 3)
        self.assertFalse(self.pkg.exists())


class HandoffCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_handoff_bundle(self):
        run_dir = Path(self.tmp.name) / "run"
        out = Path(self.tmp.name) / "handoff"
        call(GUARD, "gate", "--manifest", EX / "case_consent" / "materials.yaml",
             "--src", EX / "case_consent" / "raw", "--out", run_dir)
        res = call(HANDOFF, "--run", run_dir, "--out", out, "--tool", "任意工具")
        self.assertEqual(res.returncode, 0)
        for name in ("materials", "CONTRACT.md", "POLICY.yaml", "materials.json"):
            self.assertTrue((out / name).exists(), f"缺少 {name}")
        policy = (out / "POLICY.yaml").read_text(encoding="utf-8")
        self.assertIn("scope_limit", policy)
        self.assertTrue(list((out / "materials").rglob("*.md")))


class WatermarkCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = Path(self.tmp.name) / "run"
        self.pkg = Path(self.tmp.name) / "pkg"
        call(GUARD, "gate", "--manifest", EX / "case_consent" / "materials.yaml",
             "--src", EX / "case_consent" / "raw", "--out", self.run_dir)
        call(GUARD, "seal", "--run", self.run_dir, "--package", self.pkg)

    def test_issue_id_recorded(self):
        audit = json.loads((self.pkg / "audit.json").read_text(encoding="utf-8"))
        self.assertTrue(audit["issue_id"].startswith("DG-"))

    def test_audit_reads_watermark(self):
        res = call(GUARD, "audit", "--run", self.run_dir, "--package", self.pkg)
        self.assertEqual(res.returncode, 0)
        self.assertIn("签发标记：DG-", res.stdout)

    def test_overdue_call_flagged(self):
        ok = call(GUARD, "log-call", "--package", self.pkg,
                  "--caller", "研发部", "--purpose", "复盘")
        self.assertEqual(ok.returncode, 0)
        late = call(GUARD, "log-call", "--package", self.pkg,
                    "--caller", "外部顾问", "--purpose", "演示",
                    "--at", "2028-01-01T10:00:00")
        self.assertEqual(late.returncode, 3)
        res = call(GUARD, "audit", "--run", self.run_dir, "--package", self.pkg)
        self.assertEqual(res.returncode, 2)
        self.assertIn("超期调用", res.stdout)


if __name__ == "__main__":
    unittest.main()
