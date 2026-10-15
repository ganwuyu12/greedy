#!/usr/bin/env python3
"""
解析知识点之间的引用关系 → 依赖图

第 3 步「解析依赖关系」的实现。

为什么做这个：
  第 2 步得到的是「顺序」（谁先谁后），这一步要得到「依赖」（学它之前必须会什么）。
  区别：
    顺序：2.4 排序 排在 2.5 二分 前面
    依赖：学「线段树」必须先会「二叉树」
  「前置检查」功能靠的是依赖，不是顺序。

依赖从哪来：每个知识点正文里的内部链接。
  例：打开 ds/seg.md（线段树），正文里链到 graph/tree-basic.md（二叉树），
      说明线段树引用了二叉树。

⚠️ 重要设计决定：区分「引用」和「前置」
  一个知识点里链接另一个，可能是强依赖，也可能只是「顺便看看」。
  如果全部当成强制前置，用户会被挡住——「学线段树前请先学完 200 篇」。
  所以：
    references     —— 正文链接解析出的，全部记录（宽）
    prerequisites  —— 经人工确认的强依赖，初期为空（严）
  前置检查先用 references 做「提示」，等人工确认后再做「拦截」。

产出：
  data/dep_graph.json          引用关系图
  data/dep_report.md           覆盖率报告

用法：
    python parse_deps.py
    python parse_deps.py --top 20     # 只看被引用最多的 20 个
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
CLEAN_DIR = BASE / "data" / "oi_wiki_clean"
CURRICULUM = BASE / "data" / "curriculum.json"
OUT_JSON = BASE / "data" / "dep_graph.json"
OUT_REPORT = BASE / "data" / "dep_report.md"

# 匹配 Markdown 链接 [文本](目标)
#   (?!\!) 前置断言排除图片 ![alt](src)
RE_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# 代码块围栏：``` 或 ~~~
RE_FENCE = re.compile(r"^\s*(```|~~~)")

# 清洗阶段排除的目录：指向这些目录的链接「解析不到」是预期行为，不是错误
EXCLUDED_DIRS = {"tools", "intro", "images", "_static"}


def strip_code_blocks(text: str) -> str:
    """去掉代码块内容

    代码块里的方括号多半不是链接（比如 C++ 的 a[i]），
    不排除会造成大量误报。
    """
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if RE_FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def resolve(from_path: str, target: str) -> str | None:
    """把链接目标解析为相对于语料根目录的知识点路径

    支持三种写法：
      ../dp/knapsack/basic.md   相对路径
      /dp/knapsack/basic.md     站内绝对路径（OI Wiki 常见）
      basic.md                  同目录
    返回 None 表示不是知识点链接。
    """
    if target.startswith(("http://", "https://", "mailto:", "#", "ftp:")):
        return None
    # 去掉锚点
    target = target.split("#", 1)[0].strip()
    if not target.endswith(".md"):
        return None

    if target.startswith("/"):
        rel = target.lstrip("/")
    elif target.startswith("../") or target.startswith("./"):
        # 以 from_path 所在目录为基准
        base_dir = Path(from_path).parent
        rel = str((base_dir / target).as_posix())
    else:
        base_dir = Path(from_path).parent
        rel = str((base_dir / target).as_posix())

    # 归一化 . / .. （Path 的 as_posix 不一定消除 ..，手动处理）
    parts: list[str] = []
    for seg in rel.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    norm = "/".join(parts)
    return norm if norm.endswith(".md") else None


def concept_id(path: str) -> str:
    return path[:-3].replace("/", "_").replace("-", "_")


def main() -> None:
    ap = argparse.ArgumentParser(description="解析知识点引用关系")
    ap.add_argument("--top", type=int, default=15, help="报告里展示被引用最多的前 N 个")
    args = ap.parse_args()

    if not CLEAN_DIR.exists():
        raise SystemExit(f"找不到语料目录：{CLEAN_DIR}\n请先运行：python clean_corpus.py")

    md_files = sorted(p for p in CLEAN_DIR.rglob("*.md"))
    known = {str(p.relative_to(CLEAN_DIR)).replace("\\", "/") for p in md_files}

    print(f"扫描 {len(known)} 个知识点文件…")

    edges: dict[str, list[str]] = defaultdict(list)
    unresolved: list[dict] = []
    total_links = 0
    internal_links = 0

    for p in md_files:
        rel = str(p.relative_to(CLEAN_DIR)).replace("\\", "/")
        text = strip_code_blocks(p.read_text(encoding="utf-8", errors="ignore"))
        for m in RE_LINK.finditer(text):
            total_links += 1
            tgt = resolve(rel, m.group(2))
            if tgt is None:
                continue
            internal_links += 1
            if tgt == rel:
                continue                      # 自引用忽略
            if tgt in known:
                if tgt not in edges[rel]:
                    edges[rel].append(tgt)
            else:
                unresolved.append({"from": rel, "name": m.group(1)[:40], "target": tgt})

    # 反向索引：谁被引用了
    referenced_by: dict[str, list[str]] = defaultdict(list)
    for src, dsts in edges.items():
        for d in dsts:
            referenced_by[d].append(src)

    has_ref = len(edges)
    coverage = has_ref / len(known) if known else 0

    # 挂到 curriculum 上（第 2 步的产物）
    attached = 0
    if CURRICULUM.exists():
        cur = json.loads(CURRICULUM.read_text(encoding="utf-8"))
        for st in cur["stages"]:
            for sec in st["sections"]:
                for c in sec["concepts"]:
                    refs = edges.get(c["path"], [])
                    if refs:
                        c["references"] = refs
                        c["prerequisites"] = []      # 留空，等人工确认
                        attached += 1
        cur["stats"]["concepts_with_references"] = attached
        cur["stats"]["reference_coverage"] = round(
            attached / max(1, cur["stats"]["concept_count"]), 3)
        CURRICULUM.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")

    doc = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": {"dir": "data/oi_wiki_clean", "license": "CC BY-SA 4.0"},
        "note": "references = 正文引用关系（宽）；prerequisites = 人工确认的强依赖（严，初期为空）",
        "stats": {
            "file_count": len(known),
            "total_links": total_links,
            "internal_links": internal_links,
            "files_with_references": has_ref,
            "coverage": round(coverage, 3),
            "edge_count": sum(len(v) for v in edges.values()),
            "unresolved_count": len(unresolved),
            "unresolved_excluded_dir": sum(
                1 for u in unresolved
                if u["target"].split("/")[0] in EXCLUDED_DIRS
            ),
        },
        "edges": {k: sorted(v) for k, v in sorted(edges.items())},
        "referenced_by": {k: sorted(v) for k, v in sorted(referenced_by.items())},
        "unresolved_sample": unresolved[:50],
    }
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 报告 ----
    top = Counter({k: len(v) for k, v in referenced_by.items()}).most_common(args.top)
    out_deg = Counter({k: len(v) for k, v in edges.items()}).most_common(args.top)
    no_ref = sorted(known - set(edges))

    lines = [
        "# 依赖关系解析报告",
        "",
        f"生成时间：{doc['generated_at']}",
        "",
        "## 一、总览",
        "",
        "| 项目 | 数值 |",
        "|---|---|",
        f"| 知识点文件 | {len(known)} |",
        f"| 链接总数（去代码块后） | {total_links} |",
        f"| 其中指向知识点的链接 | {internal_links} |",
        f"| 有引用的文件 | {has_ref} |",
        f"| **引用覆盖率** | **{coverage:.1%}** |",
        f"| 引用边总数 | {doc['stats']['edge_count']} |",
        f"| 未解析的链接 | {len(unresolved)} |",
        f"| ↳ 其中指向已排除目录 | {doc['stats']['unresolved_excluded_dir']}（预期行为） |",
        f"| ↳ 真正异常 | {len(unresolved) - doc['stats']['unresolved_excluded_dir']} |",
        "",
        "## 二、被引用最多的知识点（基础中的基础）",
        "",
        "这些是被依赖最多的节点，**学习路线里应该靠前**：",
        "",
        "| 知识点 | 被引用次数 |",
        "|---|---|",
    ]
    for path, n in top:
        lines.append(f"| `{path}` | {n} |")

    lines += ["", "## 三、引用别人最多的知识点（依赖最重的）", "",
              "这些知识点前置要求最多，**适合放在路线后段**：", "",
              "| 知识点 | 引用数 |", "|---|---|"]
    for path, n in out_deg:
        lines.append(f"| `{path}` | {n} |")

    lines += ["", "## 四、无引用的知识点", "",
              f"共 {len(no_ref)} 个，应多为最基础的入口页：", ""]
    for path in no_ref[:30]:
        lines.append(f"- `{path}`")
    if len(no_ref) > 30:
        lines.append(f"- …（其余 {len(no_ref) - 30} 个见 JSON）")

    lines += [
        "",
        "## 五、结论与说明",
        "",
        f"- 引用覆盖率 **{coverage:.1%}**"
        + ("（达标，> 60%）" if coverage > 0.6 else "（偏低，需检查解析规则）"),
        "",
        "⚠️ **重要**：本报告解析的是「引用关系」，"
        "**不等于「前置依赖」**。一个知识点引用另一个，可能只是「参见」。",
        "",
        "因此：",
        "- `references` 用于**提示**用户「你可能会用到这些」",
        "- `prerequisites` 需要**人工确认**，用于**拦截**（前期检查）",
        "",
        "两者分开，是为了避免「学线段树前请先学完 200 篇」这种过度拦截。",
        "",
        "> 本报告由 `parse_deps.py` 自动生成。",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print()
    print(f"引用覆盖率：{has_ref}/{len(known)} = {coverage:.1%}"
          + ("  ✅ 达标" if coverage > 0.6 else "  ⚠️ 偏低"))
    print(f"引用边总数：{doc['stats']['edge_count']}")
    print(f"未解析链接：{len(unresolved)}")
    if attached:
        print(f"已挂到 curriculum 的知识点：{attached}")
    print()
    print("被引用最多（= 最基础）：")
    for path, n in top[:8]:
        print(f"  {n:>4}  {path}")
    print()
    print(f"已写出：\n  {OUT_JSON}\n  {OUT_REPORT}")


if __name__ == "__main__":
    main()
