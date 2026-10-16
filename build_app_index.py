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
#
# ⚠️ 结构说明（这是实测踩坑后改的）：
#   原来是 {路径: [别名]}，但**路径是猜的，17 条对不上实际文件**
#   （如 dp/knapsack.md 实际是 dp/knapsack/basic.md + advanced.md）。
#   现在改成 {别名: [路径关键词]}——用关键词去匹配实际路径，
#   语料结构变了也不会失效。
#
# 匹配规则：关键词出现在路径里即认为该别名适用（允许多个命中）。
ALIAS_RULES: list[tuple[str, list[str]]] = [
    # ---- 数据结构 ----
    ("线段树", ["ds/seg"]),
    ("segment tree", ["ds/seg"]),
    ("树状数组", ["ds/fenwick"]),
    ("BIT", ["ds/fenwick"]),
    ("二叉搜索树", ["ds/bst"]),
    ("BST", ["ds/bst"]),
    ("并查集", ["ds/dsu"]),
    ("union find", ["ds/dsu"]),
    ("ST表", ["ds/sparse-table"]),
    ("稀疏表", ["ds/sparse-table"]),
    ("主席树", ["ds/persistent-seg"]),
    ("可持久化线段树", ["ds/persistent-seg"]),
    ("单调队列", ["monotonic-queue"]),
    ("单调栈", ["monotonic-stack"]),
    ("左偏树", ["leftist-tree"]),
    ("可并堆", ["leftist-tree"]),
    ("块状链表", ["block-list"]),
    ("字典树", ["string/trie"]),
    ("Trie", ["string/trie"]),
    ("前缀树", ["string/trie"]),
    ("后缀数组", ["string/sa"]),
    ("后缀自动机", ["string/sam"]),
    ("字符串哈希", ["string/hash"]),

    # ---- 动态规划 ----
    ("背包", ["dp/knapsack"]),
    ("背包问题", ["dp/knapsack"]),
    ("区间DP", ["dp/interval"]),
    ("树形DP", ["dp/tree"]),
    ("数位DP", ["dp/digit", "dp/number", "dp/count"]),
    ("数位动态规划", ["dp/digit", "dp/number", "dp/count"]),
    ("状压DP", ["dp/state", "dp/bit"]),
    ("状态压缩", ["dp/state", "dp/bit"]),
    ("插头DP", ["dp/plug"]),
    ("单调队列优化", ["dp/opt/monotonic", "monotonic-queue-stack"]),
    ("斜率优化", ["dp/opt/slope", "slope"]),
    ("四边形不等式", ["dp/opt/quadrangle"]),

    # ---- 图论 ----
    ("最短路", ["graph/shortest-path"]),
    ("最短路径", ["graph/shortest-path"]),
    ("dijkstra", ["graph/shortest-path"]),
    ("最小生成树", ["graph/mst"]),
    ("MST", ["graph/mst"]),
    ("kruskal", ["graph/mst"]),
    ("拓扑排序", ["graph/topo"]),
    ("强连通分量", ["graph/scc"]),
    ("SCC", ["graph/scc"]),
    ("tarjan", ["graph/scc"]),
    ("最近公共祖先", ["graph/lca"]),
    ("LCA", ["graph/lca"]),
    ("二分图", ["bipartite"]),
    ("匈牙利算法", ["bipartite", "graph-match"]),
    ("最大流", ["max-flow"]),
    ("网络流", ["flow"]),
    ("最小费用流", ["min-cost"]),
    ("2-SAT", ["2-sat"]),
    ("树的直径", ["tree-diameter"]),

    # ---- 字符串 ----
    ("KMP", ["string/kmp"]),
    ("AC自动机", ["ac-automaton"]),
    ("回文串", ["manacher"]),
    ("Manacher", ["manacher"]),
    ("Z函数", ["z-func"]),
    ("扩展KMP", ["z-func"]),

    # ---- 数学 ----
    ("数论基础", ["number-theory/basic"]),
    ("素数", ["number-theory/prime", "number-theory/basic"]),
    ("质数", ["number-theory/prime", "number-theory/basic"]),
    ("筛法", ["number-theory/sieve"]),
    ("线性筛", ["number-theory/sieve"]),
    ("埃氏筛", ["number-theory/sieve"]),
    ("最大公约数", ["number-theory/gcd"]),
    ("gcd", ["number-theory/gcd"]),
    ("欧拉函数", ["euler-totient"]),
    ("中国剩余定理", ["number-theory/crt"]),
    ("CRT", ["number-theory/crt"]),
    ("扩展欧几里得", ["bezouts", "euclidean"]),
    ("莫比乌斯反演", ["mobius"]),
    ("莫反", ["mobius"]),
    ("组合数", ["combinatorics/combination"]),
    ("卡特兰数", ["catalan"]),
    ("容斥原理", ["inclusion-exclusion"]),
    ("抽屉原理", ["drawer-principle"]),
    ("鸽巢原理", ["drawer-principle"]),
    ("博弈论", ["game-theory"]),
    ("SG函数", ["game-theory"]),
    ("矩阵乘法", ["linear-algebra/matrix"]),
    ("矩阵快速幂", ["linear-algebra/matrix"]),
    ("高斯消元", ["gauss"]),
    ("FFT", ["poly/fft"]),
    ("快速傅里叶变换", ["poly/fft"]),
    ("NTT", ["poly/ntt"]),
    ("FWT", ["poly/fwt"]),
    ("期望", ["probability", "expectation"]),
    ("离散化", ["misc/discrete"]),

    # ---- 基础算法 ----
    ("分治", ["divide-and-conquer"]),
    ("二分", ["basic/binary"]),
    ("二分查找", ["basic/binary"]),
    ("二分答案", ["basic/binary"]),
    ("贪心", ["basic/greedy", "greedy"]),
    ("枚举", ["basic/enumerate"]),
    ("前缀和", ["prefix-sum"]),
    ("差分", ["prefix-sum", "difference"]),
    ("快速幂", ["quick-pow", "binary-exponentiation"]),
    ("归并排序", ["merge-sort"]),
    ("冒泡排序", ["bubble-sort"]),
    ("堆排序", ["heap-sort"]),
    ("计数排序", ["counting-sort"]),
    ("基数排序", ["radix-sort"]),

    # ---- 搜索 ----
    ("深度优先搜索", ["search/dfs"]),
    ("DFS", ["search/dfs"]),
    ("广度优先搜索", ["search/bfs"]),
    ("BFS", ["search/bfs"]),
    ("回溯", ["backtracking"]),
    ("剪枝", ["pruning", "alpha-beta"]),
    ("启发式搜索", ["astar"]),
    ("双向搜索", ["bidirectional", "meet-in-middle"]),
    ("迭代加深", ["iterative"]),
    ("舞蹈链", ["dlx"]),

    # ---- 几何 ----
    ("凸包", ["convex-hull"]),
    ("扫描线", ["scanning"]),
    ("旋转卡壳", ["rotating-calipers"]),
    ("半平面交", ["half-plane"]),
    ("计算几何", ["geometry/2d"]),

    # ---- 杂项 ----
    ("复杂度", ["cc-basic"]),
    ("时间复杂度", ["cc-basic"]),
    ("分数规划", ["fraction"]),
]

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


