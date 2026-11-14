#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""假的蒸馏器，只用来演示 wrapper 的链路。

它只从 DISTILLGUARD_MATERIALS 指定的目录读材料，证明下游拿不到 approved 以外的输入。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    materials = os.environ.get("DISTILLGUARD_MATERIALS")
    if not materials:
        print("没有拿到 DISTILLGUARD_MATERIALS，拒绝运行。")
        return 65

    src = Path(materials)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    entries = []
    for p in sorted(src.rglob("*")):
        if p.is_file():
            shutil.copy2(p, out / p.name)
            entries.append(p.name)

    (out / "skill.md").write_text(
        "# 示例技能包\n\n本文件由 mock_distill 生成，仅用于演示。\n\n"
        "来源材料：" + "、".join(entries) + "\n",
        encoding="utf-8",
    )
    (out / "sources.json").write_text(
        json.dumps({"materials_dir": str(src), "files": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"mock_distill：从 {src} 读取 {len(entries)} 份材料，写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
