#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DistillGuard：在人格提取之前判断什么材料可以进入蒸馏流程。

三个子命令：
    gate   入库闸——按三层边界分类，产出 approved/ 与 blocked.json
    seal   出厂闸——检查有效期、退出通道，生成成分表与审计记录
    audit  出包核查——检查被拦截的材料是否混进了产出包
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules"

REQUIRED_FIELDS = [
    "id", "path", "type", "author",
    "contains_third_party", "contains_personal_expression",
    "contains_identifiable_style", "subject_refused",
]

BOOL_FIELDS = [
    "contains_third_party", "contains_personal_expression",
    "contains_identifiable_style", "subject_refused",
    "consent_at_exit_process", "consideration_listed", "revocable",
]

TYPE_LABEL = {
    "process_doc": "制度化流程",
    "public": "已公开资料",
    "work_doc": "工作文档",
    "note": "个人笔记",
    "chat": "对话记录",
    "email": "邮件",
    "self_description": "自我描述",
    "other": "未分类",
}


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def coerce_manifest(manifest: dict) -> dict:
    """把 'true'/'否' 这类字符串统一成布尔，避免 YAML 手写时的静默错判。"""
    for item in manifest.get("materials", []):
        for field in BOOL_FIELDS:
            if field not in item:
                continue
            value = item[field]
            if isinstance(value, bool):
                continue
            if isinstance(value, str):
                item[field] = value.strip().lower() in ("true", "yes", "1", "是", "有")
            else:
                item[field] = bool(value)
    return manifest


def parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


