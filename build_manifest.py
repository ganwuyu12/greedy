#!/usr/bin/env python3
"""
生成语料清单（manifest）——第 1 步「语料清洗」的留痕

为什么需要它：
  data/oi_wiki_docs/ 和 data/oi_wiki_clean/ 都不入 git（体积大 + 版权），
  但如果只留一个清洗脚本，别人（包括三个月后的你）无法确认：
    - 清洗时用的是哪一版语料
    - 清洗后应该有多少个文件
    - 数据有没有被动过

  所以用一份清单记录「数量 + 校验和 + 来源」，
  既轻量（几十 KB），又能验证重建结果是否一致。

用法：
    python build_manifest.py            # 生成 data/corpus_manifest.json
    python build_manifest.py --verify   # 校验当前语料是否与清单一致
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
RAW_DIR = BASE / "data" / "oi_wiki_docs"
CLEAN_DIR = BASE / "data" / "oi_wiki_clean"
MANIFEST = BASE / "data" / "corpus_manifest.json"

# 清洗时保留的主题目录（与 clean_corpus.py 保持一致）
KEEP_DIRS = [
    "basic", "dp", "ds", "graph", "math", "string",
    "search", "geometry", "misc", "topic", "contest", "lang",
]

SOURCE = {
    "name": "OI Wiki",
    "repo": "https://github.com/OI-wiki/OI-wiki",
    "url": "https://oi-wiki.org/",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "note": "知识内容采用 CC BY-SA 4.0，转载与演绎需署名并以相同方式共享",
}


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def digest_tree(root: Path, only_md: bool = True) -> tuple[str, list[dict]]:
    """对整个目录算一个聚合摘要，并返回逐文件信息

    聚合摘要 = 所有文件「相对路径 + 内容哈希」按序拼接后再哈希
    这样任何文件的增删改都会体现出来。
    """
    files = sorted(
        (p for p in root.rglob("*") if p.is_file() and (not only_md or p.suffix == ".md")),
        key=lambda p: str(p.relative_to(root)).replace("\\", "/"),
    )
    entries = []
    joined = hashlib.sha256()
    for p in files:
        rel = str(p.relative_to(root)).replace("\\", "/")
        h = sha256_of(p)
        entries.append({"path": rel, "size": p.stat().st_size, "sha256": h})
        joined.update(f"{rel}:{h}\n".encode("utf-8"))
    return joined.hexdigest(), entries


def count_by_dir(root: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in KEEP_DIRS:
        sub = root / d
        if sub.exists():
            out[d] = sum(1 for _ in sub.rglob("*.md"))
    return out


def build() -> dict:
    if not CLEAN_DIR.exists():
        raise SystemExit(
            f"找不到清洗后的语料：{CLEAN_DIR}\n"
            f"请先运行：python clean_corpus.py"
        )

    clean_digest, clean_files = digest_tree(CLEAN_DIR)
    result = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": SOURCE,
        "pipeline": {
            "raw_dir": "data/oi_wiki_docs",
            "clean_dir": "data/oi_wiki_clean",
            "clean_script": "clean_corpus.py",
            "keep_dirs": KEEP_DIRS,
            "rule": "只保留主题目录下的 .md，剔除站点资源、测试数据、图片等",
        },
        "clean": {
            "file_count": len(clean_files),
            "total_bytes": sum(f["size"] for f in clean_files),
            "digest": clean_digest,
            "by_dir": count_by_dir(CLEAN_DIR),
        },
    }

    # 原始语料如果还在，也记一份（用于确认清洗前后的一致性）
    if RAW_DIR.exists():
        raw_total = sum(1 for _ in RAW_DIR.rglob("*") if _.is_file())
        raw_md = sum(1 for _ in RAW_DIR.rglob("*.md"))
        result["raw"] = {
            "file_count": raw_total,
            "md_count": raw_md,
            "md_bytes": sum(p.stat().st_size for p in RAW_DIR.rglob("*.md")),
        }

    result["clean"]["files"] = clean_files
    return result


def verify() -> int:
    if not MANIFEST.exists():
        print(f"找不到清单：{MANIFEST}")
        return 1
    saved = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not CLEAN_DIR.exists():
        print(f"找不到语料目录：{CLEAN_DIR}")
        return 1

    digest, files = digest_tree(CLEAN_DIR)
    exp_count = saved["clean"]["file_count"]
    exp_digest = saved["clean"]["digest"]

    ok = True
    print(f"清单记录：{exp_count} 个文件，摘要 {exp_digest[:16]}…")
    print(f"当前实际：{len(files)} 个文件，摘要 {digest[:16]}…")

    if len(files) != exp_count:
        print(f"✗ 文件数不一致（差 {len(files) - exp_count}）")
        ok = False
    if digest != exp_digest:
        print("✗ 内容摘要不一致（语料被改动过）")
        # 找出具体哪些文件不同
        exp_map = {f["path"]: f["sha256"] for f in saved["clean"]["files"]}
        cur_map = {f["path"]: f["sha256"] for f in files}
        added = sorted(set(cur_map) - set(exp_map))
        removed = sorted(set(exp_map) - set(cur_map))
        changed = sorted(p for p in set(exp_map) & set(cur_map) if exp_map[p] != cur_map[p])
        for label, items in (("新增", added), ("缺失", removed), ("改动", changed)):
            if items:
                print(f"  {label} {len(items)} 个：{items[:5]}")
        ok = False

    print("✓ 语料与清单一致" if ok else "✗ 校验未通过")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="语料清单：生成 / 校验")
    ap.add_argument("--verify", action="store_true", help="校验当前语料是否与清单一致")
    args = ap.parse_args()

    if args.verify:
        raise SystemExit(verify())

    data = build()
    MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    c = data["clean"]
    print(f"已生成清单：{MANIFEST}")
    print(f"  清洗后：{c['file_count']} 个 .md，{c['total_bytes'] / 1024 / 1024:.1f} MB")
    print(f"  摘要：{c['digest'][:16]}…")
    print("  目录分布：")
    for k, v in sorted(c["by_dir"].items(), key=lambda x: -x[1]):
        print(f"    {k:<12} {v}")
    if "raw" in data:
        print(f"  原始语料：{data['raw']['file_count']} 个文件"
              f"（其中 .md {data['raw']['md_count']} 个）")


if __name__ == "__main__":
    main()