def match_aliases(rel: str) -> list[str]:
    """按关键词匹配出适用于该路径的所有别名

    为什么要这样：原来按完整路径精确匹配，路径猜错就彻底失效
    （实测 17 条对不上）。改成关键词模糊匹配后，
    语料结构调整（如 dp/knapsack.md 拆成 basic/advanced）也不会失效。

    ⚠️ 但关键词匹配会过宽：「ds/seg」同时命中 seg.md 和 seg-beats.md。
    所以返回值带上**匹配强度**，由调用方优先取强的：
      2 = 路径以关键词结尾（最精确，如 ds/seg 命中 ds/seg.md）
      1 = 关键词只是路径的一部分（如 ds/seg 命中 ds/seg-beats.md）
    """
    low = rel.lower().replace(".md", "")
    out: list[tuple[str, int]] = []
    for alias, keywords in ALIAS_RULES:
        best = 0
        for kw in keywords:
            k = kw.lower()
            if low.endswith("/" + k) or low == k:
                best = max(best, 2)      # 精确：路径结尾就是它
            elif k in low:
                best = max(best, 1)      # 宽泛：只是包含
        if best > 0:
            out.append((alias, best))
    # 强的排前面，这样 name 取到的是最精确的那个
    out.sort(key=lambda x: -x[1])
    return [a for a, _ in out]


def alias_strength(rel: str) -> int:
    """该路径的别名匹配强度（2 精确 / 1 宽泛 / 0 无）"""
    low = rel.lower().replace(".md", "")
    best = 0
    for _alias, keywords in ALIAS_RULES:
        for kw in keywords:
            k = kw.lower()
            if low.endswith("/" + k) or low == k:
                best = max(best, 2)
            elif k in low:
                best = max(best, 1)
    return best


def build() -> dict:
    entries = []
    no_desc = 0
    for f in sorted(CLEAN.rglob("*.md")):
        rel = str(f.relative_to(CLEAN)).replace("\\", "/")
        text = f.read_text(encoding="utf-8", errors="ignore")

        stem = f.stem
        keys: list[str] = []

        manual = match_aliases(rel)
        if manual:
            # 有中文别名时，用第一个当名字
            name = manual[0]
            for a in manual:
                keys.append(a)
        else:
            # 没有人工别名时，用文件名当名字（英文），并拆开连字符
            name = stem
            keys.append(stem)
            if "-" in stem:
                keys.append(stem.replace("-", " "))
        # 文件名本身始终保留为检索键——这样中英文都能搜到
        keys.append(stem)

        # 删掉路径片段当检索键的做法。
        #
        # 为什么：路径片段（如 "seg"、"ds"）会命中一大片无关文件，
        # 实测「线段树」因此命中 ds/seg-beats.md 而不是 ds/seg.md。
        # 保留文件名本身就够了，中文靠人工别名。
        #
        # 但把「完整相对路径」作为一个检索键——它唯一，不会误伤。

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
        # 完整路径也进检索键（唯一，精确匹配用）
        clean_keys.append(rel.lower().replace(".md", ""))

        entries.append({
            "path": rel,
            "name": name,
            "keys": clean_keys,
            "desc": desc[:160],
            # 别名匹配强度：检索排序时用来区分主次
            # （如「线段树」应排 ds/seg.md 而不是 ds/seg-beats.md）
            "tier": alias_strength(rel),
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
    with_manual = sum(1 for e in entries if len(match_aliases(e["path"])) > 0)
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

    missing = [e["path"] for e in entries if len(match_aliases(e["path"])) == 0]
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
