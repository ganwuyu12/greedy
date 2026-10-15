import json
from pathlib import Path
import numpy as np
from sentence_transformers import SentenceTransformer

DATA_DIR = Path("data/solutions")


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
    # 只索引“核心目录”
    core_dirs = ["basic", "dp", "ds", "graph", "math", "string", "search", "geometry", "misc", "topic"]

    for f in data_dir.rglob("*.md"):
        if not f.is_file():
            continue
        # 检查“路径里有没有核心目录”
        if data_dir.name == "oi_wiki_docs":   # 只有 OI Wiki 才过滤
            if not any(d in f.parts for d in core_dirs):
                continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for part in split_fn(text):
            if len(part) < 20:
                continue
            chunks.append({"text": part, "source": f.name})
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