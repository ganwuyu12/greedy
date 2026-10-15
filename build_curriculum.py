#!/usr/bin/env python3
"""
处理进阶层：给 roadmap 未覆盖的知识点分层归类

第 4 步的实现。

为什么需要这一步：
  contest/roadmap.md 只覆盖入门级（CSP-J）。它结尾明确写着：
    「至此，你就学习完了入门组范畴内的所有算法」
  也就是说线段树、网络流、高级 DP 这些，它没有覆盖。
  而清洗后的语料有 418 个知识点。

关键原则：区分「解析来的」和「推断的」
  学习路线的顺序是产品地基，不能建在猜测上。
  所以本脚本产出的都是结构归类，**不是学习顺序**，并全部标注：
    level: "进阶"    （按目录划分的大类）
    verified: False  （未经人工确认）
  真正的进阶顺序仍需要人工定，或参考有成体系的课程编号。

产出：
  data/curriculum_extended.json   完整路线（入门=已解析 + 进阶=已归类）
  data/coverage_report.md         覆盖率报告

用法：
    python build_curriculum.py
    python build_curriculum.py --list-uncovered    # 列出未覆盖清单
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
CLEAN_DIR = BASE / "data" / "oi_wiki_clean"
CURRICULUM = BASE / "data" / "curriculum.json"
OUT_JSON = BASE / "data" / "curriculum_extended.json"
OUT_REPORT = BASE / "data" / "coverage_report.md"

# 目录 → 中文主题名（用于进阶层的分组展示）
DIR_TOPIC = {
    "basic": "基础算法",
    "dp": "动态规划",
    "ds": "数据结构",
    "graph": "图论",
    "math": "数学",
    "string": "字符串",
    "search": "搜索",
    "geometry": "计算几何",
    "misc": "杂项技巧",
    "topic": "专题",
    "contest": "竞赛相关",
    "lang": "语言基础",
}

# 目录的默认难度层级（用于「进阶」内部的粗略分组，不是精确顺序）
DIR_TIER = {
    "lang": 1, "basic": 2, "search": 3, "dp": 4, "ds": 4,
    "graph": 5, "string": 5, "math": 6, "geometry": 7, "misc": 8,
    "topic": 9, "contest": 9,
}

TIER_NAME = {
    1: "语言基础", 2: "基础算法", 3: "搜索", 4: "核心专题（DP / 数据结构）",
    5: "图论与字符串", 6: "数学", 7: "计算几何", 8: "杂项技巧", 9: "专题与竞赛",
}


def load_covered() -> tuple[set[str], dict]:
    """从 curriculum.json 取出已被 roadmap 覆盖的知识点路径"""
    if not CURRICULUM.exists():
        raise SystemExit(f"找不到 {CURRICULUM}\n请先运行：python parse_roadmap.py")
    cur = json.loads(CURRICULUM.read_text(encoding="utf-8"))
    covered: set[str] = set()
    for st in cur["stages"]:
        for sec in st["sections"]:
            for c in sec["concepts"]:
                covered.add(c["path"])
    return covered, cur


def main() -> None:
    ap = argparse.ArgumentParser(description="处理进阶层，输出完整路线")
    ap.add_argument("--list-uncovered", action="store_true", help="只列出未覆盖清单")
    args = ap.parse_args()

    if not CLEAN_DIR.exists():
        raise SystemExit(f"找不到语料目录：{CLEAN_DIR}\n请先运行：python clean_corpus.py")

    covered, cur = load_covered()
    all_paths = sorted(
        str(p.relative_to(CLEAN_DIR)).replace("\\", "/")
        for p in CLEAN_DIR.rglob("*.md")
    )
    uncovered = [p for p in all_paths if p not in covered]

    if args.list_uncovered:
        print(f"未覆盖知识点 {len(uncovered)} 个：")
        for p in uncovered:
            print("  ", p)
        return

    # 按目录分组
    by_dir: dict[str, list[str]] = defaultdict(list)
    for p in uncovered:
        by_dir[p.split("/")[0]].append(p)

    # 组装进阶层
    advanced_tiers: list[dict] = []
    for tier in sorted(set(DIR_TIER.values())):
        dirs_in_tier = [d for d, t in DIR_TIER.items() if t == tier and by_dir.get(d)]
        if not dirs_in_tier:
            continue
        groups = []
        for d in sorted(dirs_in_tier):
            paths = sorted(by_dir[d])
            groups.append({
                "topic": DIR_TOPIC.get(d, d),
                "dir": d,
                "count": len(paths),
                "concepts": [
                    {
                        "id": p[:-3].replace("/", "_").replace("-", "_"),
                        "name": Path(p).stem,
                        "path": p,
                        "level": "进阶",
                        "source": "directory_grouping",
                        "verified": False,      # ← 关键：未经人工确认
                        "order_in_dir": i + 1,
                    }
                    for i, p in enumerate(paths)
                ],
            })
        advanced_tiers.append({
            "tier": tier,
            "title": TIER_NAME.get(tier, f"第 {tier} 层"),
            "source": "directory_grouping",
            "verified": False,
            "note": "本层顺序为按目录归类，非学习顺序，需人工确认",
            "groups": groups,
        })

    total_advanced = sum(g["count"] for t in advanced_tiers for g in t["groups"])
    coverage = len(covered & set(all_paths)) / len(all_paths) if all_paths else 0

    doc = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "note": (
            "entry 层来自 contest/roadmap.md 解析，verified=true，有明确学习顺序；"
            "advanced 层为目录归类，verified=false，仅表示「属于哪个主题」，不表示学习顺序"
        ),
        "stats": {
            "total_concepts": len(all_paths),
            "covered_by_roadmap": len(covered & set(all_paths)),
            "uncovered": len(uncovered),
            "coverage": round(coverage, 3),
            "advanced_grouped": total_advanced,
        },
        "entry": {
            "source": "oi_wiki_roadmap",
            "verified": True,
            "stages": cur["stages"],
        },
        "advanced": {
            "source": "directory_grouping",
            "verified": False,
            "tiers": advanced_tiers,
        },
    }
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 报告 ----
    lines = [
        "# 路线覆盖率报告",
        "",
        f"生成时间：{doc['generated_at']}",
        "",
        "## 一、覆盖率",
        "",
        "| 项目 | 数量 | 占比 |",
        "|---|---|---|",
        f"| 语料知识点总数 | {len(all_paths)} | 100% |",
        f"| **roadmap 已覆盖（有学习顺序）** | **{len(covered & set(all_paths))}** "
        f"| **{coverage:.1%}** |",
        f"| 未覆盖（已按目录归类） | {len(uncovered)} | {1 - coverage:.1%} |",
        "",
        "## 二、进阶层主题分布",
        "",
        "| 层级 | 主题 | 知识点数 |",
        "|---|---|---|",
    ]
    for t in advanced_tiers:
        for g in t["groups"]:
            lines.append(f"| {t['tier']} | {g['topic']}（`{g['dir']}/`） | {g['count']} |")

    lines += [
        "",
        "## 三、未覆盖清单（按主题）",
        "",
    ]
    for t in advanced_tiers:
        lines.append(f"### 第 {t['tier']} 层：{t['title']}")
        lines.append("")
        for g in t["groups"]:
            lines.append(f"**{g['topic']}**（{g['count']} 个）")
            lines.append("")
            for c in g["concepts"][:25]:
                lines.append(f"- {c['name']} → `{c['path']}`")
            if g["count"] > 25:
                lines.append(f"- …（其余 {g['count'] - 25} 个见 JSON）")
            lines.append("")

    lines += [
        "## 四、结论与下一步",
        "",
        f"- 入门层（roadmap 覆盖）**{len(covered & set(all_paths))} 个知识点，"
        "有明确学习顺序，verified=true**，可直接用于「我该学什么」",
        f"- 进阶层 **{len(uncovered)} 个知识点已按主题归类，但顺序未定，verified=false**",
        "",
        "### 为什么进阶层的顺序留空",
        "",
        "学习路线的顺序是产品的核心价值，**不能建在猜测上**。",
        "进阶层的顺序有三个可选来源：",
        "",
        "| 来源 | 可信度 | 说明 |",
        "|---|---|---|",
        "| 有成体系的算法课程编号 | 高 | 有人验证过教学顺序 |",
        "| 按「被引用次数」排序 | 中 | 基于本项目的 dep_graph.json 数据 |",
        "| 自己判断 | 中 | — |",
        "| LLM 生成 | 低 | **必须标注未验证** |",
        "",
        "### 建议的推进方式",
        "",
        "1. **先把入门层跑通**——55 个知识点已足够支撑「我该学什么」功能",
        "2. **进阶层先展示「有什么」**，不承诺顺序（分组浏览即可）",
        "3. 等入门层验证有效后，再逐个主题确认进阶顺序",
        "",
        "> 本报告由 `build_curriculum.py` 自动生成。",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"知识点总数：{len(all_paths)}")
    print(f"  roadmap 覆盖：{len(covered & set(all_paths))}（{coverage:.1%}）← 有学习顺序")
    print(f"  未覆盖：{len(uncovered)}（{1 - coverage:.1%}）← 已按目录归类，顺序未定")
    print()
    print("进阶层分布：")
    for t in advanced_tiers:
        for g in t["groups"]:
            print(f"  [{t['tier']}] {g['topic']:<12} {g['count']:>3} 个")
    print()
    print(f"已写出：\n  {OUT_JSON}\n  {OUT_REPORT}")


if __name__ == "__main__":
    main()
