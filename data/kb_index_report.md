# 知识索引构建报告（轻量关键词版）

生成时间：2026-10-16T17:40:29+08:00

## 为什么用关键词而不是向量

语义索引（bge-small + reranker）约 **42 MB**，打进 App 太重。
而检索目标很明确——**把用户说的词映射到一个词条**，
不是做问答理解。关键词匹配对这个任务是够的。

## 索引内容

每条只放四样东西（**不放全文**）：

| 字段 | 说明 |
|---|---|
| `path` | 词条路径，用于回显来源 |
| `name` | 词条名（尽量用中文） |
| `keys` | 检索键：名称 + 别名 + 文件名 + 路径片段 |
| `desc` | 首段描述（一两句话，给 Agent 当上下文） |

## 统计

| 项目 | 数值 |
|---|---|
| 词条总数 | 418 |
| 有人工中文别名 | 113 |
| 检索键总数 | 1110 |
| 平均每词条键数 | 2 |
| **缺描述** | **3** |

⚠️ 有 3 个词条没提取到描述——这些页面的开头是表格或列表。
不影响检索（还有名称和别名），但 Agent 拿不到上下文。

## 没有人工别名的词条（靠文件名检索）

共 305 个。这些词条的检索键只有英文文件名和路径片段，
中文用户可能问不中。**优先补高频的**：

- `basic/amortized-analysis.md`
- `basic/bucket-sort.md`
- `basic/complexity.md`
- `basic/construction.md`
- `basic/index.md`
- `basic/insertion-sort.md`
- `basic/quick-sort.md`
- `basic/selection-sort.md`
- `basic/shell-sort.md`
- `basic/simulate.md`
- `basic/sort-intro.md`
- `basic/stl-sort.md`
- `basic/tim-sort.md`
- `basic/tournament-sort.md`
- `basic/use-of-sort.md`
- `contest/common-mistakes.md`
- `contest/common-tricks.md`
- `contest/dictionary.md`
- `contest/icpc.md`
- `contest/index.md`
- `contest/interaction.md`
- `contest/io.md`
- `contest/oi.md`
- `contest/problems.md`
- `contest/problemsetting.md`
- `contest/resources.md`
- `contest/roadmap.md`
- `dp/basic.md`
- `dp/dag.md`
- `dp/dp-of-dp.md`
- `dp/dynamic.md`
- `dp/index.md`
- `dp/memo.md`
- `dp/opt/dp-opt.md`
- `dp/opt/state.md`
- `dp/opt/wqs-binary-search.md`
- `ds/aa-tree.md`
- `ds/avl.md`
- `ds/balanced-in-seg.md`
- `ds/binary-heap.md`
- …还有 265 个

## 用法

```bash
python build_app_index.py
```

产出 `data/kb_index.json`，随 App 打包进 `resources/rawfile/`。

> 本报告由 `build_app_index.py` 自动生成。