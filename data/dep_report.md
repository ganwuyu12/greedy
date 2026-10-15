# 依赖关系解析报告

生成时间：2026-10-15T11:02:44+08:00

## 一、总览

| 项目 | 数值 |
|---|---|
| 知识点文件 | 418 |
| 链接总数（去代码块后） | 3876 |
| 其中指向知识点的链接 | 1280 |
| 有引用的文件 | 265 |
| **引用覆盖率** | **63.4%** |
| 引用边总数 | 956 |
| 未解析的链接 | 15 |
| ↳ 其中指向已排除目录 | 15（预期行为） |
| ↳ 真正异常 | 0 |

## 二、被引用最多的知识点（基础中的基础）

这些是被依赖最多的节点，**学习路线里应该靠前**：

| 知识点 | 被引用次数 |
|---|---|
| `math/number-theory/basic.md` | 19 |
| `math/algebra/basic.md` | 17 |
| `math/number-theory/euler-totient.md` | 16 |
| `math/order-theory.md` | 15 |
| `graph/concept.md` | 13 |
| `math/number-theory/fermat.md` | 13 |
| `math/algebra/group-theory.md` | 12 |
| `math/number-theory/gcd.md` | 11 |
| `math/binary-exponentiation.md` | 10 |
| `graph/shortest-path.md` | 10 |
| `math/algebra/ring-theory.md` | 10 |
| `math/number-theory/crt.md` | 10 |
| `math/number-theory/primitive-root.md` | 10 |
| `math/permutation.md` | 9 |
| `math/bit.md` | 9 |

## 三、引用别人最多的知识点（依赖最重的）

这些知识点前置要求最多，**适合放在路线后段**：

| 知识点 | 引用数 |
|---|---|
| `contest/roadmap.md` | 54 |
| `math/algebra/field-theory.md` | 18 |
| `dp/opt/dp-opt.md` | 17 |
| `math/algebra/ring-theory.md` | 16 |
| `math/number-theory/continued-fraction.md` | 16 |
| `math/number-theory/basic.md` | 15 |
| `math/number-theory/mod-arithmetic.md` | 15 |
| `math/number-theory/residue.md` | 14 |
| `math/number-theory/stern-brocot.md` | 14 |
| `math/permutation.md` | 14 |
| `ds/seg.md` | 13 |
| `math/linear-programming.md` | 13 |
| `lang/pas-cpp.md` | 12 |
| `math/algebra/basic.md` | 11 |
| `math/combinatorics/fibonacci.md` | 10 |

## 四、无引用的知识点

共 153 个，应多为最基础的入口页：

- `basic/bubble-sort.md`
- `basic/bucket-sort.md`
- `basic/greedy.md`
- `basic/index.md`
- `basic/insertion-sort.md`
- `basic/selection-sort.md`
- `basic/simulate.md`
- `basic/tim-sort.md`
- `contest/icpc.md`
- `contest/index.md`
- `contest/io.md`
- `contest/resources.md`
- `dp/count.md`
- `dp/index.md`
- `dp/interval.md`
- `dp/opt/state.md`
- `ds/aa-tree.md`
- `ds/avl.md`
- `ds/binary-heap.md`
- `ds/bit-in-block-array.md`
- `ds/block-array.md`
- `ds/block-list.md`
- `ds/cartesian-tree.md`
- `ds/divide-combine.md`
- `ds/dsu-complexity.md`
- `ds/ett.md`
- `ds/finger-tree.md`
- `ds/hash.md`
- `ds/huffman-tree.md`
- `ds/index.md`
- …（其余 123 个见 JSON）

## 五、结论与说明

- 引用覆盖率 **63.4%**（达标，> 60%）

⚠️ **重要**：本报告解析的是「引用关系」，**不等于「前置依赖」**。一个知识点引用另一个，可能只是「参见」。

因此：
- `references` 用于**提示**用户「你可能会用到这些」
- `prerequisites` 需要**人工确认**，用于**拦截**（前期检查）

两者分开，是为了避免「学线段树前请先学完 200 篇」这种过度拦截。

> 本报告由 `parse_deps.py` 自动生成。