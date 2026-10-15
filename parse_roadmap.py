import re
import json
from pathlib import Path

ROADMAP = Path("data/oi_wiki_clean/contest/roadmap.md")
OUTPUT = Path("data/curriculum.json")


def parse_roadmap(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    stages = []
    current_stage = None
    current_section = None
    current_note_lines = []

    stage_pattern = re.compile(r"^## (\d+)\s+(.+)$")
    section_pattern = re.compile(r"^### (\d+\.\d+)\s+(.+)$")
    subsection_pattern = re.compile(r"^#### (\d+\.\d+\.\d+)\s+(.+)$")

    def flush_note():
        nonlocal current_note_lines
        if current_section and current_note_lines:
            note = " ".join(l.strip() for l in current_note_lines if l.strip())
            if note:
                current_section["note"] = note
        current_note_lines = []

    for line in lines:
        # 阶段
        m = stage_pattern.match(line)
        if m:
            flush_note()
            current_stage = {
                "order": int(m.group(1)),
                "title": m.group(2),
                "level": "入门",
                "source": "oi_wiki_roadmap",
                "sections": [],
            }
            stages.append(current_stage)
            current_section = None
            continue

        # 小节
        m = section_pattern.match(line)
        if m:
            flush_note()
            current_section = {
                "order": m.group(1),
                "title": m.group(2),
                "note": "",
                "concepts": [],
            }
            if current_stage:
                current_stage["sections"].append(current_section)
            continue

        # 子小节（先当“小节”处理，简单点）
        m = subsection_pattern.match(line)
        if m:
            flush_note()
            current_section = {
                "order": m.group(1),
                "title": m.group(2),
                "note": "",
                "concepts": [],
            }
            if current_stage:
                current_stage["sections"].append(current_section)
            continue

        # 段落（作为 note）
        if line.strip() and not line.startswith("#") and not line.startswith("-") and not line.startswith("*"):
            current_note_lines.append(line)

    flush_note()

    return {
        "version": "0.1",
        "source": "oi_wiki_roadmap",
        "stages": stages,
    }


if __name__ == "__main__":
    result = parse_roadmap(ROADMAP)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"解析出 {len(result['stages'])} 个阶段")
    for s in result["stages"]:
        print(f"  {s['order']}. {s['title']}（{len(s['sections'])} 节）")