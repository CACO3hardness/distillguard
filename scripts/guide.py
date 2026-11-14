#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""申报引导员：把一堆材料变成一份可过闸的清单，并解释拦截原因。

它不做判断，只做三件事：
    survey   扫目录，出三问清单（draft.yaml + questions.md）
    build    收答案，生成正式 materials.yaml
    explain  读闸门结果，用大白话解释每条拦截与修复选项
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

SKIP_DIRS = {".git", "__pycache__", "run", "skill_package", "handoff", "gate_test"}

TYPE_BY_EXT = {
    ".md": "note", ".txt": "note", ".docx": "work_doc", ".doc": "work_doc",
    ".csv": "work_doc", ".xlsx": "work_doc", ".xls": "work_doc",
    ".eml": "email", ".msg": "email", ".json": "work_doc",
    ".png": "other", ".jpg": "other", ".jpeg": "other", ".pdf": "other",
}

CHAT_HINTS = ("chat", "message", "msg", "聊天", "消息", "对话", "微信", "qq", "飞书", "钉钉")


def guess_type(path: Path) -> str:
    name = path.name.lower()
    if any(h in name for h in CHAT_HINTS):
        return "chat"
    return TYPE_BY_EXT.get(path.suffix.lower(), "other")


def cmd_survey(args) -> int:
    src = Path(args.src).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    files = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        files.append(p)

    if not files:
        print(f"目录里没有找到材料：{src}")
        return 1

    entries = []
    for i, p in enumerate(files, 1):
        entries.append({
            "id": f"M{i:02d}",
            "path": p.relative_to(src).as_posix(),
            "guess_type": guess_type(p),
            "author": None,
            "third_party": None,
            "nature": None,
        })

    draft = {"version": 1, "src": str(src), "materials": entries}
    (out / "draft.yaml").write_text(
        yaml.safe_dump(draft, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out / "questions.md").write_text(render_questions(entries), encoding="utf-8")

    print(f"扫描到 {len(entries)} 份材料，已生成：")
    print(f"  {out / 'draft.yaml'}")
    print(f"  {out / 'questions.md'}")
    print("把 questions.md 里的三问答完，填进 answers.yaml，再跑 build。")
    return 0


def render_questions(entries: list[dict]) -> str:
    lines = [
        "# 材料申报问卷",
        "",
        "每一份材料回答三个问题。答完把答案写进 `answers.yaml`，格式见文末。",
        "",
        "> 不确定的，一律选「不确定」。闸门会按最保守的方式处理，这比猜错安全。",
        "",
    ]
    for e in entries:
        lines += [
            f"## {e['id']}　{e['path']}",
            "",
            f"（初步判断类型：{e['guess_type']}）",
            "",
            "**Q1 这份材料是谁写的？**",
            "- [ ] 只有我",
            "- [ ] 只有别人",
            "- [ ] 我和别人都有",
            "",
            "**Q2 里面有没有别人的话、姓名、联系方式或隐私？**",
            "- [ ] 有",
            "- [ ] 没有",
            "- [ ] 不确定",
            "",
            "**Q3 这份材料主要是什么内容？**",
            "- [ ] 流程、规范、公开资料",
            "- [ ] 我个人的判断、偏好、做事方法",
            "- [ ] 私人生活、情绪、与工作无关的内容",
            "",
            "---",
            "",
        ]
    lines += [
        "## answers.yaml 怎么写",
        "",
        "```yaml",
        "M01:",
        "  author: self          # self / other / mixed",
        "  third_party: no       # yes / no / unsure",
        "  nature: process       # process / personal / private",
        "```",
        "",
        "三问依次对应 author、third_party、nature。",
        "",
    ]
    return "\n".join(lines)


def cmd_build(args) -> int:
    draft = yaml.safe_load(Path(args.draft).read_text(encoding="utf-8"))
    answers = yaml.safe_load(Path(args.answers).read_text(encoding="utf-8")) or {}

    materials = []
    missing = []
    warnings = []

    for item in draft["materials"]:
        aid = item["id"]
        ans = answers.get(aid) or {}
        author = str(ans.get("author") or "").strip().lower() or None
        third = tri_state(ans.get("third_party"))
        nature = str(ans.get("nature") or "").strip().lower() or None
        if not author or third is None or not nature:
            missing.append(aid)
            continue

        if third in ("yes", "unsure"):
            contains_third = True
            if third == "unsure":
                warnings.append(f"{aid}：第三人信息选了「不确定」，按含第三人处理")
        else:
            contains_third = False

        if nature == "process":
            mtype = item.get("guess_type")
            if mtype not in ("process_doc", "public", "work_doc"):
                mtype = "work_doc"
            personal, style = False, False
        elif nature == "personal":
            mtype, personal, style = "note", False, False
        elif nature == "private":
            mtype, personal, style = "note", True, False
        else:
            mtype, personal, style = "other", False, False

        materials.append({
            "id": aid,
            "path": item["path"],
            "type": mtype,
            "author": author,
            "contains_third_party": contains_third,
            "contains_personal_expression": personal,
            "contains_identifiable_style": style,
            "subject_refused": bool(ans.get("refused", False)),
            "consent": "none",
            "scope": "",
            "expiry": "",
        })

    if missing:
        print("还有材料没答完：" + "、".join(missing))
        print("补齐后再跑 build。")
        return 2

    out = Path(args.out)
    out.write_text(yaml.safe_dump({"version": 1, "materials": materials},
                                  allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"已生成 {out}（{len(materials)} 份材料）")
    for w in warnings:
        print("  注意：" + w)
    return 0


def tri_state(value):
    """把 yes/no/不确定 统一成三种状态；兼容 YAML 把 no 解析成 False。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    s = str(value).strip().lower()
    if s in ("yes", "true", "1", "有"):
        return "yes"
    if s in ("no", "false", "0", "没有", "无"):
        return "no"
    if s in ("unsure", "不确定", "unknown"):
        return "unsure"
    return None


def cmd_explain(args) -> int:
    run = Path(args.run).resolve()
    blocked = json.loads((run / "blocked.json").read_text(encoding="utf-8"))
    items = blocked.get("blocked", []) + blocked.get("pending", [])
    if not items:
        print("这次没有材料被拦截或挂起，可以直接进入提取。")
        return 0

    print(f"共 {len(items)} 份材料没有通过闸门。逐条说原因和可选做法：\n")
    for m in items:
        print(f"■ {m['id']}　{m['path']}（{m['tier_label']}）")
        if m["result"] == "pending":
            print("  原因：这份材料需要单独书面同意，但目前缺：" + "、".join(m["gaps"]))
            print("  三条路：")
            print("    a. 补一份单独同意，写明用途、范围、期限、对价，并保留可撤回的通道；")
            print("    b. 把材料脱敏或替换成不含个人判断的版本，重新申报；")
            print("    c. 这份材料不进入提取。")
        else:
            reason = "；".join(f["label"] for f in m.get("flags", [])) \
                     or m.get("tier_reason") or m["tier_label"]
            print(f"  原因：{reason}")
            print("  三条路：")
            print("    a. 删除其中属于第三人或私人的部分，重新扫描；")
            print("    b. 换一份不含该内容的材料；")
            print("    c. 这份材料不进入提取。")
        print()

    print("闸门不会因为解释而放行：改完之后要重新跑 gate。")
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="DistillGuard 申报引导员")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("survey", help="扫目录，生成三问清单")
    s.add_argument("--src", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_survey)

    b = sub.add_parser("build", help="收答案，生成 materials.yaml")
    b.add_argument("--draft", required=True)
    b.add_argument("--answers", required=True)
    b.add_argument("--out", required=True)
    b.set_defaults(func=cmd_build)

    e = sub.add_parser("explain", help="解释拦截结果")
    e.add_argument("--run", required=True)
    e.set_defaults(func=cmd_explain)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
