#!/usr/bin/env python3
"""
构建 App 内嵌的知识索引（轻量关键词版）

为什么不用向量检索：
  语义索引（bge-small + reranker）约 42 MB，打进 App 太重。
  而检索的目标很明确——**把用户说的词映射到一个词条**，
  不是做问答理解。关键词匹配对这个任务是够的。

索引里放什么（最小集）：
  path    词条路径，用于回显来源
  name    词条名（如「线段树」）
  keys    检索键：名称 + 别名 + 文件名 + 路径片段
  desc    首段描述（一两句话，给 Agent 当上下文）

不放全文——全文 5.3 MB，而索引只要几十 KB。

别名怎么来：
  OI Wiki 的文件名是英文（seg.md = segment tree），
  中文用户不会那样问。所以别名从三处凑：
    1. 文件名去掉连字符（seg → seg）
    2. 正文里首次出现的英文全称
    3. 人工补充的常见叫法（下表）

产出：
  data/kb_index.json     给 App 用的索引
  data/kb_index_report.md 覆盖率报告

用法：
    python build_app_index.py
"""

from __future__ import annotations

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
CLEAN = BASE / "data" / "oi_wiki_clean"
OUT = BASE / "data" / "kb_index.json"
REPORT = BASE / "data" / "kb_index_report.md"

