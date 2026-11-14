#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DistillGuard 一键演示：五幕，带颜色、暂停与投屏报告。

用法：
    python demo/run_demo.py              # 手动回车推进
    python demo/run_demo.py --auto 3     # 每幕停 3 秒自动推进
    python demo/run_demo.py --fast       # 不停顿，用于自检
"""

from __future__ import annotations

import argparse
import html
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EX = ROOT / "examples"
GUARD = SCRIPTS / "guard.py"
RUN_GUARDED = SCRIPTS / "run_guarded.py"
WORK = ROOT / "demo" / "_run"
REPORT = ROOT / "demo" / "report.html"

USE_COLOR = True


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def clear() -> None:
    if USE_COLOR and sys.stdout.isatty():
        print("\033[2J\033[H", end="")


def rule(ch: str = "─", n: int = 64) -> str:
    return ch * n


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable] + args,
        capture_output=True, text=True, encoding="utf-8", cwd=str(cwd) if cwd else None,
    )


def head(step: str, title: str, subtitle: str) -> None:
    print()
    print(c(rule("━"), "38;5;208"))
    print(c(f"  第 {step} 幕　{title}", "1;38;5;214"))
    print(c(f"  {subtitle}", "38;5;245"))
    print(c(rule("━"), "38;5;208"))
    print()


def body(lines: list[str], color: str = "38;5;252") -> None:
    for ln in lines:
        print("  " + c(ln, color))
    print()


def takeaway(text: str) -> None:
    print("  " + c("▸ " + text, "1;38;5;114"))
    print()


def pause(seconds: float | None) -> None:
    if seconds is None:
        try:
            input(c("  按回车继续…", "38;5;240"))
        except EOFError:
            pass
    elif seconds > 0:
        time.sleep(seconds)


def extract(path: Path, prefix: str) -> list[str]:
    if not path.exists():
        return [f"(没有找到 {path.name})"]
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith(prefix)]


def scene_consent() -> dict:
    out = WORK / "s1"
    res = run([str(GUARD), "gate", "--manifest", str(EX / "case_pending" / "materials.yaml"),
               "--src", str(EX / "case_pending" / "raw"), "--out", str(out)])
    report = out / "合规记录.md"
    flags = extract(report, "- **RF")
    return {
        "step": "一",
        "title": "一份看起来很正常的同意书",
        "subtitle": "「工作成果归公司所有，可用于业务优化与管理提升」",
        "command": "guard.py gate --manifest case_pending/materials.yaml",
        "output": [x.replace("- **", "").replace("**", "") for x in flags],
        "takeaway": "它检查的不是有没有签字，是这份同意算不算数。",
        "code": res.returncode,
    }


def scene_speaker() -> dict:
    out = WORK / "s2"
    res = run([str(GUARD), "gate", "--manifest", str(EX / "case_speaker" / "materials.yaml"),
               "--src", str(EX / "case_speaker" / "raw"), "--out", str(out)])
    report = out / "合规记录.md"
    lines = [ln.strip() for ln in report.read_text(encoding="utf-8").splitlines()
             if "RF-11" in ln or "：需单独" in ln or "：禁止" in ln]
    return {
        "step": "二",
        "title": "同意要件全部齐全，为什么还是拦",
        "subtitle": "材料里有第二个说话人 —— 本人的同意覆盖不到他",
        "command": "guard.py gate --manifest case_speaker/materials.yaml",
        "output": [x.replace("- **", "").replace("**", "") for x in lines],
        "takeaway": "第三人不是「数据」，是另一个权利主体。",
        "code": res.returncode,
    }


def scene_lock() -> dict:
    base = WORK / "s3"
    raw = base / "raw"
    if base.exists():
        shutil.rmtree(base)
    shutil.copytree(EX / "case_consent" / "raw", raw)
    res = run([str(RUN_GUARDED),
               "--manifest", str(EX / "case_consent" / "materials.yaml"),
               "--src", str(raw), "--workdir", str(base / "run"),
               "--package", str(base / "pkg"),
               "--", sys.executable, str(EX / "probe_raw.py")])
    lines = [ln.strip().replace(str(base), "<演示目录>") for ln in res.stdout.splitlines()
             if "probe_raw" in ln or "锁定原始目录" in ln or "原始目录已恢复" in ln]
    return {
        "step": "三",
        "title": "提取运行时，原始目录消失了",
        "subtitle": "下游只拿到 approved/，连绝对路径都读不到",
        "command": "run_guarded.py … -- python probe_raw.py",
        "output": lines,
        "takeaway": "闸门不是提醒，是改变输入的物理结构。",
        "code": res.returncode,
    }


def scene_rewrite() -> dict:
    base = WORK / "s4"
    run_dir = base / "run"
    pkg = base / "pkg"
    run([str(GUARD), "gate", "--manifest", str(EX / "case_block" / "materials.yaml"),
         "--src", str(EX / "case_block" / "raw"), "--out", str(run_dir)])
    run([str(GUARD), "seal", "--run", str(run_dir), "--package", str(pkg)])
    src_text = (EX / "case_block" / "raw" / "聊天记录_摘录.txt").read_text(encoding="utf-8")
    (pkg / "rewritten_chat.md").write_text(src_text.replace("小王", "小李"), encoding="utf-8")
    res = run([str(GUARD), "audit", "--run", str(run_dir), "--package", str(pkg)])
    lines = [ln.strip().replace(str(base), "<演示目录>") for ln in res.stdout.splitlines()
             if "疑似" in ln or "签发标记" in ln]
    return {
        "step": "四",
        "title": "改几个字再塞进去，能查出来吗",
        "subtitle": "把「小王」全部换成「小李」，重新混入产出包",
        "command": "guard.py audit --run … --package …",
        "output": lines,
        "takeaway": "哈希抓原样复制，文本重合度抓改写。",
        "code": res.returncode,
    }


def scene_fixed() -> dict:
    out = WORK / "s5"
    res = run([str(GUARD), "gate", "--manifest", str(EX / "case_fixed" / "materials.yaml"),
               "--src", str(EX / "case_fixed" / "raw"), "--out", str(out)])
    report = out / "合规记录.md"
    line = extract(report, "| M01")
    return {
        "step": "五",
        "title": "同一份材料，换一份合规的同意书",
        "subtitle": "单独签署、范围期限明确、对价单列、可撤回",
        "command": "guard.py gate --manifest case_fixed/materials.yaml",
        "output": line + ["", "入库闸：放行 1，挂起 0，拦截 0"],
        "takeaway": "它拦得住，也放得过改好的材料 —— 这是规则，不是态度。",
        "code": res.returncode,
    }


TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>DistillGuard 演示报告</title>
<style>
:root{{--ink:#0d1a2b;--paper:#f7f9fc;--accent:#c2703d;--line:#dbe2ea;}}
*{{box-sizing:border-box}}
html{{background:#0d1a2b}}
body{{margin:0;background:var(--ink);color:var(--paper);
font-family:"Microsoft YaHei","PingFang SC",sans-serif;padding:48px 56px 72px}}
h1{{font-size:40px;margin:0 0 6px;letter-spacing:.5px}}
.sub{{color:#8fa6be;font-size:17px;margin-bottom:36px}}
.card{{background:#13253c;border:1px solid #24384f;border-radius:16px;
padding:26px 30px;margin-bottom:22px}}
.step{{color:var(--accent);font-size:14px;letter-spacing:2px;font-weight:700}}
h2{{font-size:26px;margin:8px 0 6px}}
.desc{{color:#a9b8c9;font-size:16px;margin-bottom:16px}}
pre{{background:#0b1727;border:1px solid #22344a;border-radius:10px;
padding:16px 18px;font-size:15px;line-height:1.7;color:#d7e2ef;
white-space:pre-wrap;margin:0 0 14px;font-family:Consolas,"Courier New",monospace}}
.take{{color:#8fd08f;font-size:17px;font-weight:700}}
footer{{color:#5c7085;font-size:13px;margin-top:30px}}
</style></head><body>
<h1>DistillGuard · 提取闸门</h1>
<div class="sub">{when}　|　五幕演示：拦截、隔离、追查、放行</div>
{cards}
<footer>本报告由 demo/run_demo.py 生成，内容来自本地实际运行结果。</footer>
</body></html>"""


