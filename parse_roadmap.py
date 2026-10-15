#!/usr/bin/env python3
"""
解析 OI Wiki 的学习路线（contest/roadmap.md）→ data/curriculum.json

第 2 步「解析 roadmap」的实现。

为什么要解析它而不是自己排顺序：
  OI Wiki 的 contest/roadmap.md 是官方维护的学习路线，235 行，
  开篇写明「该学习路线既是新手学习算法竞赛知识的指南，也是一份复习清单」。
  它已经按学习顺序组织好了章节，还给每节配了「为什么现在学」的说明。
  → 我们要做的是解析它，不是重新发明它。

解析四类元素：
  ##   1 C++ 语言基础         → 阶段（stage）
  ###  1.1 Hello, World!     → 小节（section）
  #### 2.6.1 深度优先搜索     → 子小节（归入 stage.sections，带 parent 标记）
  -   [背包 DP](../dp/…md)   → 知识点（concept），路径需归一化
  普通段落                    → 归到上方最近的小节作为 note

产出：
  data/curriculum.json         有序、分层、带来源标记的路线
  data/curriculum_report.md    解析报告（覆盖率、链接失效、未归类）

用法：
    python parse_roadmap.py              # 解析并写文件
    python parse_roadmap.py --dry-run    # 只看统计，不写文件
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
CLEAN_DIR = BASE / "data" / "oi_wiki_clean"
ROADMAP = CLEAN_DIR / "contest" / "roadmap.md"
OUT_JSON = BASE / "data" / "curriculum.json"
OUT_REPORT = BASE / "data" / "curriculum_report.md"

# 匹配标题：## 1 标题 / ### 1.1 标题 / #### 1.1.1 标题
RE_STAGE = re.compile(r"^##\s+(\d+)\s+(.+?)\s*$")
RE_SECTION = re.compile(r"^###\s+(\d+\.\d+)\s+(.+?)\s*$")
RE_SUBSECTION = re.compile(r"^####\s+(\d+\.\d+\.\d+)\s+(.+?)\s*$")

# 匹配知识点链接：-   [名称](路径)
#   1) 排除图片（前面带 !）
#   2) 允许名称里有中文括号、空格
#   3) 路径里可能有 #anchor
RE_LINK = re.compile(r"^\s*[-*]\s+\[([^\]]+)\]\(([^)]+)\)\s*$")

# 分节线
RE_HR = re.compile(r"^\s*(\*\s*\*\s*\*|-\s*-\s*-|_+)\s*$")


def normalize_path(raw: str) -> tuple[str, str]:
    """把 ../dp/knapsack/basic.md 归一化成 dp/knapsack/basic.md

    返回 (归一化路径, 锚点)。锚点单独返回，因为锚点是文内跳转，不是知识点。
    """
    anchor = ""
    if "#" in raw:
        raw, anchor = raw.split("#", 1)

    p = raw.strip()
    # 去掉开头的 ../ 和 ./
    while p.startswith("../"):
        p = p[3:]
    while p.startswith("./"):
        p = p[2:]
    return p.replace("\\", "/"), anchor


def is_knowledge_link(path: str) -> bool:
    """判断是否指向一个知识点文件"""
    if not path.endswith(".md"):
        return False
    # 排除站点资源类
    if path.startswith(("_", ".")):
        return False
    return True


def concept_id(path: str) -> str:
    """由路径生成稳定的 id：dp/knapsack/basic.md → dp_knapsack_basic"""
    return path[:-3].replace("/", "_").replace("-", "_")


def parse(path: Path) -> tuple[dict, dict]:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    stages: list[dict] = []
    stage = None
    section = None
    note_buf: list[str] = []

    # 统计
    stats = {
        "total_links": 0,
        "knowledge_links": 0,
        "skipped_links": 0,
        "missing_files": [],
        "anchors": 0,
        "dup_concepts": [],
    }
    seen_paths: set[str] = set()

    def flush_note() -> None:
        nonlocal note_buf
        if section is not None and note_buf:
            txt = " ".join(x.strip() for x in note_buf if x.strip())
            if txt:
                section["note"] = (section["note"] + " " + txt).strip() if section["note"] else txt
        note_buf = []

    for raw_line in lines:
        line = raw_line.rstrip()

        # ---- 阶段 ----
        m = RE_STAGE.match(line)
        if m:
            flush_note()
            stage = {
                "order": int(m.group(1)),
                "title": m.group(2).strip(),
                "level": "入门",
                "source": "oi_wiki_roadmap",
                "verified": True,
                "sections": [],
            }
            stages.append(stage)
            section = None
            continue

        # ---- 小节 ----
        m = RE_SECTION.match(line)
        if m:
            flush_note()
            section = {
                "order": m.group(1),
                "title": m.group(2).strip(),
                "parent": None,
                "note": "",
                "concepts": [],
            }
            if stage is not None:
                stage["sections"].append(section)
            continue

        # ---- 子小节（归入上级小节）----
        m = RE_SUBSECTION.match(line)
        if m:
            flush_note()
            order = m.group(1)
            parent_order = ".".join(order.split(".")[:2])
            section = {
                "order": order,
                "title": m.group(2).strip(),
                "parent": parent_order,
                "note": "",
                "concepts": [],
            }
            if stage is not None:
                stage["sections"].append(section)
            continue

        # ---- 分节线 ----
        if RE_HR.match(line):
            flush_note()
            continue

        # ---- 知识点链接 ----
        m = RE_LINK.match(line)
        if m:
            stats["total_links"] += 1
            name, raw_target = m.group(1).strip(), m.group(2).strip()

            # 外链（http/https）跳过
            if raw_target.startswith(("http://", "https://", "mailto:")):
                stats["skipped_links"] += 1
                continue

            target, anchor = normalize_path(raw_target)
            if anchor:
                stats["anchors"] += 1

            if not is_knowledge_link(target):
                stats["skipped_links"] += 1
                continue

            stats["knowledge_links"] += 1
            exists = (CLEAN_DIR / target).exists()
            if not exists:
                stats["missing_files"].append({"name": name, "path": target,
                                               "section": section["order"] if section else "?"})

            cid = concept_id(target)
            if target in seen_paths:
                stats["dup_concepts"].append({"name": name, "path": target})
            seen_paths.add(target)

            if section is not None:
                section["concepts"].append({
                    "id": cid,
                    "name": name,
                    "path": target,
                    "level": "入门",
                    "source": "oi_wiki_roadmap",
                    "verified": True,
                    "exists": exists,
                    "order_in_section": len(section["concepts"]) + 1,
                    "references": [],       # 第 3 步填充
                })
            continue

        # ---- 普通段落 → note ----
        if line.strip() and not line.lstrip().startswith(("#", "|", ">", "```")):
            note_buf.append(line)

    flush_note()

    # 给知识点打全局顺序号
    seq = 0
    for st in stages:
        for sec in st["sections"]:
            for c in sec["concepts"]:
                seq += 1
                c["global_order"] = seq

    doc = {
        "version": "2.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {
            "id": "oi_wiki_roadmap",
            "file": "contest/roadmap.md",
            "url": "https://oi-wiki.org/contest/roadmap/",
            "repo": "https://github.com/OI-wiki/OI-wiki",
            "license": "CC BY-SA 4.0",
        },
        "stages": stages,
        "stats": {
            "stage_count": len(stages),
            "section_count": sum(len(s["sections"]) for s in stages),
            "concept_count": seq,
            "total_links": stats["total_links"],
            "knowledge_links": stats["knowledge_links"],
            "skipped_links": stats["skipped_links"],
            "missing_file_count": len(stats["missing_files"]),
            "duplicate_path_count": len(stats["dup_concepts"]),
        },
    }
    return doc, stats


def write_report(doc: dict, stats: dict, out: Path) -> None:
    s = doc["stats"]
    lines = [
        "# 学习路线解析报告",
        "",
        f"生成时间：{doc['generated_at']}",
        f"数据来源：`{doc['source']['file']}`（{doc['source']['license']}）",
        "",
        "## 一、解析结果",
        "",
        "| 项目 | 数量 |",
        "|---|---|",
        f"| 阶段 | {s['stage_count']} |",
        f"| 小节 | {s['section_count']} |",
        f"| 知识点 | {s['concept_count']} |",
        f"| 总链接数 | {s['total_links']} |",
        f"| 其中知识点链接 | {s['knowledge_links']} |",
        f"| 跳过的链接（外链/图片） | {s['skipped_links']} |",
        f"| **链接失效** | **{s['missing_file_count']}** |",
        f"| 重复提及的知识点 | {s['duplicate_path_count']} |",
        "",
        "## 二、阶段结构",
        "",
        "| 阶段 | 标题 | 小节数 | 知识点数 |",
        "|---|---|---|---|",
    ]
    for st in doc["stages"]:
        n_concepts = sum(len(sec["concepts"]) for sec in st["sections"])
        lines.append(f"| {st['order']} | {st['title']} | {len(st['sections'])} | {n_concepts} |")

    lines += ["", "## 三、逐节明细", ""]
    for st in doc["stages"]:
        lines.append(f"### {st['order']}. {st['title']}")
        lines.append("")
        for sec in st["sections"]:
            indent = "  " if sec.get("parent") else ""
            lines.append(f"{indent}- **{sec['order']} {sec['title']}**"
                         f"（{len(sec['concepts'])} 个知识点）")
            for c in sec["concepts"]:
                flag = "" if c["exists"] else "  ⚠️ 文件缺失"
                lines.append(f"{indent}  - {c['name']} → `{c['path']}`{flag}")
        lines.append("")

    if stats["missing_files"]:
        lines += ["## 四、链接失效清单", "",
                  "以下链接指向的知识点文件在清洗后的语料里找不到：", "",
                  "| 名称 | 路径 | 所在小节 |", "|---|---|---|"]
        for m in stats["missing_files"]:
            lines.append(f"| {m['name']} | `{m['path']}` | {m['section']} |")
        lines.append("")

    if stats["dup_concepts"]:
        lines += ["## 五、被重复提及的知识点", "",
                  "同一知识点在多个小节出现（后续应标记为「复习」而非新学）：", ""]
        for d in stats["dup_concepts"]:
            lines.append(f"- {d['name']} → `{d['path']}`")
        lines.append("")

    lines += ["## 六、结论", ""]
    if s["missing_file_count"] == 0:
        lines.append("✅ 所有知识点链接均指向存在的文件，路线骨架完整。")
    else:
        lines.append(f"⚠️ 有 {s['missing_file_count']} 个链接失效，"
                     "可能是该知识点不在保留目录内，或清洗规则需要调整。")
    lines.append("")
    lines.append("> 本报告由 `parse_roadmap.py` 自动生成，"
                 "用于确认解析完整度——**不要盲目相信数据，先看报告**。")

    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="解析 OI Wiki 学习路线")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = ap.parse_args()

    if not ROADMAP.exists():
        raise SystemExit(f"找不到路线文件：{ROADMAP}\n请先运行：python clean_corpus.py")

    doc, stats = parse(ROADMAP)
    s = doc["stats"]

    print(f"解析：{ROADMAP.name}")
    print(f"  阶段   {s['stage_count']}")
    print(f"  小节   {s['section_count']}")
    print(f"  知识点 {s['concept_count']}")
    print(f"  链接   {s['total_links']} 条（知识点 {s['knowledge_links']}，"
          f"跳过 {s['skipped_links']}）")
    print(f"  失效   {s['missing_file_count']}")
    if stats["missing_files"]:
        for m in stats["missing_files"][:10]:
            print(f"    ⚠️ {m['name']} → {m['path']}")

    if args.dry_run:
        print("\n（dry-run，未写文件）")
        return

    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(doc, stats, OUT_REPORT)
    print(f"\n已写出：")
    print(f"  {OUT_JSON}")
    print(f"  {OUT_REPORT}")


if __name__ == "__main__":
    main()
