import json
import re
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

DATA_DIR = Path("data/solutions")

# 只索引这些目录（OI Wiki 清洗后保留的主题目录）
CORE_DIRS = ["basic", "dp", "ds", "graph", "math", "string",
             "search", "geometry", "misc", "topic", "lang", "contest"]

# 不索引的文件：这些是「元信息」而非知识点
#   roadmap.md 是学习路线本身，它列出了所有知识点名字，
#   会以「关键词碎片」的形式抢走所有「X 是什么」的查询。
#   它的结构已由 parse_roadmap.py 单独解析。
EXCLUDE_FILES = {"roadmap.md"}

# 纯标题块：整块只有 Markdown 标题或极短文字，没有正文
# 这类块没有讲解价值，但会因精确命中关键词而排在真词条前面
RE_HEADING_ONLY = re.compile(r"^\s*#{1,6}\s+")


def is_content_chunk(text: str, min_len: int = 40) -> bool:
    """判断一个块是否值得进索引

    过滤掉：
      - 太短的块（< min_len 字符）
      - 纯标题块（去掉标题行后没剩什么）
    """
    t = text.strip()
    if len(t) < min_len:
        return False
    # 去掉所有标题行后，看还剩多少正文
    body = "\n".join(
        ln for ln in t.split("\n")
        if ln.strip() and not RE_HEADING_ONLY.match(ln)
    )
    if len(body) < 20:
        return False
    return True


def split_fixed(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """固定长度切分，带重叠"""
    step = size - overlap
    parts = []
    for i in range(0, len(text), step):
        chunk = text[i:i + size]
        if chunk.strip():
            parts.append(chunk)
    return parts


def split_by_blank_line(text: str) -> list[str]:
    """按空行切分"""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def split_mixed(text: str, max_size: int = 800) -> list[str]:
    """先按空行切，超长的再按固定长度二次切分"""
    parts = []
    for part in split_by_blank_line(text):
        if len(part) <= max_size:
            parts.append(part)
        else:
            parts.extend(split_fixed(part, size=max_size, overlap=50))
    return parts


def load_and_split(split_fn, data_dir: Path) -> list[dict]:
    chunks = []
    skipped_file = 0
    skipped_chunk = 0

    for f in data_dir.rglob("*.md"):
        if not f.is_file():
            continue
        # 排除元信息文件
        if f.name in EXCLUDE_FILES:
            skipped_file += 1
            continue
        # 只保留主题目录下的内容（避免简介、工具配置这类非知识点）
        if not any(d in f.parts for d in CORE_DIRS):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        # 记录相对路径：多个目录下都有 basic.md、index.md 这类同名文件，
        # 只存文件名会导致检索结果无法区分来源，既影响评测也影响用户体验
        try:
            rel = str(f.relative_to(data_dir)).replace("\\", "/")
        except ValueError:
            rel = f.name
        for part in split_fn(text):
            if not is_content_chunk(part):
                skipped_chunk += 1
                continue
            chunks.append({"text": part, "source": f.name, "path": rel})
    print(f"  跳过文件 {skipped_file} 个（元信息）")
    print(f"  跳过碎片 {skipped_chunk} 个（纯标题/过短）")
    return chunks


def build_index(split_fn, data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(exist_ok=True)
    chunks = load_and_split(split_fn, data_dir)
    print(f"切出 {len(chunks)} 块")

    model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
    texts = [c["text"] for c in chunks]
    print("开始向量化...")
    vectors = model.encode(texts, show_progress_bar=True)
    print(f"向量化完成，形状: {vectors.shape}")

    np.save(output_dir / "embeddings.npy", vectors)
    with open(output_dir / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False)
    print(f"已保存到 {output_dir}")

if __name__ == '__main__':
    import sys
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/solutions")
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/index")
    build_index(split_by_blank_line, data_dir, output_dir)