# 人工补充的常见叫法（中文用户会这么问，但语料里不这么写）
# 只补高频的，不追求全 —— 关键词检索的召回率靠「名称 + 别名」已经够
ALIASES: dict[str, list[str]] = {
    "ds/seg.md": ["线段树", "segment tree"],
    "ds/fenwick.md": ["树状数组", "BIT", "binary indexed tree"],
    "ds/bst.md": ["二叉搜索树", "BST", "二叉查找树"],
    "ds/segment-tree-beats.md": ["segment tree beats"],
    "ds/sparse-table.md": ["ST表", "稀疏表"],
    "ds/dsu.md": ["并查集", "union find", "disjoint set"],
    "ds/heap.md": ["堆", "优先队列", "priority queue"],
    "ds/monotonic-queue.md": ["单调队列"],
    "ds/monotonic-stack.md": ["单调栈"],
    "ds/persistent-seg.md": ["主席树", "可持久化线段树"],
    "ds/leftist-tree.md": ["左偏树", "可并堆"],
    "ds/splay.md": ["Splay", "伸展树"],
    "ds/treap.md": ["Treap", "树堆"],
    "ds/block-list.md": ["块状链表"],
    "ds/queue.md": ["队列"],
    "ds/stack.md": ["栈"],
    "ds/linked-list.md": ["链表"],
    "dp/knapsack.md": ["背包", "背包问题"],
    "dp/interval.md": ["区间DP"],
    "dp/tree.md": ["树形DP"],
    "dp/digit.md": ["数位DP"],
    "dp/state.md": ["状压DP", "状态压缩"],
    "dp/plug.md": ["插头DP"],
    "dp/optimization/monotonic.md": ["单调队列优化"],
    "dp/optimization/slope.md": ["斜率优化"],
    "graph/shortest-path.md": ["最短路", "最短路径", "dijkstra", "spfa"],
    "graph/mst.md": ["最小生成树", "MST", "kruskal", "prim"],
    "graph/tree-diameter.md": ["树的直径"],
    "graph/lca.md": ["最近公共祖先", "LCA"],
    "graph/scc.md": ["强连通分量", "SCC", "tarjan"],
    "graph/topo.md": ["拓扑排序"],
    "graph/bipartite-graph.md": ["二分图"],
    "graph/flow/max-flow.md": ["最大流", "网络流"],
    "graph/flow/min-cost.md": ["最小费用流", "费用流"],
    "graph/2-sat.md": ["2-SAT", "2SAT"],
    "string/kmp.md": ["KMP"],
    "string/ac-automaton.md": ["AC自动机", "AC automaton"],
    "string/sa.md": ["后缀数组", "SA", "suffix array"],
    "string/sam.md": ["后缀自动机", "SAM", "suffix automaton"],
    "string/trie.md": ["字典树", "Trie", "前缀树"],
    "string/hash.md": ["字符串哈希", "hash"],
    "string/manacher.md": ["Manacher", "回文串"],
    "string/z-func.md": ["Z函数", "扩展KMP"],
    "math/number-theory/basic.md": ["数论基础"],
    "math/number-theory/prime.md": ["素数", "质数", "素性测试"],
    "math/number-theory/sieve.md": ["筛法", "埃氏筛", "线性筛"],
    "math/number-theory/gcd.md": ["最大公约数", "gcd"],
    "math/number-theory/euler-totient.md": ["欧拉函数", "phi"],
    "math/number-theory/crt.md": ["中国剩余定理", "CRT"],
    "math/number-theory/exgcd.md": ["扩展欧几里得", "exgcd"],
    "math/number-theory/bsgs.md": ["BSGS", "大步小步"],
    "math/mobius.md": ["莫比乌斯反演", "莫反"],
    "math/combinatorics/combination.md": ["组合数"],
    "math/combinatorics/catalan.md": ["卡特兰数", "Catalan"],
    "math/combinatorics/inclusion-exclusion.md": ["容斥原理"],
    "math/combinatorics/drawer-principle.md": ["抽屉原理", "鸽巢原理"],
    "math/game-theory.md": ["博弈论", "SG函数"],
    "math/linear-algebra/matrix.md": ["矩阵", "矩阵乘法"],
    "math/linear-algebra/gauss.md": ["高斯消元"],
    "math/poly/fft.md": ["FFT", "快速傅里叶变换"],
    "math/poly/ntt.md": ["NTT", "快速数论变换"],
    "math/poly/fwt.md": ["FWT", "快速沃尔什变换"],
    "math/expectation.md": ["期望", "概率期望"],
    "math/vector.md": ["向量"],
    "math/order-theory.md": ["偏序", "序理论"],
    "basic/divide-and-conquer.md": ["分治"],
    "basic/binary.md": ["二分", "二分查找", "二分答案"],
    "basic/greedy.md": ["贪心"],
    "basic/enumerate.md": ["枚举"],
    "basic/sort.md": ["排序"],
    "basic/prefix-sum.md": ["前缀和", "差分"],
    "basic/quick-pow.md": ["快速幂"],
    "basic/simulate.md": ["模拟"],
    "basic/merge-sort.md": ["归并排序"],
    "basic/bubble-sort.md": ["冒泡排序"],
    "basic/selection-sort.md": ["选择排序"],
    "basic/insertion-sort.md": ["插入排序"],
    "basic/counting-sort.md": ["计数排序"],
    "basic/radix-sort.md": ["基数排序"],
    "basic/heap-sort.md": ["堆排序"],
    "basic/stl-sort.md": ["STL排序"],
    "basic/bucket-sort.md": ["桶排序"],
    "search/dfs.md": ["深度优先搜索", "DFS"],
    "search/bfs.md": ["广度优先搜索", "BFS"],
    "search/backtracking.md": ["回溯"],
    "search/astar.md": ["A*", "启发式搜索"],
    "search/alpha-beta.md": ["Alpha-Beta剪枝", "博弈搜索"],
    "search/dlx.md": ["DLX", "舞蹈链"],
    "search/iterative.md": ["迭代加深", "IDA*"],
    "search/bidirectional.md": ["双向搜索", "meet in middle"],
    "geometry/convex-hull.md": ["凸包"],
    "geometry/2d.md": ["二维几何", "计算几何基础"],
    "geometry/inverse.md": ["反演"],
    "geometry/half-plane.md": ["半平面交"],
    "geometry/scanning.md": ["扫描线"],
    "geometry/rotating-calipers.md": ["旋转卡壳"],
    "misc/cc-basic.md": ["复杂度", "复杂度分析"],
    "misc/discrete.md": ["离散化"],
    "misc/fraction-programming.md": ["分数规划", "01分数规划"],
}

# 文件名里无意义的词（不该当检索键）
STOP_TOKENS = {"index", "basic", "intro", "md"}

RE_HEADING = re.compile(r"^\s*#{1,6}\s+")
RE_META = re.compile(r"^[a-zA-Z_]+:\s")
RE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
RE_NOISE = re.compile(r"[`*$_]")


def first_paragraph(text: str) -> str:
    """取第一段有意义的正文

    OI Wiki 的页面**没有 H1 标题**，且部分文件元数据裸在开头
    （如 `author: xxx` 直接起行），所以要跳过这些。
    """
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if RE_HEADING.match(s):
            continue
        if s.startswith("???") or s.startswith("!!!") or s.startswith("!["):
            continue
        if RE_META.match(s):
            continue
        if s.startswith("|") or s.startswith("-") or s.startswith("*") or s.startswith(">"):
            continue
        if s.startswith("```"):
            continue
        s = RE_LINK.sub(r"\1", s)
        s = RE_NOISE.sub("", s)
        return s.strip()
    return ""


