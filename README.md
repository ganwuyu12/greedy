# 贪心（greedy）

面向算法学习者的 AI 学习助手。同时服务两类人：

- **初学者**——需要体系化的路径，知道先学什么、学完练哪道
- **进阶爱好者**——需要针对性诊断，找出真实短板

核心差异是**三层知识架构**：路线骨架（有学习顺序）+ 理论讲解（OI Wiki）+ 实操范例（个人题解）。

---

## 快速开始

### 1. 环境

```bash
# 需要 Python 3.12+ 和 uv
pip install uv
uv sync
```

### 2. 配置密钥

在项目根目录创建 `.env`：

```
DEEPSEEK_API_KEY=你的密钥
```

### 3. 重建数据（**首次必做**）

语料和索引体积大，不入 git，需要本地重建：

```bash
# ① 下载 OI Wiki 语料（约 53 MB）
git clone --depth=1 https://github.com/OI-wiki/OI-wiki.git _oiwiki_tmp
mkdir -p data/oi_wiki_docs
xcopy /E /I /Y _oiwiki_tmp\docs data\oi_wiki_docs    # Windows
# cp -r _oiwiki_tmp/docs/. data/oi_wiki_docs/       # Linux/macOS
rmdir /S /Q _oiwiki_tmp

# ② 清洗语料（剔除非知识点）
python clean_corpus.py

# ③ 生成语料清单（可校验）
python build_manifest.py

# ④ 解析学习路线
python parse_roadmap.py      # → data/curriculum.json
python parse_deps.py         # → data/dep_graph.json
python build_curriculum.py   # → data/curriculum_extended.json

# ⑤ 建索引（题解库 + 知识库，较慢，需要下载嵌入模型）
python rag_load.py data/solutions data/index
python rag_load.py data/oi_wiki_clean data/wiki_index
```

**验证**：`python build_manifest.py --verify` 应输出「语料与清单一致」。

### 4. 运行

```bash
# 命令行对话
python my_agent.py

# 网页版（含语音）
streamlit run app.py

# HTTP 接口
uvicorn api:app --reload
```

---

## 数据流水线

```
OI Wiki 仓库
    ↓ git clone
data/oi_wiki_docs/          原始语料（2930 个文件，53 MB，不入库）
    ↓ python clean_corpus.py
data/oi_wiki_clean/         清洗后（418 个 .md，5.3 MB，不入库）
    ↓ python build_manifest.py
data/corpus_manifest.json   语料清单（校验和 + 来源许可，入库）

data/oi_wiki_clean/contest/roadmap.md     ← OI Wiki 官方学习路线
    ↓ python parse_roadmap.py
data/curriculum.json        入门层：55 个知识点，有学习顺序
data/curriculum_report.md   解析报告

data/oi_wiki_clean/（全部）
    ↓ python parse_deps.py
data/dep_graph.json         引用关系图（956 条边）
data/dep_report.md          覆盖率报告

data/curriculum.json + 目录结构
    ↓ python build_curriculum.py
data/curriculum_extended.json  完整分层路线
data/coverage_report.md        覆盖率报告
```

**重建顺序不能反**——语料没洗干净，解析出的路线会掺进站点资源这类非知识点。

---

## 项目结构

| 文件 | 职责 |
|---|---|
| `my_agent.py` | Agent 主循环 + 14 个工具的注册与派发 |
| `personality.py` | 人格设定 + 工具调用流程约束 |
| `client.py` | 大模型调用（重试、异常分层、成本计算） |
| `curriculum.py` | 学习路线查询层（找下一课、检查前置） |
| `rag_load.py` / `rag_search.py` | 检索（向量粗筛 + 重排精排） |
| `asr.py` / `tts.py` | 语音识别与合成 |
| `app.py` | Streamlit 网页界面 |
| `api.py` | FastAPI 接口（对话 + 同步） |
| `cf_watcher.py` | 比赛提交监听，自动整理题解 |
| `clean_corpus.py` | 语料清洗 |
| `build_manifest.py` | 语料清单生成与校验 |
| `parse_roadmap.py` | 解析学习路线 |
| `parse_deps.py` | 解析知识点引用关系 |
| `build_curriculum.py` | 组装完整分层路线 |

---

## Agent 工具一览（14 个）

**题解相关**
- `search_solutions` — 检索个人题解库
- `find_code` — 按题号查找本地代码文件
- `add_record` / `get_records` — 刷题记录（长期记忆）

**知识相关**
- `search_wiki` — 检索 OI Wiki 知识库

**学习路线相关**
- `get_next_topic` — 下一个该学的知识点
- `check_prerequisites` — 检查某知识点的前置
- `get_topic_info` — 知识点详情
- `list_curriculum` — 路线概览

**文件与维护**
- `read_file` / `write_file` / `list_files`
- `rebuild_index` — 整理题解后重建索引
- `get_date`

---

## 数据来源与许可

| 来源 | 用途 | 许可 | 使用方式 |
|---|---|---|---|
| **OI Wiki** | 理论讲解 + 学习路线 | **CC BY-SA 4.0** | 引用内容，需署名 + 相同方式共享 |
| **Codeforces API** | 提交记录、题库、能力诊断 | 公开 API | 匿名访问，遵守每 2 秒 1 次的限流 |
| **个人题解与代码** | 实操范例 | 本人所有 | — |

**OI Wiki 许可要求**：

- 必须**署名**
- 演绎作品必须以**相同方式共享**（CC BY-SA 4.0）发布
- 建议给上游仓库点 Star

**本项目引用了 OI Wiki 内容，因此同样以 CC BY-SA 4.0 发布。**

> 说明：本产品的学习路径参考公开的算法课程体系组织，未使用任何受限的课件或配套代码。

---

## 当前进度

| 阶段 | 状态 |
|---|---|
| P0 健壮性修复（5 项） | ✅ 完成 |
| 语料清洗与清单 | ✅ 完成 |
| 学习路线解析（入门层 55 个知识点） | ✅ 完成 |
| 引用关系解析（覆盖率 63.4%） | ✅ 完成 |
| 进阶层归类（364 个知识点，12 个主题） | ✅ 完成 |
| 接入 Agent（4 个路线工具） | ✅ 完成 |
| 知识层评测 | ⬜ 待做 |
| 跨端迁移（鸿蒙 ArkUI-X） | ⬜ 待做 |

---

## 已知限制

- **进阶层顺序未定**：364 个知识点只做了主题归类，`verified=false`。学习顺序需要人工确认。
- **「已学」判断是粗匹配**：基于题解标签与知识点名的字符串包含关系，可能漏判。
- **引用关系 ≠ 强制前置**：`references` 是正文链接，不等于「必须先学」。前置检查只做提示，不做拦截。
- **覆盖率 12.9%**：入门路线只覆盖 418 个知识点中的 54 个——这是 `roadmap.md` 的设计范围（CSP-J 入门级），不是解析缺陷。
- **嵌入模型首次运行需下载**：约 100 MB。
