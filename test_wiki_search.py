#!/usr/bin/env python3
"""
验证知识索引的检索质量

为什么需要：`WikiIndex.ets` 里的打分算法是新写的（四级打分 + 字符交叠），
从没验证过。而且它在设备上很难测（UI 自动化输入中文有障碍）。

所以先在这里用**同样的算法**跑一遍，看召回质量——
两边算法必须一致，否则测了不算数。

用法：
    python test_wiki_search.py
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
INDEX = BASE / "data" / "kb_index.json"

MIN_KEY_LEN = 2
MIN_SCORE = 25


def overlap_ratio(a: str, b: str) -> float:
    """字符交叠比例（与 ArkTS 版逐行对齐）"""
    set_a = set(a)
    set_b = set(b)
    denom = min(len(set_a), len(set_b))
    return 0.0 if denom == 0 else len(set_a & set_b) / denom


def score(q: str, k: str) -> int:
    """四级打分（与 ArkTS 版逐行对齐）"""
    if q == k:
        return 100
    if k in q:
        return 80 + min(len(k), 6)
    if q in k:
        return 60 + min(len(q), 6)
    r = overlap_ratio(q, k)
    if r >= 0.6:
        return round(r * 40)
    return 0


def search(entries: list[dict], query: str, top_k: int = 3) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    out = []
    for e in entries:
        best = 0
        for k in e["keys"]:
            if len(k) < MIN_KEY_LEN:
                continue
            s = score(q, k)
            if s > best:
                best = s
        if best >= MIN_SCORE:
            out.append({**e, "score": best})
    # 同分时，别名匹配更精确的排前面
    # （如「线段树」应排 ds/seg.md 而不是 ds/seg-beats.md）
    out.sort(key=lambda x: (-x["score"], -x.get("tier", 0), len(x["path"])))
    return out[:top_k]


def main() -> None:
    idx = json.loads(INDEX.read_text(encoding="utf-8"))
    entries = idx["entries"]
    print(f"索引词条：{len(entries)}")
    print()

    # 测试用例：用户会怎么问
    #
    # ⚠️ 期望值以**语料的实际结构**为准，不是我以为的路径。
    #    第一版凭印象写期望，导致 4 个"失败"其实是我期望写错了
    #    （如数位 DP 在语料里是 dp/count.md，不是 dp/digit.md）。
    cases: list[tuple[str, str]] = [
        # (查询, 期望命中的路径关键字)
        ("线段树", "ds/seg.md"),
        ("树状数组", "ds/fenwick"),
        ("并查集", "ds/dsu"),
        ("数位DP", "dp/count"),
        ("数位动态规划", "dp/count"),
        ("背包", "dp/knapsack"),
        ("最短路", "graph/shortest-path"),
        ("最小生成树", "graph/mst"),
        ("KMP", "string/kmp"),
        ("字典树", "string/trie"),
        ("后缀数组", "string/sa.md"),
        ("二分查找", "basic/binary"),
        ("快速幂", "binary-exponent"),
        ("欧拉函数", "number-theory/euler-totient"),
        ("中国剩余定理", "number-theory/crt"),
        ("莫比乌斯反演", "number-theory/mobius"),
        ("容斥原理", "inclusion-exclusion"),
        ("博弈论", "game-theory"),
        ("凸包", "geometry/convex-hull"),
        ("复杂度", "cc-basic"),
        # 口语化 / 容错
        ("线段数", "ds/seg.md"),         # 常见错别字
        ("树状数", "ds/fenwick"),        # 常见错别字
        ("LCA", "graph/lca"),
        ("st表", "ds/sparse-table"),
        ("什么是线段树", "ds/seg.md"),    # 带前缀
    ]

    hit = 0
    print(f"{'查询':<16} {'命中':<28} {'分数':>5}  {'结果'}")
    print("-" * 78)
    for q, expect in cases:
        res = search(entries, q, 3)
        top = res[0] if res else None
        ok = top is not None and expect in top["path"]
        hit += ok
        mark = "✓" if ok else "✗"
        got = f"{top['name']}({top['path']})" if top else "（无结果）"
        if len(got) > 26:
            got = got[:24] + "…"
        sc = top["score"] if top else 0
        print(f"{q:<16} {mark} {got:<28} {sc:>5}  ", end="")
        if not ok and res:
            print("其他候选：" + "、".join(r["name"] for r in res[1:]))
        else:
            print()

    print()
    print(f"命中率：{hit}/{len(cases)} = {hit / len(cases):.1%}")


if __name__ == "__main__":
    main()