def split_camel(name: str) -> str:
    """Codeforces 那种驼峰写法拆开（方便匹配），这里主要用于英文全称提取"""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def build() -> dict:
    entries = []
    no_desc = 0
    for f in sorted(CLEAN.rglob("*.md")):
        rel = str(f.relative_to(CLEAN)).replace("\\", "/")
        text = f.read_text(encoding="utf-8", errors="ignore")

        # 名称：优先用人工表里的中文名，否则用文件名
        stem = f.stem
        keys: list[str] = []
        name = ""

        manual = ALIASES.get(rel)
        if manual:
            name = manual[0]
            for a in manual:
                keys.append(a)
        else:
            # 没有人工别名时，用文件名当名字（英文），并拆开连字符
            name = stem
            keys.append(stem)
            if "-" in stem:
                keys.append(stem.replace("-", " "))

        # 路径片段也能当检索键（如 math/number-theory/basic.md → number theory）
        parts = rel.replace(".md", "").split("/")
        for p in parts:
            if p in STOP_TOKENS:
                continue
            keys.append(p)
            if "-" in p:
                keys.append(p.replace("-", " "))

        desc = first_paragraph(text)
        if not desc:
            no_desc += 1

        # 去重、去空、限长
        seen: set[str] = set()
        clean_keys: list[str] = []
        for k in keys:
            kk = k.strip().lower()
            if not kk or kk in seen or kk in STOP_TOKENS:
                continue
            seen.add(kk)
            clean_keys.append(kk)

        entries.append({
            "path": rel,
            "name": name,
            "keys": clean_keys,
            "desc": desc[:160],
        })

    return {
        "version": 1,
        "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "count": len(entries),
        "entries": entries,
    }


def write_report(idx: dict) -> None:
    entries = idx["entries"]
    no_desc = sum(1 for e in entries if not e["desc"])
    with_manual = sum(1 for e in entries
                      if e["path"] in ALIASES)
    total_keys = sum(len(e["keys"]) for e in entries)

    lines = [
        "# 知识索引构建报告（轻量关键词版）",
        "",
        f"生成时间：{idx['generated']}",
        "",
        "## 为什么用关键词而不是向量",
        "",
        "语义索引（bge-small + reranker）约 **42 MB**，打进 App 太重。",
        "而检索目标很明确——**把用户说的词映射到一个词条**，",
        "不是做问答理解。关键词匹配对这个任务是够的。",
        "",
        "## 索引内容",
        "",
        "每条只放四样东西（**不放全文**）：",
        "",
        "| 字段 | 说明 |",
        "|---|---|",
        "| `path` | 词条路径，用于回显来源 |",
        "| `name` | 词条名（尽量用中文） |",
        "| `keys` | 检索键：名称 + 别名 + 文件名 + 路径片段 |",
        "| `desc` | 首段描述（一两句话，给 Agent 当上下文） |",
        "",
        "## 统计",
        "",
        f"| 项目 | 数值 |",
        f"|---|---|",
        f"| 词条总数 | {len(entries)} |",
        f"| 有人工中文别名 | {with_manual} |",
        f"| 检索键总数 | {total_keys} |",
        f"| 平均每词条键数 | {total_keys // max(len(entries), 1)} |",
        f"| **缺描述** | **{no_desc}** |",
        "",
    ]

    if no_desc > 0:
        lines += [
            f"⚠️ 有 {no_desc} 个词条没提取到描述——这些页面的开头是表格或列表。",
            "不影响检索（还有名称和别名），但 Agent 拿不到上下文。",
            "",
        ]

    missing = [e["path"] for e in entries if e["path"] not in ALIASES]
    lines += [
        "## 没有人工别名的词条（靠文件名检索）",
        "",
        f"共 {len(missing)} 个。这些词条的检索键只有英文文件名和路径片段，",
        "中文用户可能问不中。**优先补高频的**：",
        "",
    ]
    for p in missing[:40]:
        lines.append(f"- `{p}`")
    if len(missing) > 40:
        lines.append(f"- …还有 {len(missing) - 40} 个")

    lines += [
        "",
        "## 用法",
        "",
        "```bash",
        "python build_app_index.py",
        "```",
        "",
        "产出 `data/kb_index.json`，随 App 打包进 `resources/rawfile/`。",
        "",
        "> 本报告由 `build_app_index.py` 自动生成。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not CLEAN.exists():
        raise SystemExit(f"找不到语料目录：{CLEAN}")
    print("构建知识索引…")
    idx = build()
    OUT.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(idx)

    size_kb = OUT.stat().st_size / 1024
    print(f"词条数：{idx['count']}")
    print(f"索引大小：{size_kb:.1f} KB")
    print(f"已写出：\n  {OUT}\n  {REPORT}")


if __name__ == "__main__":
    main()
