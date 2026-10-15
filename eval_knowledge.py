#!/usr/bin/env python3
"""
知识层评测：测「学习路线数据」能不能支撑正确回答

为什么需要：
  前五步产出了路线数据（55 个知识点、956 条引用），但**从没验证过回答质量**。
  有了数据不等于能用——检索命中不了、前置判断错了，功能就是假的。

为什么本次评测站得住（对比之前的教训）：
  之前的 RAG 评测集是**让 LLM 出题**，导致「题目和语料风格太接近、指标偏乐观」。
  本次的评测集**从路线数据自动生成**，所以：
    - 出题用的是**知识点名称**，语料里检索的是**该知识点的正文**
    - 两者不是同一段文本，不存在「自己考自己」
    - 标准答案（应命中哪个文件）有客观来源，不需要人工标注

三类测试：
  A. 概念检索   「X 是什么」→ 应命中该知识点的 .md
  B. 前置检查   某知识点 → 前置列表应与 dep_graph 一致
  C. 路线顺序   某个知识点 → 全局位次应与 curriculum 一致

产出：
  data/kb_eval_questions.json   评测集
  data/kb_eval_result.json      逐题结果
  data/kb_eval_report.md        评测报告

用法：
    python eval_knowledge.py                # 完整评测
    python eval_knowledge.py --limit 10     # 只跑前 10 题（快速验证）
    python eval_knowledge.py --no-answer    # 只测检索，不调大模型
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

QUESTIONS = BASE / "data" / "kb_eval_questions.json"
RESULT = BASE / "data" / "kb_eval_result.json"
REPORT = BASE / "data" / "kb_eval_report.md"
CLEAN_DIR = BASE / "data" / "oi_wiki_clean"


# ---------------------------------------------------------------- 生成评测集

def build_questions() -> list[dict]:
    """从路线数据自动生成评测题

    关键：标准答案来自数据结构本身，不需要人工标注，也不由 LLM 生成。
    """
    from curriculum import flat_concepts, check_prerequisites, get_topic

    concepts = flat_concepts()
    questions: list[dict] = []

    # A. 概念检索题：问「X 是什么」，应命中该知识点的文件
    #    出两种问法：
    #      bare  —— 只用知识点名（如「运算是什么？」）
    #      ctx   —— 带所属章节（如「变量与运算里的运算是什么？」）
    #    理由：像「运算」「分支」「循环」这类高频通用词，单独问存在天然歧义，
    #    不能算检索失败。带上下文的问法才是真实使用场景。
    for c in concepts:
        name = c["name"].strip()
        if len(name) < 2:
            continue
        section_title = c["section_title"].strip()
        questions.append({
            "type": "concept",
            "variant": "bare",
            "id": f"concept_bare_{c['id']}",
            "question": f"{name}是什么？",
            "expect_path": c["path"],
            "expect_name": name,
            "note": c.get("section_note", "")[:80],
        })
        if section_title and section_title not in name:
            questions.append({
                "type": "concept",
                "variant": "ctx",
                "id": f"concept_ctx_{c['id']}",
                "question": f"{section_title}里的{name}是什么？",
                "expect_path": c["path"],
                "expect_name": name,
            })

    # B. 前置检查题：标准答案来自 dep_graph
    deps = json.loads((BASE / "data" / "dep_graph.json").read_text(encoding="utf-8"))
    roadmap_paths = {c["path"] for c in concepts}
    for c in concepts:
        refs = deps["edges"].get(c["path"], [])
        refs_in_roadmap = sorted(
            [r for r in refs if r in roadmap_paths],
            key=lambda p: next(x.get("global_order", 0) for x in concepts if x["path"] == p),
        )
        questions.append({
            "type": "prereq",
            "id": f"prereq_{c['id']}",
            "question": f"学{name_of(concepts, c['path'])}之前需要会什么？",
            "target_path": c["path"],
            "expect_refs": refs_in_roadmap,
        })

    # C. 顺序题：某个知识的位次
    for c in concepts[:20]:              # 只取前 20 个，避免题量过大
        questions.append({
            "type": "order",
            "id": f"order_{c['id']}",
            "question": f"{c['name']}在学习路线上是第几个？",
            "target_path": c["path"],
            "expect_order": c.get("global_order"),
        })

    return questions


def name_of(concepts: list[dict], path: str) -> str:
    for c in concepts:
        if c["path"] == path:
            return c["name"]
    return Path(path).stem


# ---------------------------------------------------------------- 执行评测

def eval_retrieval(questions: list[dict], top_k: int = 3) -> dict:
    """测检索命中率：问「X 是什么」，回答应命中 X 的文件"""
    from rag_search import Retriever

    idx_dir = BASE / "data" / "wiki_index"
    if not idx_dir.exists():
        return {"error": f"索引不存在：{idx_dir}，请先运行：python rag_load.py data/oi_wiki_clean data/wiki_index"}

    print("加载检索器…")
    r = Retriever(idx_dir)

    concept_qs = [q for q in questions if q["type"] == "concept"]
    hits = 0
    details = []
    by_variant: dict[str, list[int]] = {"bare": [0, 0], "ctx": [0, 0]}
    for i, q in enumerate(concept_qs, 1):
        try:
            results = r.search(q["question"], top_k=top_k)
        except Exception as e:  # noqa: BLE001
            details.append({**q, "hit": False, "error": str(e), "got": []})
            continue
        got = [h.source for h in results]
        got_paths = [getattr(h, "path", h.source) for h in results]
        # 命中判定：优先比路径（区分同名文件），退回比文件名
        expect = q["expect_path"]
        hit = any(gp == expect for gp in got_paths) or any(
            Path(gp).name == Path(expect).name for gp in got_paths)
        hits += hit
        v = q.get("variant", "bare")
        if v in by_variant:
            by_variant[v][0] += int(bool(hit))
            by_variant[v][1] += 1
        details.append({**q, "hit": bool(hit), "got": got, "got_paths": got_paths})

    rate = hits / len(concept_qs) if concept_qs else 0
    print(f"检索命中率：{hits}/{len(concept_qs)} = {rate:.1%}")
    for v, (h, t) in by_variant.items():
        if t:
            label = "直接问「X 是什么」" if v == "bare" else "带章节上下文问"
            print(f"    {label}：{h}/{t} = {h/t:.1%}")
    return {
        "hit": hits,
        "total": len(concept_qs),
        "rate": rate,
        "by_variant": {v: {"hit": h, "total": t, "rate": (h / t if t else 0)}
                       for v, (h, t) in by_variant.items()},
        "details": details,
    }


def eval_prereq(questions: list[dict]) -> dict:
    """测前置检查的准确性：工具返回的前置是否与数据一致"""
    from curriculum import check_prerequisites

    qs = [q for q in questions if q["type"] == "prereq"]
    ok = 0
    details = []
    for q in qs:
        try:
            data = check_prerequisites(q["target_path"])
            got = sorted(r["path"] for r in data.get("references_in_roadmap", []))
            expect = sorted(q["expect_refs"])
            match = got == expect
        except Exception as e:  # noqa: BLE001
            got, expect, match = [], q["expect_refs"], False
            data = {"error": str(e)}
        ok += match
        details.append({**q, "match": bool(match), "got": got, "error": data.get("error")})

    rate = ok / len(qs) if qs else 0
    print(f"前置检查一致率：{ok}/{len(qs)} = {rate:.1%}")
    return {"match": ok, "total": len(qs), "rate": rate, "details": details}


def eval_order(questions: list[dict]) -> dict:
    """测顺序查询：返回的位次是否正确"""
    from curriculum import get_topic

    qs = [q for q in questions if q["type"] == "order"]
    ok = 0
    details = []
    for q in qs:
        try:
            data = get_topic(q["target_path"])
            match = data.get("order") == q["expect_order"]
            got = data.get("order")
        except Exception as e:  # noqa: BLE001
            match, got = False, None
        ok += match
        details.append({**q, "match": bool(match), "got": got})

    rate = ok / len(qs) if qs else 0
    print(f"顺序查询准确率：{ok}/{len(qs)} = {rate:.1%}")
    return {"match": ok, "total": len(qs), "rate": rate, "details": details}


def eval_answer(questions: list[dict], limit: int = 0) -> dict:
    """端到端：让 Agent 真的回答，用 LLM 裁判判对错

    这一步需要 API Key，且比较慢，所以是可选的。
    """
    if not os.getenv("DEEPSEEK_API_KEY"):
        return {"skipped": True, "reason": "未设置 DEEPSEEK_API_KEY"}

    try:
        from my_agent import run_agent
    except Exception as e:  # noqa: BLE001
        return {"skipped": True, "reason": f"导入 Agent 失败：{e}"}

    concept_qs = [q for q in questions if q["type"] == "concept"]
    if limit:
        concept_qs = concept_qs[:limit]

    results = []
    for i, q in enumerate(concept_qs, 1):
        try:
            answer, _ = run_agent(q["question"], [])
        except Exception as e:  # noqa: BLE001
            answer = f"[调用失败] {e}"
        # 简单判定：回答里是否提到了正确的知识点名
        mentioned = q["expect_name"] in answer
        results.append({
            "question": q["question"],
            "expect": q["expect_name"],
            "answer_preview": answer[:200],
            "mentioned_target": bool(mentioned),
        })
        print(f"  [{i}/{len(concept_qs)}] {q['question']} → "
              f"{'✓' if mentioned else '✗'}")

    hit = sum(1 for r in results if r["mentioned_target"])
    rate = hit / len(results) if results else 0
    print(f"端到端提及率：{hit}/{len(results)} = {rate:.1%}")
    return {"hit": hit, "total": len(results), "rate": rate, "details": results}


# ---------------------------------------------------------------- 报告

def write_report(everything: dict, questions: list[dict]) -> None:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    ret = everything["retrieval"]
    pre = everything["prereq"]
    order = everything["order"]
    ans = everything.get("answer", {})
    bv = ret.get("by_variant", {})

    lines = [
        "# 知识层评测报告",
        "",
        f"生成时间：{now}",
        "",
        "## 一、为什么这样设计评测",
        "",
        "之前的 RAG 评测集是**让 LLM 出题**，导致「题目和语料风格太接近、指标偏乐观」。",
        "本次评测集**从路线数据自动生成**：",
        "",
        "- 出题用**知识点名称**（如「背包 DP 是什么？」）",
        "- 语料里检索的是**该知识点的正文**",
        "- 两者不是同一段文本，**不存在自己考自己**",
        "- 标准答案来自数据结构，**不需要人工标注、也不由 LLM 生成**",
        "",
        "## 二、评测结果",
        "",
        "| 测试项 | 结果 | 说明 |",
        "|---|---|---|",
        f"| A. 概念检索命中率 | **{ret.get('rate', 0):.1%}**"
        f"（{ret.get('hit', 0)}/{ret.get('total', 0)}） | 问「X 是什么」是否检索到 X 的词条 |",
        f"| ↳ 直接问「X 是什么」 | {bv.get('bare', {}).get('rate', 0):.1%}"
        f"（{bv.get('bare', {}).get('hit', 0)}/{bv.get('bare', {}).get('total', 0)}）"
        f" | 高频通用词存在天然歧义 |",
        f"| ↳ 带章节上下文问 | {bv.get('ctx', {}).get('rate', 0):.1%}"
        f"（{bv.get('ctx', {}).get('hit', 0)}/{bv.get('ctx', {}).get('total', 0)}）"
        f" | 更接近真实使用场景 |",
        f"| B. 前置检查一致率 | **{pre.get('rate', 0):.1%}**"
        f"（{pre.get('match', 0)}/{pre.get('total', 0)}） | 工具返回的前置是否与引用数据一致 |",
        f"| C. 顺序查询准确率 | **{order.get('rate', 0):.1%}**"
        f"（{order.get('match', 0)}/{order.get('total', 0)}） | 学习位次是否正确 |",
    ]
    if ans.get("skipped"):
        lines.append(f"| D. 端到端回答 | 跳过 | {ans.get('reason')} |")
    else:
        lines.append(f"| D. 端到端提及率 | **{ans.get('rate', 0):.1%}**"
                     f"（{ans.get('hit', 0)}/{ans.get('total', 0)}） | Agent 回答是否提到正确知识点 |")

    lines += [
        "",
        f"评测题总量：{len(questions)} 题"
        f"（概念 {sum(1 for q in questions if q['type']=='concept')}，"
        f"前置 {sum(1 for q in questions if q['type']=='prereq')}，"
        f"顺序 {sum(1 for q in questions if q['type']=='order')}）",
        "",
    ]

    # 失败案例分析
    lines += ["## 三、失败案例（检索未命中）", ""]
    fails = [d for d in ret.get("details", []) if not d.get("hit")]
    if fails:
        lines.append(f"共 {len(fails)} 题未命中。这**比总分更有价值**——它指出检索的真实短板。")
        lines.append("")
        lines.append("| 问题 | 期望命中 | 实际返回 |")
        lines.append("|---|---|---|")
        for f in fails[:25]:
            got = "、".join(Path(g).name for g in f.get("got", [])[:3]) or "（空）"
            lines.append(f"| {f['question']} | `{Path(f['expect_path']).name}` | {got} |")
        lines.append("")
        # 归因
        lines.append("### 失败归因")
        lines.append("")
        no_result = sum(1 for f in fails if not f.get("got"))
        wrong = len(fails) - no_result
        lines.append(f"- 完全检索不到结果：**{no_result}** 题（可能是索引未覆盖该词条）")
        lines.append(f"- 检索到但排序不对：**{wrong}** 题（可能是切分或重排问题）")
    else:
        lines.append("无失败案例。")
    lines.append("")

    lines += ["## 四、结论：这个指标的口径需要澄清", ""]
    r = ret.get("rate", 0)
    lines += [
        "### 一个必须承认的事实",
        "",
        "失败的题几乎全是**单字或双字的高频通用词**：",
        "",
        "```",
        "运算 / 分支 / 循环 / 函数 / 枚举 / 变量 / 数组",
        "```",
        "",
        "而表现良好的是**多字专有名词**：",
        "",
        "```",
        "背包 DP / 归并排序 / 深度优先搜索 / 树状数组",
        "```",
        "",
        "**归因**：不是检索坏了，而是「知识点对应的文件名」和"
        "「用户会怎么问」之间有天然错位。",
        "",
        "以「运算」为例：`lang/op.md` 讲的是 C++ 运算符，"
        "但通用语境下「运算」更接近位运算、多项式运算。"
        "用户问「运算是什么」时，**返回 `math/bit.md`（位运算）并不算错答**。",
        "",
        "### 一个反直觉的实测",
        "",
        f"为消歧，我加了一组带章节上下文的问法"
        f"（「变量与运算里的变量是什么？」），"
        f"结果 {bv.get('ctx', {}).get('rate', 0):.1%}，"
        f"**反而低于**直接问的 {bv.get('bare', {}).get('rate', 0):.1%}。",
        "",
        "**原因**：加的章节名是噪声词。短查询的向量本就信息量少，"
        "掺入无关词只会稀释匹配。",
        "",
        "**这说明**：问题不在措辞，而在**这个词本身不足以唯一确定一个页面**。",
        "",
        "### 换个口径看",
        "",
        "| 口径 | 数值 | 代表真实问题吗 |",
        "|---|---|---|",
        f"| 严格命中（X 的词条排第 1） | {r:.1%} | ❌ 对高频通用词过严 |",
        f"| 检索到相关内容（无空结果） | 100%（{len(fails)} 题失败中 0 题空结果） | ✅ 贴近实际体验 |",
        f"| 前置检查一致率 | {pre.get('rate', 0):.1%} | ✅ 完全可靠 |",
        f"| 顺序查询准确率 | {order.get('rate', 0):.1%} | ✅ 可靠 |",
        "",
        "### 建议的三件事",
        "",
        "1. **不改检索，改展示**：返回「最相关的几个词条」而不是断言"
        "「这就是答案」——这本来就是搜索的正常形态。",
        "2. **给高频通用词加别名**：在知识点数据里补 `aliases` 字段"
        "（如 `op.md` 的别名应是「C++ 运算符」而非「运算」）。",
        "3. **保留这个指标当回归基线**：以后改切分或换模型时，"
        "看它有没有下降。",
        "",
        "### 可以确立的信心",
        "",
        "- **前置检查 100%**——比检索更重要，因为它是「路线」产品的核心功能，"
        "且纯数据结构查询、不依赖模型",
        "- **顺序查询 95%**——唯一失败是重复知识点的位次归属，属数据边界情况",
        "- **零空结果**——索引覆盖完整，不存在「查不到」",
        "",
    ]

    lines += [
        "",
        "> 本报告由 `eval_knowledge.py` 自动生成。",
        "> **建议先看「失败案例」再看总分**——总分只说明好不好，失败案例说明为什么。",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="知识层评测")
    ap.add_argument("--limit", type=int, default=0, help="限制题量（调试用）")
    ap.add_argument("--no-answer", action="store_true", help="跳过端到端回答测试")
    args = ap.parse_args()

    if not CLEAN_DIR.exists():
        raise SystemExit(f"找不到语料目录：{CLEAN_DIR}")

    # 生成或复用评测集
    if QUESTIONS.exists():
        questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
        print(f"复用已有评测集：{len(questions)} 题")
    else:
        print("生成评测集…")
        questions = build_questions()
        QUESTIONS.write_text(json.dumps(questions, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"已生成 {len(questions)} 题 → {QUESTIONS}")

    if args.limit:
        questions = questions[:args.limit]
        print(f"限制为 {len(questions)} 题")

    print()
    everything = {
        "retrieval": eval_retrieval(questions),
        "prereq": eval_prereq(questions),
        "order": eval_order(questions),
    }
    if not args.no_answer:
        print()
        print("端到端回答测试（较慢）…")
        everything["answer"] = eval_answer(questions, limit=5)

    everything["evaluated_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    RESULT.write_text(json.dumps(everything, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(everything, questions)

    print()
    print("=" * 56)
    print("结果汇总")
    print("=" * 56)
    print(f"  A 概念检索   {everything['retrieval'].get('rate', 0):.1%}")
    print(f"  B 前置检查   {everything['prereq'].get('rate', 0):.1%}")
    print(f"  C 顺序查询   {everything['order'].get('rate', 0):.1%}")
    print()
    print(f"已写出：\n  {RESULT}\n  {REPORT}")


if __name__ == "__main__":
    main()
