#!/usr/bin/env python3
"""
贪心 · 陪伴与成长记录

设计原则（重要，决定了这个模块和「诊断工具」的区别）：

  1. **只说事实，不给评判**
     「你今天解了 3 道题」 ✅
     「你的难度偏低，该练更难的」 ❌
     后者是教练口吻，不是朋友口吻。判断留给使用者自己。

  2. **不需要额外操作**
     从已有数据自动生成，不让使用者为了「被记录」而多做事。
     记录本身就是负担的话，没人会记。

  3. **尊重真实作息**
     比赛常在深夜开始、跨零点结束。
     所以按**比赛日**归档，而不是按提交时间戳——
     否则一场比赛会被劈成两天，连续天数也会断。

产出：
  data/practice_log.json  长期的练习记录（按题目去重，保留首次解出日期）

用法：
    python companion.py                # 生成/更新记录，并打印今日小结
    python companion.py --sync         # 从 CF 拉最新数据后重建
    python companion.py --stats        # 只看累计与里程碑
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

RAW_SUBS = BASE / "data" / "cf_raw" / "submissions.json"
LOG = BASE / "data" / "practice_log.json"

TZ = timezone(timedelta(hours=8))       # 本地时区（东八区）

# 比赛通常在深夜，跨零点结束。
# 若提交时间早于这个钟点，算作「前一天那场比赛」的一部分。
# 例如凌晨 0:40 交的题，归属到前一天。
NIGHT_CUTOFF_HOUR = 5


def problem_key(s: dict) -> str:
    p = s.get("problem", {})
    cid, idx = p.get("contestId"), p.get("index")
    if cid is None:
        return f"{p.get('name', '?')}"
    return f"{cid}{idx}"


def practice_date(ts: int) -> str:
    """把一个提交时间戳归到「练习日」

    深夜（0:00–5:00）的提交算前一天，避免一场跨零点的比赛被劈成两天。
    """
    dt = datetime.fromtimestamp(ts, TZ)
    if dt.hour < NIGHT_CUTOFF_HOUR:
        dt = dt - timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def build_log(subs: list[dict]) -> dict:
    """从提交记录构建练习日志

    以「题目」为单位（而不是提交），记录每道题**首次通过**的信息。
    未通过的题也保留，因为「卡住过」也是成长的一部分。
    """
    problems: dict[str, dict] = {}

    for s in sorted(subs, key=lambda x: x.get("creationTimeSeconds", 0)):
        ts = s.get("creationTimeSeconds", 0)
        if not ts:
            continue
        key = problem_key(s)
        date = practice_date(ts)
        p = s.get("problem", {})

        e = problems.setdefault(key, {
            "key": key,
            "name": s.get("problem_name") or p.get("name", ""),
            "rating": s.get("problem_rating") or p.get("rating"),
            "tags": list(s.get("problem_tags") or p.get("tags") or []),
            "contestId": p.get("contestId"),
            "index": p.get("index"),
            "attempts": 0,
            "solved": False,
            "first_try_date": date,       # 第一次见到它的日子
            "solved_date": None,          # 首次通过的日子
        })
        e["attempts"] += 1
        if s.get("verdict") == "OK" and not e["solved"]:
            e["solved"] = True
            e["solved_date"] = date

    # ---- 按日聚合 ----
    by_date: dict[str, dict] = {}
    for e in problems.values():
        date = e["solved_date"] or e["first_try_date"]
        d = by_date.setdefault(date, {
            "date": date,
            "solved": [],       # 当天通过的题
            "attempted": [],    # 当天碰过但没通过的题
            "contests": set(),
        })
        if e["contestId"]:
            d["contests"].add(e["contestId"])
        (d["solved"] if e["solved"] else d["attempted"]).append({
            "key": e["key"],
            "name": e["name"],
            "rating": e["rating"],
            "tags": e["tags"],
        })

    days = []
    for date in sorted(by_date):
        d = by_date[date]
        ratings = [x["rating"] for x in d["solved"] if x["rating"]]
        days.append({
            "date": date,
            "solved_count": len(d["solved"]),
            "attempted_count": len(d["attempted"]),
            "contests": sorted(d["contests"]),
            "max_rating": max(ratings) if ratings else None,
            "solved": d["solved"],
            "attempted": d["attempted"],
        })

    solved = [e for e in problems.values() if e["solved"]]
    return {
        "version": "1.0",
        "updated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "note": "按题目去重；deep-night 提交归入前一练习日",
        "problems": sorted(problems.values(), key=lambda x: x["first_try_date"]),
        "days": days,
    }


def compute_stats(log: dict) -> dict:
    """累计与里程碑——只陈述事实"""
    problems = log["problems"]
    solved = [p for p in problems if p["solved"]]
    days = log["days"]

    total_solved = len(solved)
    ratings = [p["rating"] for p in solved if p["rating"]]
    tags = Counter(t for p in solved for t in p["tags"])

    # 连续天数（有通过记录的日子）
    active = sorted({d["date"] for d in days if d["solved_count"] > 0})
    streak = 0
    if active:
        today = datetime.now(TZ).strftime("%Y-%m-%d")
        yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        # 从最近一次有记录的日子往前数
        cur = active[-1]
        if cur in (today, yesterday):
            streak = 1
            pool = set(active)
            probe = datetime.strptime(cur, "%Y-%m-%d")
            while True:
                probe -= timedelta(days=1)
                if probe.strftime("%Y-%m-%d") in pool:
                    streak += 1
                else:
                    break

    # 首次解出的难度档位（里程碑）
    tiers = [800, 1000, 1200, 1400, 1600, 1800, 2000, 2200]
    tier_first: dict[int, str] = {}
    for p in sorted(solved, key=lambda x: x["solved_date"] or ""):
        if not p["rating"]:
            continue
        for t in tiers:
            if p["rating"] >= t and t not in tier_first:
                tier_first[t] = p["solved_date"]

    return {
        "total_problems": len(problems),
        "total_solved": total_solved,
        "total_left_unsolved": len(problems) - total_solved,
        "active_days": len(active),
        "current_streak": streak,
        "first_day": active[0] if active else None,
        "last_day": active[-1] if active else None,
        "hardest_solved": max(ratings) if ratings else None,
        "median_solved": sorted(ratings)[len(ratings) // 2] if ratings else None,
        "tag_counts": dict(tags.most_common()),
        "tier_first_solved": tier_first,
    }


def today_summary(log: dict, stats: dict) -> str:
    """今日/最近一次的小结——朋友口吻"""
    days = log["days"]
    if not days:
        return "还没有记录。等你第一道题。"

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    last = days[-1]
    is_today = last["date"] == today

    lines = []
    if is_today:
        lines.append(f"今天解了 {last['solved_count']} 道")
    else:
        lines.append(f"最近一次是 {last['date']}，解了 {last['solved_count']} 道")

    if last["solved"]:
        detail = "、".join(
            f"{x['key']}" + (f"（{x['rating']}）" if x["rating"] else "")
            for x in last["solved"][:8]
        )
        lines.append(f"  {detail}")
    if last["attempted_count"]:
        lines.append(f"  还有 {last['attempted_count']} 道卡住了，回头可以看看")
    if last["max_rating"]:
        lines.append(f"  当天最难：{last['max_rating']}")

    lines.append("")
    lines.append(f"累计 {stats['total_solved']} 道，活跃 {stats['active_days']} 天"
                 + (f"，连续 {stats['current_streak']} 天" if stats["current_streak"] > 1 else ""))
    if stats["hardest_solved"]:
        lines.append(f"最高难度 {stats['hardest_solved']}")
    return "\n".join(lines)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="陪伴与成长记录")
    ap.add_argument("--sync", action="store_true", help="从 CF 拉最新数据")
    ap.add_argument("--stats", action="store_true", help="只看累计与里程碑")
    a = ap.parse_args()

    if a.sync or not RAW_SUBS.exists():
        if not RAW_SUBS.exists():
            print("本地没有提交数据，从 CF 拉取…")
        from coach import load_data
        subs, rating, starts = load_data("ganwuyu")
        # 复用 coach 的落盘
        RAW_SUBS.parent.mkdir(parents=True, exist_ok=True)
        RAW_SUBS.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        subs = json.loads(RAW_SUBS.read_text(encoding="utf-8"))
        print(f"读取本地数据：{len(subs)} 条提交")

    log = build_log(subs)
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    stats = compute_stats(log)

    print()
    print("=" * 58)
    print("贪心 · 成长记录")
    print("=" * 58)
    print(today_summary(log, stats))

    print()
    print("—— 里程碑 ——")
    for t, d in sorted(stats["tier_first_solved"].items()):
        print(f"  首次解出 {t}+ ：{d}")

    print()
    print("—— 常做的类型 ——")
    for tag, n in list(stats["tag_counts"].items())[:10]:
        print(f"  {tag:<28} {n} 道")

    print()
    print(f"已写出：{LOG}")


if __name__ == "__main__":
    main()
