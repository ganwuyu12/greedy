import shutil
from pathlib import Path

SRC = Path("data/oi_wiki_docs")
DST = Path("data/oi_wiki_clean")

KEEP_DIRS = [
    "basic", "dp", "ds", "graph", "math", "string",
    "search", "geometry", "misc", "topic", "contest",
]


def clean():
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    count = 0
    for d in KEEP_DIRS:
        src_dir = SRC / d
        if not src_dir.exists():
            continue
        dst_dir = DST / d
        dst_dir.mkdir(parents=True, exist_ok=True)

        for f in src_dir.rglob("*.md"):
            if not f.is_file():
                continue
            rel = f.relative_to(src_dir)
            target = dst_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            count += 1

    print(f"清洗完成：{count} 个 .md")


if __name__ == "__main__":
    clean()