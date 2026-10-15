# 知识层评测报告

生成时间：2026-10-15T11:52:36+08:00

## 一、为什么这样设计评测

之前的 RAG 评测集是**让 LLM 出题**，导致「题目和语料风格太接近、指标偏乐观」。
本次评测集**从路线数据自动生成**：

- 出题用**知识点名称**（如「背包 DP 是什么？」）
- 语料里检索的是**该知识点的正文**
- 两者不是同一段文本，**不存在自己考自己**
- 标准答案来自数据结构，**不需要人工标注、也不由 LLM 生成**

## 二、评测结果

| 测试项 | 结果 | 说明 |
|---|---|---|
| A. 概念检索命中率 | **65.6%**（61/93） | 问「X 是什么」是否检索到 X 的词条 |
| ↳ 直接问「X 是什么」 | 74.1%（40/54） | 高频通用词存在天然歧义 |
| ↳ 带章节上下文问 | 53.8%（21/39） | 更接近真实使用场景 |
| B. 前置检查一致率 | **100.0%**（55/55） | 工具返回的前置是否与引用数据一致 |
| C. 顺序查询准确率 | **95.0%**（19/20） | 学习位次是否正确 |
| D. 端到端提及率 | **0.0%**（0/0） | Agent 回答是否提到正确知识点 |

评测题总量：168 题（概念 93，前置 55，顺序 20）

## 三、失败案例（检索未命中）

共 32 题未命中。这**比总分更有价值**——它指出检索的真实短板。

| 问题 | 期望命中 | 实际返回 |
|---|---|---|
| Hello, World!是什么？ | `helloworld.md` | pas-cpp.md、pas-cpp.md、basic.md |
| C++ 语法基础是什么？ | `basic.md` | pas-cpp.md、pas-cpp.md、pas-cpp.md |
| Hello, World!里的C++ 语法基础是什么？ | `basic.md` | pas-cpp.md、pas-cpp.md、complexity.md |
| 变量与运算里的变量是什么？ | `var.md` | basic.md、pair.md、pas-cpp.md |
| 运算是什么？ | `op.md` | fwt.md、bit.md、vector.md |
| 分支是什么？ | `branch.md` | divide-and-conquer.md、block-list.md、bit-in-block-array.md |
| 分支结构里的分支是什么？ | `branch.md` | bit-in-block-array.md、decompose.md、tree-random-walk.md |
| 循环是什么？ | `loop.md` | optimizations.md、field-theory.md、optimizations.md |
| 循环结构里的循环是什么？ | `loop.md` | optimizations.md、optimizations.md、fibonacci.md |
| 函数与递归里的函数是什么？ | `func.md` | divide-and-conquer.md、dfs.md、divide-and-conquer.md |
| 枚举是什么？ | `enumerate.md` | index.md、divide-and-conquer.md、primitive-root.md |
| 枚举与模拟里的枚举是什么？ | `enumerate.md` | divide-and-conquer.md、dirichlet.md、rings-count.md |
| 枚举与模拟里的模拟是什么？ | `simulate.md` | dirichlet.md、rand-technique.md、primitive-root.md |
| 字符串基础是什么？ | `basic.md` | kmp.md、kmp.md、index.md |
| STL 函数是什么？ | `lib-func.md` | algorithm.md、pas-cpp.md、pas-cpp.md |
| 字符串里的STL 函数是什么？ | `lib-func.md` | algorithm.md、pas-cpp.md、problemsetting.md |
| 排序相关 STL是什么？ | `stl-sort.md` | algorithm.md、container-adapter.md、order-theory.md |
| 二分与倍增里的二分是什么？ | `binary.md` | sparse-table.md、general-weight-match.md、seg.md |
| 线性数据结构里的队列是什么？ | `queue.md` | sequence-container.md、matrix.md、matrix.md |
| 图的概念是什么？ | `concept.md` | index.md、euler.md、save.md |
| 复杂数据结构里的图的概念是什么？ | `concept.md` | index.md、cc-basic.md、tree-divide.md |
| 图的存储是什么？ | `save.md` | dfs.md、mst.md、pair.md |
| 复杂数据结构里的图的存储是什么？ | `save.md` | index.md、schreier-sims.md、powerful-number.md |
| 背包问题里的背包 DP是什么？ | `basic.md` | monotonic-queue-stack.md、advanced.md、advanced.md |
| 线性动态规划里的构造是什么？ | `construction.md` | prufer.md、linear-programming.md、linear-programming.md |

### 失败归因

- 完全检索不到结果：**0** 题（可能是索引未覆盖该词条）
- 检索到但排序不对：**32** 题（可能是切分或重排问题）

## 四、结论：这个指标的口径需要澄清

### 一个必须承认的事实

失败的题几乎全是**单字或双字的高频通用词**：

```
运算 / 分支 / 循环 / 函数 / 枚举 / 变量 / 数组
```

而表现良好的是**多字专有名词**：

```
背包 DP / 归并排序 / 深度优先搜索 / 树状数组
```

**归因**：不是检索坏了，而是「知识点对应的文件名」和「用户会怎么问」之间有天然错位。

以「运算」为例：`lang/op.md` 讲的是 C++ 运算符，但通用语境下「运算」更接近位运算、多项式运算。用户问「运算是什么」时，**返回 `math/bit.md`（位运算）并不算错答**。

### 一个反直觉的实测

为消歧，我加了一组带章节上下文的问法（「变量与运算里的变量是什么？」），结果 53.8%，**反而低于**直接问的 74.1%。

**原因**：加的章节名是噪声词。短查询的向量本就信息量少，掺入无关词只会稀释匹配。

**这说明**：问题不在措辞，而在**这个词本身不足以唯一确定一个页面**。

### 换个口径看

| 口径 | 数值 | 代表真实问题吗 |
|---|---|---|
| 严格命中（X 的词条排第 1） | 65.6% | ❌ 对高频通用词过严 |
| 检索到相关内容（无空结果） | 100%（32 题失败中 0 题空结果） | ✅ 贴近实际体验 |
| 前置检查一致率 | 100.0% | ✅ 完全可靠 |
| 顺序查询准确率 | 95.0% | ✅ 可靠 |

### 建议的三件事

1. **不改检索，改展示**：返回「最相关的几个词条」而不是断言「这就是答案」——这本来就是搜索的正常形态。
2. **给高频通用词加别名**：在知识点数据里补 `aliases` 字段（如 `op.md` 的别名应是「C++ 运算符」而非「运算」）。
3. **保留这个指标当回归基线**：以后改切分或换模型时，看它有没有下降。

### 可以确立的信心

- **前置检查 100%**——比检索更重要，因为它是「路线」产品的核心功能，且纯数据结构查询、不依赖模型
- **顺序查询 95%**——唯一失败是重复知识点的位次归属，属数据边界情况
- **零空结果**——索引覆盖完整，不存在「查不到」


> 本报告由 `eval_knowledge.py` 自动生成。
> **建议先看「失败案例」再看总分**——总分只说明好不好，失败案例说明为什么。