TEXT_SUFFIX = {".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".py", ".html"}

# 零宽水印：用 U+200B / U+200C 承载位，U+2060 作边界
ZW0, ZW1, ZW_BOUND = "\u200b", "\u200c", "\u2060"

# 聊天记录的说话人前缀：`我：` / `小王: ` / `[2026-01-01] 老张：`
SPEAKER_RE = re.compile(r"^\s*(?:\[[^\]]{1,20}\]\s*)?([^\s:：]{1,12})\s*[:：]\s*\S")
NON_SPEAKER = {
    "http", "https", "时间", "日期", "备注", "说明", "注", "来源", "注意",
    "用法", "输出", "输入", "示例", "问题", "回答", "参考", "注意：", "例",
}
SELF_NAMES = {"我", "本人", "自己", "me", "自", "笔者"}

# 常见姓氏，用于从"老张/小王"这类称谓里提候选名
SURNAMES = set(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤"
)


def read_text(path: Path):
    if path.suffix.lower() not in TEXT_SUFFIX:
        return None
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            return None
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None


def shingles(text: str, n: int = 6) -> set[str]:
    flat = re.sub(r"\s+", "", text)
    if len(flat) < n:
        return set()
    return {flat[i:i + n] for i in range(len(flat) - n + 1)}


def encode_watermark(payload: str) -> str:
    bits = "".join(f"{b:08b}" for b in payload.encode("utf-8"))
    return ZW_BOUND + "".join(ZW0 if c == "0" else ZW1 for c in bits) + ZW_BOUND


def decode_watermark(text: str) -> list[str]:
    found = []
    for m in re.finditer(ZW_BOUND + "([" + ZW0 + ZW1 + "]+)" + ZW_BOUND, text):
        bits = m.group(1)
        if len(bits) % 8:
            continue
        data = bytes(
            int("".join("1" if c == ZW1 else "0" for c in bits[i:i + 8]), 2)
            for i in range(0, len(bits), 8)
        )
        try:
            found.append(data.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return found


def make_issue_id(materials: list) -> str:
    base = "|".join(sorted((m.get("sha256") or "") for m in materials))
    digest = hashlib.sha256((base + date.today().isoformat()).encode()).hexdigest()[:8]
    return f"DG-{date.today():%Y%m%d}-{digest.upper()}"


def load_scanner():
    """读取 PII 模式与第三人姓名观察名单。"""
    patterns = []
    pii_path = RULES / "pii.yaml"
    if pii_path.exists():
        patterns = load_yaml(pii_path).get("patterns", [])
    names = []
    wl = RULES / "watchlist.txt"
    if wl.exists():
        for line in wl.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                names.append(s)
    return patterns, names


def scan_text(text: str, patterns: list, names: list) -> list[dict]:
    hits = []
    for p in patterns:
        try:
            found = list(re.finditer(p["regex"], text))
        except re.error:
            continue
        if found:
            hits.append({
                "id": p["id"],
                "label": p.get("label", p["id"]),
                "severity": p.get("severity", "medium"),
                "count": len(found),
            })
    for name in names:
        if name and name in text:
            hits.append({"id": "watchlist", "label": f"观察名单：{name}",
                         "severity": "high", "count": text.count(name)})
    return hits


def detect_speakers(text: str) -> Counter:
    speakers = Counter()
    for line in text.splitlines():
        m = SPEAKER_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        if not name or name in NON_SPEAKER or name.isdigit():
            continue
        if len(name) > 12:
            continue
        speakers[name] += 1
    return speakers


def detect_nicknames(text: str) -> Counter:
    """从"老张""小王""张工""李老师"这类称谓里提候选人名。"""
    found = Counter()
    for m in re.finditer(r"(?:老|小)([\u4e00-\u9fa5])", text):
        if m.group(1) in SURNAMES:
            found[m.group(0)] += 1
    for m in re.finditer(r"([\u4e00-\u9fa5])(?:工|老师|总|经理|主任|姐|哥)", text):
        if m.group(1) in SURNAMES:
            found[m.group(0)] += 1
    return found


def check_quasi_identifiers(rows: list, manifest: dict):
    """把整份语料的属性取并集，凑齐任一准标识符组合就返回该组合。"""
    if manifest.get("quasi_identifier_ack"):
        return None
    path = RULES / "quasi_identifiers.yaml"
    if not path.exists():
        return None
    rules = load_yaml(path)
    attrs = set()
    for r in rows:
        if r["result"] in ("approved", "pending"):
            attrs.update(r.get("attributes") or [])
    for combo in rules.get("combos", []):
        need = set(combo.get("attributes", []))
        if need and need <= attrs:
            return combo
    return None


def match_condition(item: dict, cond: dict) -> bool:
    field = cond.get("field")
    value = item.get(field)
    if "equals" in cond:
        return value == cond["equals"]
    if "in" in cond:
        return value in cond["in"]
    return False


def classify(item: dict, tiers: dict) -> dict:
    for tier in tiers["tiers"]:
        for cond in tier.get("when_any", []):
            if match_condition(item, cond):
                return tier
    return tiers["default"]


def consent_review(item: dict, consent_rules: dict) -> tuple[list[str], list[str]]:
    """返回 (缺口列表, 命中的概括用语)。"""
    gaps = []
    if item.get("consent") != "separate":
        gaps.append("单独签署")
    if not item.get("scope") or not item.get("expiry"):
        gaps.append("明确用途、范围与期限")
    if item.get("consent_at_exit_process"):
        gaps.append("时点自由")
    if not item.get("consideration_listed"):
        gaps.append("对价单独计列")
    if not item.get("revocable"):
        gaps.append("可撤回且有退出通道")
    expiry = parse_date(item.get("expiry"))
    if expiry is None or expiry < date.today():
        gaps.append("授权未过期")

    terms = str(item.get("consent_terms", ""))
    hits = [p for p in consent_rules.get("blanket_phrases", []) if p in terms]
    if hits:
        gaps.append("未使用概括性授权")
    return gaps, hits


def redflags(item: dict, tier_id: str, hits: list[str], consent_gaps: list[str]) -> list[dict]:
    flags = []
    if hits:
        flags.append({"id": "RF-01", "label": "概括性授权", "detail": "、".join(hits)})
    if item.get("consent_at_exit_process"):
        flags.append({"id": "RF-02", "label": "同意在压力峰值取得", "detail": "离职谈判或离职证明办理期间签署"})
    if tier_id == "consent" and not item.get("revocable"):
        flags.append({"id": "RF-03", "label": "无退出机制", "detail": "当事人无法要求停止调用"})
    if tier_id == "consent" and not item.get("expiry"):
        flags.append({"id": "RF-04", "label": "无到期时间", "detail": "授权无限期"})
    if item.get("contains_third_party"):
        flags.append({"id": "RF-05", "label": "第三人信息未隔离", "detail": "本人同意覆盖不到第三人表达"})
    if item.get("type") in ("chat", "email") and item.get("consent") == "none":
        flags.append({"id": "RF-06", "label": "以工作任务替代授权请求", "detail": "材料已归集但未取得授权"})
    if tier_id == "consent" and not item.get("consideration_listed"):
        flags.append({"id": "RF-07", "label": "对价未单列", "detail": "收益与劳动者无关"})
    if item.get("type") == "other" or item.get("author") == "other":
        flags.append({"id": "RF-08", "label": "材料归属不清", "detail": "按禁止处理"})
    expiry = parse_date(item.get("expiry"))
    if tier_id == "consent" and (expiry is None or expiry < date.today()):
        flags.append({"id": "RF-09", "label": "授权已过期", "detail": "需重新取得同意"})
    return flags


def cmd_gate(args) -> int:
    manifest = coerce_manifest(load_yaml(Path(args.manifest)))
    tiers = load_yaml(RULES / "tiers.yaml")
    consent_rules = load_yaml(RULES / "consent.yaml")
    patterns, names = load_scanner()
    do_scan = not getattr(args, "no_scan", False)

    src = Path(args.src)
    out = Path(args.out)
    approved = out / "approved"
    # 每次过闸都重建 approved，避免上一轮的残余材料被下游读到
    if approved.exists():
        shutil.rmtree(approved)
    approved.mkdir(parents=True, exist_ok=True)

    rows, blocked, pending = [], [], []
    candidates = Counter()

    for item in manifest.get("materials", []):
        missing = [f for f in REQUIRED_FIELDS if f not in item]
        item_id = item.get("id", "(无编号)")

        if missing:
            tier = tiers["default"]
            tier_id, tier_label, action = tier["id"], tier["label"], tier["action"]
            gaps, hits, flags = [], [], [{"id": "RF-08", "label": "字段缺失", "detail": "、".join(missing)}]
            result = "blocked"
        else:
            tier = classify(item, tiers)
            tier_id, tier_label, action = tier["id"], tier["label"], tier["action"]
            gaps, hits = ([], [])
            flags = []
            if tier_id == "consent":
                gaps, hits = consent_review(item, consent_rules)
                flags = redflags(item, tier_id, hits, gaps)
                result = "approved" if not gaps else "pending"
            elif tier_id == "prohibited":
                flags = redflags(item, tier_id, [], [])
                result = "blocked"
            else:
                result = "approved"

        src_path = src / item.get("path", "")
        exists = src_path.exists()

        scan_hits = []
        if do_scan and exists and src_path.is_file():
            text = read_text(src_path)
            if text:
                scan_hits = scan_text(text, patterns, names)
                speakers = detect_speakers(text)
                if len(speakers) >= 2:
                    scan_hits.append({
                        "id": "multi_speaker",
                        "label": "多说话人",
                        "severity": "high",
                        "count": len(speakers),
                    })
                for name_, cnt in speakers.items():
                    if name_ not in SELF_NAMES:
                        candidates[name_] += cnt
                for nick, cnt in detect_nicknames(text).items():
                    candidates[nick] += cnt
                serious = [h for h in scan_hits if h["severity"] in ("high", "medium")]
                declared_clean = item.get("contains_third_party") is False
                if serious and declared_clean:
                    result = "blocked"
                    tier_label = tier_label + "（扫描冲突）"
                    if {h["id"] for h in serious} == {"multi_speaker"}:
                        flags.append({
                            "id": "RF-11",
                            "label": "多说话人未申报",
                            "detail": f"出现 {serious[0]['count']} 个说话人",
                        })
                    else:
                        flags.append({
                            "id": "RF-10",
                            "label": "申报与扫描冲突",
                            "detail": "扫描到 " + "、".join(
                                f"{h['label']}×{h['count']}" for h in serious),
                        })

        if result == "approved" and not exists:
            result = "blocked"
            flags.append({"id": "RF-08", "label": "文件不存在", "detail": str(item.get("path"))})

        if result == "approved":
            dest = approved / item["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)

        record = {
            "id": item_id,
            "path": item.get("path"),
            "type": item.get("type"),
            "tier": tier_id,
            "tier_label": tier_label,
            "result": result,
            "gaps": gaps,
            "blanket_hits": hits,
            "flags": flags,
            "scan_hits": scan_hits,
            "attributes": item.get("attributes") or [],
            "scope": item.get("scope"),
            "expiry": item.get("expiry"),
            "sha256": sha256(src_path) if exists else None,
        }
        rows.append(record)
        if result == "blocked":
            blocked.append(record)
        elif result == "pending":
            pending.append(record)

    # 准标识符组合检查：跨材料拼起来能识别身份时，挂起整个语料
    qi = check_quasi_identifiers(rows, manifest)
    if qi:
        for r in rows:
            if r["result"] in ("approved", "pending"):
                r["flags"].append({
                    "id": "RF-12",
                    "label": "准标识符组合可识别",
                    "detail": qi["label"],
                })
                if r["result"] == "approved":
                    r["result"] = "pending"
                    r["gaps"].append("准标识符组合：" + qi["label"])
        blocked = [r for r in rows if r["result"] == "blocked"]
        pending = [r for r in rows if r["result"] == "pending"]

    state = {
        "generated": date.today().isoformat(),
        "src": str(src.resolve()),
        "approved": str(approved.resolve()),
        "materials": rows,
    }
    (out / "run.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "blocked.json").write_text(
        json.dumps({"blocked": blocked, "pending": pending}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "合规记录.md").write_text(render_gate_report(rows, approved), encoding="utf-8")
    if candidates:
        lines = ["# 候选人名（需人工确认后写入 rules/watchlist.txt）", ""]
        for name_, cnt in candidates.most_common():
            lines.append(f"{name_}\t{cnt}")
        (out / "watchlist_candidates.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"入库闸：共 {len(rows)} 份材料，放行 {len(rows) - len(blocked) - len(pending)}，"
          f"挂起 {len(pending)}，拦截 {len(blocked)}")
    for r in blocked:
        reason = "；".join(f["label"] for f in r["flags"]) or r["tier_label"]
        print(f"  [拦截] {r['id']} {r['path']} —— {reason}")
    for r in pending:
        print(f"  [挂起] {r['id']} {r['path']} —— 缺：{'、'.join(r['gaps'])}")
    print(f"产出：{out / '合规记录.md'}")
    if candidates:
        print(f"候选人名 {len(candidates)} 个，见：{out / 'watchlist_candidates.txt'}")

    if blocked:
        return 2
    if pending:
        return 3
    return 0


def render_gate_report(rows: list[dict], approved: Path) -> str:
    lines = ["# 提取合规记录", "", f"生成日期：{date.today().isoformat()}", ""]
    lines += ["## 一、材料分层结果", "",
              "| 编号 | 材料 | 类型 | 层级 | 结果 | 说明 |",
              "|---|---|---|---|---|---|"]
    for r in rows:
        t = TYPE_LABEL.get(r["type"], r["type"] or "-")
        note = "—"
        if r["gaps"]:
            note = "缺：" + "、".join(r["gaps"])
        elif r["flags"]:
            note = "；".join(f['label'] for f in r["flags"])
        lines.append(f"| {r['id']} | {r['path']} | {t} | {r['tier_label']} | {r['result']} | {note} |")

    pending = [r for r in rows if r["result"] == "pending"]
    blocked = [r for r in rows if r["result"] == "blocked"]

    lines += ["", "## 二、授权缺口", ""]
    with_gaps = [r for r in rows if r["gaps"]]
    if with_gaps:
        for r in with_gaps:
            lines.append(f"- **{r['id']}**：{'、'.join(r['gaps'])}")
    else:
        lines.append("无。")

    lines += ["", "## 三、合规表演红旗", ""]
    flagged = [r for r in rows if r["flags"]]
    if flagged:
        for r in flagged:
            for f in r["flags"]:
                lines.append(f"- **{f['id']} {f['label']}**（{r['id']}）：{f['detail']}")
    else:
        lines.append("无。")

    lines += ["", "## 四、被拦截的材料", ""]
    if blocked:
        for r in blocked:
            reason = r["tier_label"]
            if r["flags"]:
                reason += "（" + "；".join(f["label"] for f in r["flags"]) + "）"
            lines.append(f"- **{r['id']}** {r['path']}：{reason}")
    else:
        lines.append("无。")

    lines += ["", "## 五、扫描提示", ""]
    scanned = [r for r in rows if r.get("scan_hits")]
    if scanned:
        for r in scanned:
            desc = "、".join(f"{h['label']}×{h['count']}" for h in r["scan_hits"])
            lines.append(f"- **{r['id']}**：{desc}")
        lines.append("")
        lines.append("> 扫描只做交叉核对，不替代申报。命中不等于一定有问题，但申报为"
                     "“不含第三人”时会被阻断，需核对后重新申报。")
    else:
        lines.append("未发现高置信度的联系方式或观察名单命中。")

    lines += ["", "## 六、下一步", ""]
    if blocked or pending:
        lines.append("1. 被挂起的材料补齐五项同意要件后重新过闸。")
        lines.append("2. 被拦截的材料不得以任何方式进入蒸馏输入。")
        lines.append("3. 需要脱敏的材料，先脱敏再由使用者在清单中重新申报。")
    else:
        lines.append("全部材料已通过入库闸，可交给蒸馏工具，输入目录限定为：")
        lines.append(f"`{approved}`")

    lines += ["", "> 本记录为风险提示与检查清单，不构成法律意见。", ""]
    return "\n".join(lines)


def cmd_seal(args) -> int:
    run = Path(args.run)
    state = json.loads((run / "run.json").read_text(encoding="utf-8"))
    package = Path(args.package)
    package.mkdir(parents=True, exist_ok=True)

    pending = [m for m in state["materials"] if m["result"] == "pending"]
    approved = [m for m in state["materials"] if m["result"] == "approved"]

    if pending:
        print("出厂闸：仍有挂起材料，不予出厂。")
        for m in pending:
            print(f"  [挂起] {m['id']} {m['path']} —— {'、'.join(m['gaps'])}")
        return 3

    if not approved:
        print("出厂闸：没有任何材料通过入库闸，无可提取内容，不予出厂。")
        return 3

    today = date.today()
    expiry_default = today + timedelta(days=180)
    # 包的有效期取各材料授权到期时间中最早的一个；都没有则用默认 180 天
    dates = []
    for m in approved:
        raw = m.get("expiry")
        if raw:
            try:
                dates.append(date.fromisoformat(str(raw)))
            except ValueError:
                pass
    package_expiry = min(dates) if dates else expiry_default
    issue_id = make_issue_id(approved)
    rows = []
    for m in approved:
        expiry = str(m.get("expiry") or package_expiry.isoformat())
        rows.append((m["id"], m["path"], TYPE_LABEL.get(m["type"], m["type"] or "-"),
                     m["tier_label"], expiry))

    lines = ["# 技能包成分表", "",
             f"签发编号：**{issue_id}**", "",
             "| 编号 | 材料 | 类型 | 授权层级 | 到期时间 |",
             "|---|---|---|---|---|"]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in r) + " |")
    lines += ["", "## 出厂条件", "",
              f"1. **有效期**：{package_expiry.isoformat()} 到期即失效，续用须重新取得同意。",
              "2. **删除义务**：到期后 30 日内删除个人痕迹数据，并提供可查验的确认方式。",
              "3. **退出通道**：当事人可要求停止后续调用，调用方须在 7 个工作日内响应。",
              "4. **审计留痕**：保存授权范围与调用记录，使越界使用可被识别。",
              "",
              "> 成分表的作用是把授权范围说清楚，不追溯到模型参数级的贡献。",
              "",
              encode_watermark(issue_id), ""]
    (package / "成分表.md").write_text("\n".join(lines), encoding="utf-8")

    audit = {
        "issue_id": issue_id,
        "issued": today.isoformat(),
        "expires": package_expiry.isoformat(),
        "materials": [m["id"] for m in approved],
        "obligations": ["delete_on_expiry", "stop_on_request", "audit_trail", "scope_limit"],
    }
    (package / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    excluded = len([m for m in state["materials"] if m["result"] == "blocked"])
    print(f"出厂闸：通过，{len(approved)} 份材料写入成分表，排除 {excluded} 份被拦截材料。"
          f"有效期至 {package_expiry.isoformat()}。")
    print(f"签发编号：{issue_id}（已写入成分表，含不可见水印）")
    print(f"产出：{package / '成分表.md'}")
    return 0


def cmd_audit(args) -> int:
    run = Path(args.run)
    state = json.loads((run / "run.json").read_text(encoding="utf-8"))
    package = Path(args.package)

    blocked_hashes = {}
    blocked_texts = {}
    src_root = Path(state.get("src", "")).resolve()
    for m in state["materials"]:
        if m["result"] in ("blocked", "pending") and m["sha256"]:
            blocked_hashes[m["sha256"]] = m
            if m.get("path"):
                text = read_text(src_root / m["path"])
                if text:
                    blocked_texts[m["id"]] = (m, shingles(text))

    leaks = []
    derived = []
    marks = {}
    for p in package.rglob("*"):
        if p.is_file():
            h = sha256(p)
            if h in blocked_hashes:
                leaks.append((p, blocked_hashes[h]))
            text = read_text(p)
            if text:
                for mark in decode_watermark(text):
                    marks.setdefault(mark, []).append(p.name)
            if text and blocked_texts:
                s = shingles(text)
                for mid, (m, bs) in blocked_texts.items():
                    if not bs or not s:
                        continue
                    overlap = len(s & bs) / len(bs)
                    if overlap >= 0.6:
                        derived.append((p, m, overlap))

    if marks:
        print("签发标记：" + "、".join(sorted(marks)))
    else:
        print("签发标记：未发现（该产出可能不是经由本工具签发）")

    # 调用记录核查
    overdue = []
    calls_path = package / "calls.jsonl"
    calls = []
    if calls_path.exists():
        for line in calls_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                calls.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        audit_file = package / "audit.json"
        expires = ""
        if audit_file.exists():
            try:
                expires = json.loads(audit_file.read_text(encoding="utf-8")).get("expires", "")
            except json.JSONDecodeError:
                expires = ""
        overdue = [c for c in calls if expires and str(c.get("at", ""))[:10] > expires]
        print(f"调用记录：{len(calls)} 次" +
              (f"，最近一次 {calls[-1].get('at')}（{calls[-1].get('caller')}）" if calls else ""))

    if leaks:
        print(f"出包核查：发现 {len(leaks)} 处越界。")
        for p, m in leaks:
            print(f"  [越界] {p} 与已拦截材料 {m['id']} 内容相同")
        return 2

    if derived:
        print(f"出包核查：发现 {len(derived)} 处疑似改写后混入（文本重合度 ≥ 60%）。")
        for p, m, ratio in derived:
            print(f"  [疑似] {p} 与已拦截材料 {m['id']} 文本重合 {ratio:.0%}")
        return 2

    if overdue:
        print(f"出包核查：发现 {len(overdue)} 次超期调用。")
        for c in overdue:
            print(f"  [超期] {c.get('at')} 由 {c.get('caller')} 调用，授权已于 {expires} 到期")
        return 2

    print(f"出包核查：未发现被拦截材料混入产出包"
          f"（比对 {len(blocked_hashes)} 份拦截材料的哈希与 {len(blocked_texts)} 份文本）。")
    return 0


def cmd_recover(args) -> int:
    """进程被强杀时，把 --lock-raw 改名的目录恢复回来。"""
    src = Path(args.src).resolve()
    if src.exists():
        print(f"原目录已存在，无需恢复：{src}")
        return 0
    candidates = sorted(src.parent.glob(src.name + ".locked-*"))
    if not candidates:
        print(f"没有找到锁定目录：{src.parent / (src.name + '.locked-*')}")
        return 1
    target = candidates[-1]
    os.replace(target, src)
    print(f"已恢复：{target.name} -> {src.name}")
    return 0


def cmd_log_call(args) -> int:
    """登记一次技能包调用，用于事后核查是否越期或越界。"""
    pkg = Path(args.package)
    audit_file = pkg / "audit.json"
    if not audit_file.exists():
        print("包内没有 audit.json，无法登记调用。")
        return 1
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    at = args.at or datetime.now().isoformat(timespec="seconds")
    entry = {
        "at": at,
        "caller": args.caller,
        "purpose": args.purpose,
        "issue_id": audit.get("issue_id"),
    }
    with open(pkg / "calls.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"已登记：{at}　{args.caller}　{args.purpose}".rstrip())

    expires = str(audit.get("expires", ""))
    if expires and str(at)[:10] > expires:
        print(f"警告：本次调用晚于授权到期日 {expires}。")
        return 3
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="DistillGuard · 在提取之前决定什么可以进入")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("gate", help="入库闸")
    g.add_argument("--manifest", required=True)
    g.add_argument("--src", required=True)
    g.add_argument("--out", required=True)
    g.add_argument("--no-scan", action="store_true",
                   help="关闭扫描交叉核对（不建议）")
    g.set_defaults(func=cmd_gate)

    s = sub.add_parser("seal", help="出厂闸")
    s.add_argument("--run", required=True)
    s.add_argument("--package", required=True)
    s.set_defaults(func=cmd_seal)

    a = sub.add_parser("audit", help="出包核查")
    a.add_argument("--run", required=True)
    a.add_argument("--package", required=True)
    a.set_defaults(func=cmd_audit)

    r = sub.add_parser("recover", help="恢复被 --lock-raw 改名且未自动还原的目录")
    r.add_argument("--src", required=True)
    r.set_defaults(func=cmd_recover)

    lc = sub.add_parser("log-call", help="登记一次技能包调用")
    lc.add_argument("--package", required=True)
    lc.add_argument("--caller", required=True)
    lc.add_argument("--purpose", default="")
    lc.add_argument("--at", default="")
    lc.set_defaults(func=cmd_log_call)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
