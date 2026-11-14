#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DistillGuard wrapper：把"先过闸、再提取"写死成一条命令。

用法：
    python scripts/run_guarded.py \
        --manifest examples/case_consent/materials.yaml \
        --src examples/case_consent/raw \
        --workdir examples/case_consent/run \
        --package examples/case_consent/skill_package \
        -- python examples/mock_distill.py --out ../skill_package

保证的三件事：
1. 下游进程的工作目录在 run/ 里，看不到 raw/；相对路径 raw/... 直接失效。
2. 下游只拿到 DISTILLGUARD_MATERIALS 这一个材料路径，指向 approved/。
3. 存在挂起材料时，下游根本不会启动。

默认在运行期间把原始目录改名，连绝对路径也断掉；要关掉用 --no-lock。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

GUARD = Path(__file__).resolve().parent / "guard.py"


def run_guard(cmd: list[str]) -> int:
    proc = subprocess.run([sys.executable, str(GUARD)] + cmd)
    return proc.returncode


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="DistillGuard wrapper：先过闸，再让下游提取")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--allow-partial", action="store_true",
                        help="存在被拦截材料时仍然只对放行部分继续")
    parser.add_argument("--reason", default="",
                        help="配合 --allow-partial 记录放行理由")
    parser.add_argument("--no-lock", action="store_true",
                        help="不锁定原始目录（默认锁定）")
    parser.add_argument("--lock-raw", action="store_true",
                        help=argparse.SUPPRESS)  # 兼容旧写法，已默认开启
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- 之后的命令，例如 python mock_distill.py --out ../pkg")
    args = parser.parse_args()

    cmd = [c for c in args.command if c != "--"]
    if not cmd:
        print("缺少下游命令：在 -- 之后给出，例如 -- python mock_distill.py")
        return 64

    workdir = Path(args.workdir).resolve()
    src = Path(args.src).resolve()
    package = Path(args.package).resolve()
    approved = workdir / "approved"

    started = datetime.now().isoformat(timespec="seconds")
    log = {"started": started, "commands": []}

    # ---- 1. 入库闸 ----
    print("\n[1/4] 入库闸")
    code = run_guard(["gate", "--manifest", args.manifest,
                      "--src", str(src), "--out", str(workdir)])
    log["gate_exit"] = code

    if code == 3:
        print("\n存在挂起材料，下游不会启动。补齐同意要件后重新运行。")
        log["aborted"] = "pending_consent"
        (workdir / "runlog.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return 3

    if code == 2 and not args.allow_partial:
        print("\n存在被拦截材料。确认只提取放行部分后，加 --allow-partial 重跑。")
        log["aborted"] = "blocked_materials"
        (workdir / "runlog.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return 2

    if args.allow_partial and args.reason:
        log["partial_reason"] = args.reason

    if not approved.exists() or not any(approved.iterdir()):
        print("\napproved/ 为空，没有可提取的内容。")
        return 3

    # ---- 2. 可选：锁住原始目录 ----
    locked_from = locked_to = None
    if not args.no_lock:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        locked_to = src.with_name(src.name + f".locked-{stamp}")
        try:
            os.replace(src, locked_to)
        except OSError as exc:
            print(f"\n无法锁定原始目录（{exc}）。请关闭占用它的程序后重试，"
                  f"或显式加 --no-lock 放弃物理隔离。")
            return 4
        locked_from = src
        (workdir / "lock.json").write_text(
            json.dumps({"src": str(src), "locked_to": str(locked_to)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n已锁定原始目录：{src.name} -> {locked_to.name}"
              f"（如进程被强杀，用 guard.py recover --src {src.name} 恢复）")

    env = dict(os.environ)
    env["DISTILLGUARD_MATERIALS"] = str(approved)
    env["DISTILLGUARD_RUN"] = str(workdir)
    env["DISTILLGUARD_PACKAGE"] = str(package)

    downstream_exit = None
    try:
        # ---- 3. 下游提取 ----
        print("\n[2/4] 下游提取（只提供 approved/）", flush=True)
        print(f"  DISTILLGUARD_MATERIALS={approved}", flush=True)
        proc = subprocess.run(cmd, cwd=str(workdir), env=env)
        downstream_exit = proc.returncode
        log["downstream"] = {"command": cmd, "exit": downstream_exit}
        if downstream_exit != 0:
            print(f"\n下游返回非零（{downstream_exit}），停止。")
    finally:
        if locked_from and locked_to and locked_to.exists():
            os.replace(locked_to, locked_from)
            lock_file = workdir / "lock.json"
            if lock_file.exists():
                lock_file.unlink()
            print(f"原始目录已恢复：{locked_to.name} -> {locked_from.name}")

    if downstream_exit != 0:
        (workdir / "runlog.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return downstream_exit or 1

    # ---- 4. 出厂 + 核查 ----
    print("\n[3/4] 出厂闸")
    code = run_guard(["seal", "--run", str(workdir), "--package", str(package)])
    log["seal_exit"] = code
    if code != 0:
        (workdir / "runlog.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        return code

    print("\n[4/4] 出包核查")
    code = run_guard(["audit", "--run", str(workdir), "--package", str(package)])
    log["audit_exit"] = code

    log["finished"] = datetime.now().isoformat(timespec="seconds")
    (workdir / "runlog.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成。运行日志：{workdir / 'runlog.json'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
