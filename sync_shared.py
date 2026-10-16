#!/usr/bin/env python3
"""
同步共享业务代码到两个工程

方案 C 的配套工具：跨端工程与鸿蒙单端工程共用大部分业务代码，
但必须保证「共享部分两边完全一致」——靠手工复制迟早会不一致。

用法：
    python sync_shared.py             # 检查两边是否一致
    python sync_shared.py --apply     # 从跨端工程同步到鸿蒙工程
    python sync_shared.py --diff      # 显示差异

共享清单怎么定的：
    **只有不含平台特有 API 的文件才能共享。**
    逐个查过 import：
      - @kit.NetworkKit / @kit.ArkData / @kit.ArkTS 等 → 跨平台兼容，可共享
      - @kit.CoreSpeechKit / @hms.* → 平台特有，**不可共享**
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

# 两个工程的位置
CROSS = Path("E:/projects/greedy-app")        # ArkUI-X 跨端（鸿蒙 + Android）
HARMONY = Path("E:/projects/greedy-harmony")  # 鸿蒙单端（带语音）

ETS = "entry/src/main/ets"

# ---------------------------------------------------------------- 共享清单

# 完全共享：两边内容必须一致
SHARED: list[str] = [
    f"{ETS}/core/Agent.ets",
    f"{ETS}/core/CFClient.ets",
    f"{ETS}/core/Config.ets",
    f"{ETS}/core/Persona.ets",
    f"{ETS}/core/SessionStore.ets",
    f"{ETS}/core/Tools.ets",
    f"{ETS}/core/WikiIndex.ets",
    f"{ETS}/core/Voice.ets",          # 接口层（不含平台 API）
    f"{ETS}/pages/Index.ets",
    "entry/src/main/resources/rawfile/kb_index.json",
    "entry/src/main/resources/base/element/string.json",
    "entry/src/main/module.json5",
]

# 平台特有：**不共享**，各工程自己维护
PLATFORM_SPECIFIC: dict[str, str] = {
    f"{ETS}/core/VoiceHarmony.ets":
        "跨端版是占位实现（语音 API 不支持 ArkUI-X）；"
        "鸿蒙单端版是真实实现（静态 import @kit.CoreSpeechKit）",
}


def digest(p: Path) -> str:
    if not p.exists():
        return "(缺失)"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def check() -> int:
    print("=" * 66)
    print("共享代码一致性检查")
    print("=" * 66)

    same = 0
    diff: list[str] = []
    missing: list[str] = []

    for rel in SHARED:
        a = CROSS / rel
        b = HARMONY / rel
        da, db = digest(a), digest(b)
        if da == "(缺失)" or db == "(缺失)":
            missing.append(f"{rel}  (跨端:{da} 鸿蒙:{db})")
        elif da == db:
            same += 1
            print(f"  ✓ {rel}")
        else:
            diff.append(f"{rel}  ({da} ≠ {db})")
            print(f"  ✗ {rel}    {da} ≠ {db}")

    print()
    print(f"一致 {same} / 不一致 {len(diff)} / 缺失 {len(missing)}")

    if PLATFORM_SPECIFIC:
        print()
        print("平台特有文件（本就不该相同）：")
        for rel, why in PLATFORM_SPECIFIC.items():
            print(f"  · {rel}")
            print(f"      {why}")

    return 0 if not diff and not missing else 1


def show_diff() -> None:
    for rel in SHARED:
        a = CROSS / rel
        b = HARMONY / rel
        if digest(a) == digest(b):
            continue
        print("=" * 66)
        print(f"{rel}")
        print("=" * 66)
        if not a.exists() or not b.exists():
            print("  一方缺失，无法比对")
            continue
        la = a.read_text(encoding="utf-8", errors="ignore").split("\n")
        lb = b.read_text(encoding="utf-8", errors="ignore").split("\n")
        print(f"  行数：跨端 {len(la)} / 鸿蒙 {len(lb)}")
        import difflib
        d = difflib.unified_diff(la, lb, "crossplatform", "harmony", lineterm="", n=1)
        shown = 0
        for line in d:
            if shown > 40:
                print("  …（省略）")
                break
            print(f"  {line}")
            shown += 1


def apply_sync() -> int:
    print("=" * 66)
    print("从跨端工程同步到鸿蒙单端工程")
    print("=" * 66)
    n = 0
    for rel in SHARED:
        a = CROSS / rel
        b = HARMONY / rel
        if not a.exists():
            print(f"  ⚠️ 源文件不存在，跳过：{rel}")
            continue
        if digest(a) == digest(b):
            continue
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a, b)
        print(f"  → {rel}")
        n += 1
    print()
    print(f"同步了 {n} 个文件")
    print()
    print("⚠️ 注意：VoiceHarmony.ets 不在同步清单里。")
    print("   鸿蒙单端版的语音实现是**真实现**，不能被跨端版覆盖。")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="同步共享业务代码")
    ap.add_argument("--apply", action="store_true", help="执行同步（跨端 → 鸿蒙）")
    ap.add_argument("--diff", action="store_true", help="显示具体差异")
    args = ap.parse_args()

    if not CROSS.exists():
        raise SystemExit(f"找不到跨端工程：{CROSS}")
    if not HARMONY.exists():
        raise SystemExit(f"找不到鸿蒙工程：{HARMONY}")

    if args.apply:
        sys.exit(apply_sync())
    if args.diff:
        show_diff()
        sys.exit(0)
    sys.exit(check())


if __name__ == "__main__":
    main()