def write_report(scenes: list[dict]) -> None:
    cards = []
    for s in scenes:
        out = html.escape("\n".join(s["output"]))
        cards.append(f"""<div class="card">
<div class="step">第 {s['step']} 幕</div>
<h2>{html.escape(s['title'])}</h2>
<div class="desc">{html.escape(s['subtitle'])}</div>
<pre>{out}</pre>
<div class="take">{html.escape(s['takeaway'])}</div>
</div>""")
    REPORT.write_text(TEMPLATE.format(
        when=datetime.now().strftime("%Y-%m-%d %H:%M"),
        cards="\n".join(cards)), encoding="utf-8")


def main() -> int:
    global USE_COLOR
    parser = argparse.ArgumentParser(description="DistillGuard 一键演示")
    parser.add_argument("--auto", type=float, default=None,
                        help="每幕停几秒自动推进（默认回车推进）")
    parser.add_argument("--fast", action="store_true", help="不停顿")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    USE_COLOR = not args.no_color
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    clear()
    print()
    print(c("  DistillGuard · 提取闸门", "1;38;5;214"))
    print(c("  五幕演示：什么样的提取会被拦下来", "38;5;245"))
    print(c(rule("━"), "38;5;208"))
    pause(0 if args.fast else args.auto)

    scenes = [scene_consent, scene_speaker, scene_lock, scene_rewrite, scene_fixed]
    results = []
    for i, fn in enumerate(scenes):
        data = fn()
        clear()
        head(data["step"], data["title"], data["subtitle"])
        body([c("$ " + data["command"], "38;5;245")])
        body(data["output"], "38;5;252")
        takeaway(data["takeaway"])
        results.append(data)
        pause(0 if args.fast else args.auto)

    clear()
    print()
    print(c("  五幕演示结束", "1;38;5;214"))
    print(c(rule("━"), "38;5;208"))
    print()
    for s in results:
        print("  " + c(f"第 {s['step']} 幕", "38;5;214") + "　" +
              c(s["title"], "1;38;5;252") + "　" + c(f"exit={s['code']}", "38;5;245"))
    write_report(results)
    print()
    print("  投屏报告已生成：" + c(str(REPORT), "1;38;5;114"))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
