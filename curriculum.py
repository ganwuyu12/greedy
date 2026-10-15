#!/usr/bin/env python3
"""
学习路线查询接口

第 5 步「接进 Agent」的数据层：把 curriculum.json 变成可查询的能力。

为什么单独成模块：
  路线查询逻辑（找下一个知识点、检查前置）不该混在 Agent 主循环里。
  分开之后，这部分可以独立测试，也方便以后换数据源。

设计要点：
  - 数据一次性加载并缓存，避免每次查询都读文件
  - 「已学」的判断基于 data/records.json（做题记录），而不是单独维护进度表
    → 理由：用户已经用 add_record 记录刷题，不必再让他维护第二份进度
  - 前置检查用「引用关系」做提示，而非硬拦截
    → 全部当强制前置会导致「学线段树前先学完 200 篇」

用法：
    from curriculum import next_topic, check_prerequisites, get_topic, list_stage

    python curriculum.py --next            # 命令行查看下一个该学的
    python curriculum.py --check ds/seg.md # 检查某知识点的前置
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
CURRICULUM = BASE / "data" / "curriculum.json"
CURRICULUM_EXT = BASE / "data" / "curriculum_extended.json"
DEPS = BASE / "data" / "dep_graph.json"
RECORDS = BASE / "data" / "records.json"


# ---------------------------------------------------------------- 数据加载

_cur: dict | None = None
_deps: dict | None = None
_adv_names: dict[str, str] | None = None


def _advanced_names() -> dict[str, str]:
    """进阶层知识点的「路径 → 名称」映射

    进阶层是按目录归类的，文件名多为英文（seg.md、knapsack.md），
    展示时用文件名很难看，所以优先取中文名（如果有）。
    """
    global _adv_names
    if _adv_names is None:
        _adv_names = {}
        if CURRICULUM_EXT.exists():
            try:
                ext = json.loads(CURRICULUM_EXT.read_text(encoding="utf-8"))
                for tier in ext.get("advanced", {}).get("tiers", []):
                    for g in tier.get("groups", []):
                        for c in g.get("concepts", []):
                            _adv_names[c["path"]] = c.get("name") or ""
            except (json.JSONDecodeError, OSError, KeyError):
                _adv_names = {}
    return _adv_names


def display_name(path: str) -> str:
    """给出一个知识点的可读名称（入门层优先，其次进阶层，最后文件名）

    文件名多为英文，直接用会很难看。中英混排时优先带中文的那个。
    """
    concepts = {c["path"]: c for c in flat_concepts()}
    if path in concepts:
        return concepts[path]["name"]
    adv = _advanced_names().get(path, "")
    stem = Path(path).stem
    # 两者选「含中文」的那个；都含或都不含时优先进阶层的名字
    if any("\u4e00" <= ch <= "\u9fff" for ch in adv):
        return adv
    if any("\u4e00" <= ch <= "\u9fff" for ch in stem):
        return stem
    return adv or stem


def _load_curriculum() -> dict:
    global _cur
    if _cur is None:
        if not CURRICULUM.exists():
            raise FileNotFoundError(
                f"缺少 {CURRICULUM}，请先运行：python parse_roadmap.py")
        _cur = json.loads(CURRICULUM.read_text(encoding="utf-8"))
    return _cur


def _load_deps() -> dict:
    global _deps
    if _deps is None:
        if not DEPS.exists():
            raise FileNotFoundError(
                f"缺少 {DEPS}，请先运行：python parse_deps.py")
        _deps = json.loads(DEPS.read_text(encoding="utf-8"))
    return _deps


def reload() -> None:
    """清空缓存（数据文件更新后调用）"""
    global _cur, _deps
    _cur = None
    _deps = None


def flat_concepts() -> list[dict]:
    """按学习顺序展开所有入门层知识点"""
    cur = _load_curriculum()
    out: list[dict] = []
    for stage in cur["stages"]:
        for sec in stage["sections"]:
            for c in sec["concepts"]:
                item = dict(c)
                item["stage_order"] = stage["order"]
                item["stage_title"] = stage["title"]
                item["section_order"] = sec["order"]
                item["section_title"] = sec["title"]
                item["section_note"] = sec.get("note", "")
                out.append(item)
    out.sort(key=lambda x: x.get("global_order", 0))
    return out


def learned_paths() -> set[str]:
    """从做题记录推断「已学」的知识点

    匹配规则：题解的算法标签里如果出现了知识点名，就认为学过。
    这是粗匹配，保守使用——**宁可漏判也不误判**，因为误判会跳过该学的内容。
    """
    if not RECORDS.exists():
        return set()
    try:
        records = json.loads(RECORDS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()

    learned: set[str] = set()
    for c in flat_concepts():
        name = c["name"]
        # 知识点名太短或太通用时跳过，避免误匹配
        if len(name) < 3:
            continue
        for r in records:
            tags = str(r.get("algorithm", ""))
            if name in tags:
                learned.add(c["path"])
                break
    return learned


# ---------------------------------------------------------------- 工具函数

def next_topic(count: int = 3) -> dict:
    """找学习路线上还没学的下一个知识点（按顺序返回若干个）"""
    concepts = flat_concepts()
    learned = learned_paths()

    pending = [c for c in concepts if c["path"] not in learned]
    nxt = pending[:count]

    if not nxt:
        return {
            "done": True,
            "message": f"入门层的 {len(concepts)} 个知识点都已学过。可以开始进阶层了。",
        }

    return {
        "done": False,
        "progress": f"{len(concepts) - len(pending)}/{len(concepts)}",
        "learned_count": len(concepts) - len(pending),
        "total": len(concepts),
        "next": [
            {
                "order": c.get("global_order"),
                "name": c["name"],
                "path": c["path"],
                "stage": c["stage_title"],
                "section": f"{c['section_order']} {c['section_title']}",
                "why": c.get("section_note", "")[:120],
            }
            for c in nxt
        ],
    }


def check_prerequisites(path: str) -> dict:
    """检查某知识点的前置

    注意措辞：返回的是「可能会用到」，不是「必须先学」。
    因为 references 是正文引用关系，不等于强依赖。
    """
    deps = _load_deps()
    refs = deps["edges"].get(path, [])
    learned = learned_paths()

    concepts = {c["path"]: c for c in flat_concepts()}
    target = concepts.get(path)

    # 只关心被 roadmap 收录的前置（它们有明确学习位次）
    refs_in_roadmap = [r for r in refs if r in concepts]
    missing = [r for r in refs_in_roadmap if r not in learned]

    # 进阶层的知识点：给出它引用的内容名称（虽无学习位次，也要能看）
    refs_all = [
        {"name": display_name(r), "path": r, "in_roadmap": r in concepts}
        for r in sorted(refs)
    ]

    return {
        "path": path,
        "name": target["name"] if target else display_name(path),
        "in_roadmap": target is not None,
        "order": target.get("global_order") if target else None,
        "references_total": len(refs),
        "references_in_roadmap": [
            {"name": concepts[r]["name"], "path": r,
             "order": concepts[r].get("global_order"),
             "learned": r in learned}
            for r in sorted(refs_in_roadmap, key=lambda x: concepts[x].get("global_order", 999))
        ],
        "references_all": refs_all,
        "missing_count": len(missing),
        "hint": (
            "该知识点的引用关系里，有内容还没在路线中学过，建议先看看"
            if missing else
            "该知识点的引用内容都在已学范围内"
        ),
    }


def get_topic(path: str) -> dict:
    """获取某个知识点的详细信息"""
    concepts = {c["path"]: c for c in flat_concepts()}
    c = concepts.get(path)
    if c is None:
        # 不在入门路线里，可能在进阶层
        return {
            "found": False,
            "path": path,
            "message": "该知识点不在入门路线中（可能属于进阶层，顺序尚未确认）",
        }
    return {
        "found": True,
        "name": c["name"],
        "path": c["path"],
        "order": c.get("global_order"),
        "stage": c["stage_title"],
        "section": f"{c['section_order']} {c['section_title']}",
        "note": c.get("section_note", ""),
        "learned": c["path"] in learned_paths(),
    }


def list_stage(stage_order: int | None = None) -> dict:
    """列出路线概览，或某个阶段的详情"""
    cur = _load_curriculum()
    learned = learned_paths()

    if stage_order is None:
        return {
            "total_concepts": sum(
                len(sec["concepts"])
                for st in cur["stages"] for sec in st["sections"]
            ),
            "learned": len(learned),
            "stages": [
                {
                    "order": st["order"],
                    "title": st["title"],
                    "section_count": len(st["sections"]),
                    "concept_count": sum(len(s["concepts"]) for s in st["sections"]),
                }
                for st in cur["stages"]
            ],
        }

    for st in cur["stages"]:
        if st["order"] == stage_order:
            return {
                "order": st["order"],
                "title": st["title"],
                "sections": [
                    {
                        "order": sec["order"],
                        "title": sec["title"],
                        "note": sec.get("note", "")[:100],
                        "concepts": [
                            {"name": c["name"], "path": c["path"],
                             "learned": c["path"] in learned}
                            for c in sec["concepts"]
                        ],
                    }
                    for sec in st["sections"]
                ],
            }
    return {"error": f"没有第 {stage_order} 阶段"}


# ---------------------------------------------------------------- 命令行自测

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="学习路线查询")
    ap.add_argument("--next", action="store_true", help="下一个该学的知识点")
    ap.add_argument("--check", metavar="PATH", help="检查某知识点的前置")
    ap.add_argument("--topic", metavar="PATH", help="查看知识点详情")
    ap.add_argument("--overview", action="store_true", help="路线概览")
    a = ap.parse_args()

    if a.next:
        print(json.dumps(next_topic(), ensure_ascii=False, indent=2))
    elif a.check:
        print(json.dumps(check_prerequisites(a.check), ensure_ascii=False, indent=2))
    elif a.topic:
        print(json.dumps(get_topic(a.topic), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(list_stage(), ensure_ascii=False, indent=2))
