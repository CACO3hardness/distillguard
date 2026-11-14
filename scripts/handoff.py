#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把通过入库闸的材料打包成通用交接包，交给任意蒸馏工具。

产出结构：
    handoff/
        materials/        只读材料目录（下游唯一合法输入）
        materials.json    材料清单与哈希
        POLICY.yaml       机器可读的授权范围与义务
        CONTRACT.md       给下游工具/agent 的契约文本

不绑定具体工具：命令行工具、Claude/Codex skill、自建脚本都能接。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成通用交接包")
    parser.add_argument("--run", required=True, help="gate 产出的 run 目录")
    parser.add_argument("--out", required=True, help="交接包输出目录")
    parser.add_argument("--tool", default="通用蒸馏工具",
                        help="下游工具名称，只用于契约文本")
    args = parser.parse_args()

    run = Path(args.run).resolve()
    state = json.loads((run / "run.json").read_text(encoding="utf-8"))
    approved = [m for m in state["materials"] if m["result"] == "approved"]
    if not approved:
        print("没有通过入库闸的材料，无法生成交接包。")
        return 3

    out = Path(args.out).resolve()
    materials_dir = out / "materials"
    if materials_dir.exists():
        shutil.rmtree(materials_dir)
    materials_dir.mkdir(parents=True, exist_ok=True)

    src_root = Path(state["src"])
    entries = []
    for m in approved:
        src = src_root / m["path"]
        dst = materials_dir / m["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        entries.append({
            "id": m["id"],
            "path": m["path"],
            "type": m["type"],
            "tier": m["tier"],
            "scope": m.get("scope"),
            "expiry": m.get("expiry"),
            "sha256": m.get("sha256"),
        })

    dates = []
    for e in entries:
        if e["expiry"]:
            try:
                dates.append(date.fromisoformat(str(e["expiry"])))
            except ValueError:
                pass
    expires = (min(dates) if dates else date.today() + timedelta(days=180)).isoformat()

    policy = {
        "version": 1,
        "issued": date.today().isoformat(),
        "expires": expires,
        "tool": args.tool,
        "input_dir": "materials",
        "output_dir": "output",
        "materials": entries,
        "obligations": [
            "scope_limit",
            "no_redistribution",
            "delete_on_expiry",
            "stop_on_request",
            "audit_trail",
        ],
    }
    (out / "POLICY.yaml").write_text(
        yaml.safe_dump(policy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out / "materials.json").write_text(
        json.dumps({"materials": entries, "expires": expires}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "CONTRACT.md").write_text(render_contract(args.tool, entries, expires), encoding="utf-8")

    print(f"交接包已生成：{out}")
    print(f"  材料 {len(entries)} 份，有效期至 {expires}")
    print(f"  下游只能读：{materials_dir}")
    return 0


def render_contract(tool: str, entries: list[dict], expires: str) -> str:
    lines = [
        "# 材料使用契约",
        "",
        f"本交接包面向：**{tool}**。",
        "",
        "## 你只能做这些",
        "",
        "- 只从 `materials/` 读取材料，不得访问原始目录、原始聊天记录或其他外部来源。",
        "- 产出写入 `output/`。",
        "- 在产出的技能包里保留本契约与 `materials.json`。",
        "",
        "## 你不能做这些",
        "",
        "- 不得把材料用于本包 `POLICY.yaml` 所列授权范围之外的用途。",
        "- 不得向第三方转发材料或由其派生的完整内容。",
        "- 不得在有效期之后继续使用；到期即失效。",
        "- 当事人要求停止调用时，须停止并可查验。",
        "",
        "## 材料清单",
        "",
        "| 编号 | 材料 | 类型 | 授权层级 | 授权范围 | 到期 |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        lines.append(
            f"| {e['id']} | {e['path']} | {e['type'] or '-'} | {e['tier']} | "
            f"{e.get('scope') or '限定为本次技能包'} | {e.get('expiry') or expires} |"
        )
    lines += [
        "",
        f"整体有效期：**{expires}**。",
        "",
        "## 如果你无法遵守",
        "",
        "停止处理，向调用方报告哪一条无法满足，不要自行降级处理。",
        "",
        "> 本契约由 DistillGuard 生成，是技术约束与风险提示，不构成法律意见。",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
