#!/usr/bin/env python3
"""
教练：能力诊断

面向的使用者：**已经把 CF 当主战场的算法爱好者**（不是新手）。

回答三个问题：
  1. 我的实力画像是什么（rating / 解题分布 / 天花板在哪）
  2. 我的真实短板是什么（按官方标签统计通过率，找「做得多但不通过」的）
  3. 我为什么卡住了（对比不同时期的行为变化）

关键设计：诊断的是「行为」，不只是「结果」
  rating 掉分只是结果。要看的是：
    - 最近还在做多难的题？（天花板有没有下移）
    - 每场比赛做到第几题？（是 A/B 止步还是能摸到 C/D）
    - 哪个标签在持续失分？

产出：
  data/cf_raw/submissions.json     原始提交（带题目名与标签）
  data/coach_profile.json          能力画像
  data/coach_report.md             诊断报告

用法：
    python coach.py                    # 用默认 handle
    python coach.py <handle>           # 指定 handle
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))

RAW = BASE / "data" / "cf_raw"
OUT_PROFILE = BASE / "data" / "coach_profile.json"
OUT_REPORT = BASE / "data" / "coach_report.md"

DEFAULT_HANDLE = "ganwuyu"

# 最近多少场算「近期」（用于对比行为变化）
RECENT_CONTESTS = 8


def load_data(handle: str, max_pages: int = 5) -> tuple[list[dict], list[dict], dict]:
    from cf_client import CFClient
    cf = CFClient(verbose=True)
    print("拉取提交记录…")
    subs = cf.submissions_with_problem(handle, max_pages=max_pages)
    print(f"  {len(subs)} 条")
    print("拉取参赛记录…")
    rating = cf.user_rating(handle)
    print(f"  {len(rating)} 场")
    print("拉取比赛时间表…")
    try:
        starts = {c["id"]: c.get("startTimeSeconds", 0) for c in cf.contest_list()}
        print(f"  {len(starts)} 场比赛")
    except Exception as e:  # noqa: BLE001
        print(f"  失败（速度分析会降级）：{e}")
        starts = {}
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / "submissions.json").write_text(
        json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")
    (RAW / "user_rating.json").write_text(
        json.dumps(rating, ensure_ascii=False, indent=2), encoding="utf-8")
    return subs, rating, starts


def analyze(subs: list[dict], rating: list[dict], starts: dict[int, int]) -> dict:
    # ---- 1. 整体 ----
    total = len(subs)
    ac = [s for s in subs if s.get("verdict") == "OK"]
    tried_keys = {(s["problem"].get("contestId"), s["problem"].get("index")) for s in subs}
    solved_keys = {(s["problem"].get("contestId"), s["problem"].get("index")) for s in ac}

    # ---- 2. 按题目难度分布 ----
    def bucket(rs: list[int | None]) -> dict[str, int]:
        out: Counter = Counter()
        for r in rs:
            if r is None:
                out["未定级"] += 1
            else:
                lo = (r // 100) * 100
                out[f"{lo}-{lo + 99}"] += 1
        return dict(sorted(out.items()))

    solved_ratings = [s.get("problem_rating") for s in ac]
    tried_ratings = [s.get("problem_rating") for s in subs]

    # ---- 3. 按标签统计通过率（薄弱点诊断的核心）----
    #     以「题目」为单位，而不是「提交」——否则反复提交同一题会扭曲统计
    tag_tried: dict[str, set] = defaultdict(set)
    tag_solved: dict[str, set] = defaultdict(set)
    for s in subs:
        p = s["problem"]
        key = (p.get("contestId"), p.get("index"))
        for t in (s.get("problem_tags") or []):
            tag_tried[t].add(key)
            if s.get("verdict") == "OK":
                tag_solved[t].add(key)

    tag_stats = []
    for t, tried in tag_tried.items():
        done = len(tag_solved.get(t, set()))
        n = len(tried)
        tag_stats.append({
            "tag": t,
            "tried": n,
            "solved": done,
            "rate": round(done / n, 3) if n else 0,
        })
    tag_stats.sort(key=lambda x: (-x["tried"], x["rate"]))

    # 薄弱点：做得多（>=5）但通过率低
    weak = [t for t in tag_stats if t["tried"] >= 5 and t["rate"] < 0.6]
    weak.sort(key=lambda x: x["rate"])
    # 强项：做得多且通过率高
    strong = [t for t in tag_stats if t["tried"] >= 5 and t["rate"] >= 0.8]
    strong.sort(key=lambda x: -x["rate"])

    # ---- 4. 未通过的题都集中在哪 ----
    #     注意：必须排除已 AC 的题——同一道题先 WA 后 AC 是正常的调试过程
    failed = [s for s in subs
              if s.get("verdict") != "OK"
              and (s["problem"].get("contestId"), s["problem"].get("index")) not in solved_keys]
    failed_tags: Counter = Counter()
    for s in failed:
        for t in (s.get("problem_tags") or []):
            failed_tags[t] += 1

    # 试过但没做出来的题（按难度）——按题目去重，记录尝试次数
    unsolved_map: dict[tuple, dict] = {}
    for s in subs:
        key = (s["problem"].get("contestId"), s["problem"].get("index"))
        if key in solved_keys:
            continue
        e = unsolved_map.setdefault(key, {
            "name": s.get("problem_name") or "",
            "rating": s.get("problem_rating"),
            "tags": (s.get("problem_tags") or [])[:3],
            "attempts": 0,
            "contestId": s["problem"].get("contestId"),
        })
        e["attempts"] += 1
    unsolved = sorted(unsolved_map.values(),
                      key=lambda x: (-(x["rating"] or 0), -x["attempts"]))

    # ---- 4b. 解题速度（关键指标）----
    #     rating 掉分往往不是「不会做」，而是「做得太慢，没时间做难题」。
    #
    #     耗时 = 首次 AC 时间 − 比赛真实开始时间
    #     开始时间取自 contest.list 的 startTimeSeconds（可靠）；
    #     拿不到该场比赛时就跳过，不硬猜。
    speed_by_contest = []
    skipped_no_start = 0
    for r in rating:
        cid = r["contestId"]
        t0 = starts.get(cid, 0)
        if not t0:
            skipped_no_start += 1
            continue
        c_subs = [s for s in subs if s["problem"].get("contestId") == cid]
        if not c_subs:
            continue
        ac_first: dict[str, int] = {}
        for s in sorted(c_subs, key=lambda x: x.get("creationTimeSeconds", 0)):
            if s.get("verdict") != "OK":
                continue
            idx = s["problem"].get("index", "?")
            if idx not in ac_first:
                delta = s.get("creationTimeSeconds", 0) - t0
                # 只保留 0 ~ 5 小时内的，排除赛后补题
                if 0 <= delta <= 5 * 3600:
                    ac_first[idx] = delta
        speed_by_contest.append({
            "contestId": cid,
            "name": r["contestName"],
            "solved": sorted(ac_first),
            "minutes": {k: round(v / 60) for k, v in sorted(ac_first.items())},
        })

    def median_minutes(rows: list[dict], letter: str) -> int | None:
        vals = [r["minutes"][letter] for r in rows if letter in r["minutes"]]
        if not vals:
            return None
        vals.sort()
        return vals[len(vals) // 2]

    # ---- 5. 参赛行为：每场做到第几题 ----
    contest_behavior = []
    for r in rating:
        cid = r["contestId"]
        c_subs = [s for s in subs if s["problem"].get("contestId") == cid]
        attempted = sorted({s["problem"].get("index", "?") for s in c_subs})
        done = sorted({s["problem"].get("index", "?") for s in c_subs
                       if s.get("verdict") == "OK"})
        contest_behavior.append({
            "contestId": cid,
            "name": r["contestName"],
            "rank": r["rank"],
            "old": r["oldRating"],
            "new": r["newRating"],
            "delta": r["newRating"] - r["oldRating"],
            "attempted": attempted,
            "solved": done,
            "max_solved": done[-1] if done else "-",
        })

    # ---- 6. 前后期行为对比 ----
    n = len(contest_behavior)
    recent = contest_behavior[-RECENT_CONTESTS:] if n > RECENT_CONTESTS else contest_behavior
    earlier = contest_behavior[:n - RECENT_CONTESTS] if n > RECENT_CONTESTS else []

    def avg_delta(rows: list[dict]) -> float:
        return round(sum(r["delta"] for r in rows) / len(rows), 1) if rows else 0

    def avg_rank(rows: list[dict]) -> int:
        return round(sum(r["rank"] for r in rows) / len(rows)) if rows else 0

    # 每场最高做到第几题的平均（做题天花板）
    def avg_level(rows: list[dict]) -> float:
        lv = [len(r["solved"]) for r in rows if r["solved"]]
        return round(sum(lv) / len(lv), 1) if lv else 0

    comparison = {
        "recent_contests": len(recent),
        "earlier_contests": len(earlier),
        "recent_avg_delta": avg_delta(recent),
        "earlier_avg_delta": avg_delta(earlier),
        "recent_avg_rank": avg_rank(recent),
        "earlier_avg_rank": avg_rank(earlier),
        "recent_avg_solved": avg_level(recent),
        "earlier_avg_solved": avg_level(earlier),
    }

    # ---- 7. 近期解题难度趋势（看天花板有没有下移）----
    def median_rating(items: list[int]) -> int:
        if not items:
            return 0
        items = sorted(items)
        return items[len(items) // 2]

    recent_cids = {r["contestId"] for r in recent}
    earlier_cids = {r["contestId"] for r in earlier}
    recent_solved_r = [s["problem_rating"] for s in ac
                       if s["problem"].get("contestId") in recent_cids
                       and s.get("problem_rating")]
    earlier_solved_r = [s["problem_rating"] for s in ac
                        if s["problem"].get("contestId") in earlier_cids
                        and s.get("problem_rating")]

    return {
        "handle": None,       # 由 main 填
        "current_rating": rating[-1]["newRating"] if rating else None,
        "max_rating": max((r["newRating"] for r in rating), default=None),
        "overall": {
            "submissions": total,
            "accepted_submissions": len(ac),
            "ac_rate_submission": round(len(ac) / total, 3) if total else 0,
            "problems_tried": len(tried_keys),
            "problems_solved": len(solved_keys),
            "solve_rate_problem": round(len(solved_keys) / len(tried_keys), 3) if tried_keys else 0,
        },
        "difficulty": {
            "solved_by_rating": bucket(solved_ratings),
            "tried_by_rating": bucket(tried_ratings),
            "max_solved_rating": max((r for r in solved_ratings if r), default=None),
            "median_solved_rating": median_rating([r for r in solved_ratings if r]),
        },
        "tags": tag_stats,
        "weak_tags": weak,
        "strong_tags": strong,
        "failed_tag_ranking": failed_tags.most_common(12),
        "unsolved_problem_count": len(unsolved),
        "unsolved_sample": unsolved[:15],
        "speed": {
            "by_contest": speed_by_contest,
            "median_minutes_overall": {
                letter: median_minutes(speed_by_contest, letter)
                for letter in ("A", "B", "C", "D", "E")
            },
            "median_minutes_recent": {
                letter: median_minutes(speed_by_contest[-RECENT_CONTESTS:], letter)
                for letter in ("A", "B", "C", "D", "E")
            },
            "median_minutes_earlier": {
                letter: median_minutes(speed_by_contest[:-RECENT_CONTESTS], letter)
                for letter in ("A", "B", "C", "D", "E")
            },
        },
        "contests": contest_behavior,
        "comparison": comparison,
        "trend": {
            "recent_solved_median_rating": median_rating(recent_solved_r),
            "earlier_solved_median_rating": median_rating(earlier_solved_r),
            "recent_sample": len(recent_solved_r),
            "earlier_sample": len(earlier_solved_r),
        },
    }


def write_report(p: dict) -> None:
    o, d, c, t = p["overall"], p["difficulty"], p["comparison"], p["trend"]
    lines = [
        "# 能力诊断报告",
        "",
        f"生成时间：{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
        f"选手：**{p['handle']}**",
        "",
        "## 一、总体画像",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 提交总数 | {o['submissions']} |",
        f"| 通过提交 | {o['accepted_submissions']}（{o['ac_rate_submission']:.1%}） |",
        f"| 尝试过的题目 | {o['problems_tried']} |",
        f"| 解出的题目 | {o['problems_solved']}（{o['solve_rate_problem']:.1%}） |",
        f"| 解出的最高难度 | {d['max_solved_rating'] or '—'} |",
        f"| 解出难度的中位数 | {d['median_solved_rating'] or '—'} |",
        "",
        "## 二、解题难度分布",
        "",
        "| 难度区间 | 解出 | 尝试 |",
        "|---|---|---|",
    ]
    keys = sorted(set(d["solved_by_rating"]) | set(d["tried_by_rating"]))
    for k in keys:
        lines.append(f"| {k} | {d['solved_by_rating'].get(k, 0)} | {d['tried_by_rating'].get(k, 0)} |")

    lines += [
        "",
        "## 三、薄弱点诊断",
        "",
        "判据：**尝试过 ≥5 题，但通过率 <60%** 的标签——做得多却不通过，说明是真短板。",
        "",
    ]
    if p["weak_tags"]:
        lines += ["| 标签 | 尝试 | 解出 | 通过率 |", "|---|---|---|---|"]
        for w in p["weak_tags"]:
            lines.append(f"| `{w['tag']}` | {w['tried']} | {w['solved']} | {w['rate']:.0%} |")
    else:
        lines.append("（没有满足条件的标签）")

    lines += ["", "### 强项（尝试 ≥5 题且通过率 ≥80%）", ""]
    if p["strong_tags"]:
        lines += ["| 标签 | 尝试 | 解出 | 通过率 |", "|---|---|---|---|"]
        for s in p["strong_tags"]:
            lines.append(f"| `{s['tag']}` | {s['tried']} | {s['solved']} | {s['rate']:.0%} |")
    else:
        lines.append("（暂无）")

    lines += [
        "",
        "### 未通过提交最集中的标签",
        "",
        "| 标签 | 未通过次数 |",
        "|---|---|",
    ]
    for tag, n in p["failed_tag_ranking"]:
        lines.append(f"| `{tag}` | {n} |")

    lines += [
        "",
        "## 四、参赛行为对比",
        "",
        f"| 指标 | 前 {c['earlier_contests']} 场 | 最近 {c['recent_contests']} 场 |",
        "|---|---|---|",
        f"| 平均 rating 变化 | {c['earlier_avg_delta']:+} | {c['recent_avg_delta']:+} |",
        f"| 平均排名 | {c['earlier_avg_rank']} | {c['recent_avg_rank']} |",
        f"| 平均每场解出题数 | {c['earlier_avg_solved']} | {c['recent_avg_solved']} |",
        "",
        "### 解题难度天花板的变化",
        "",
        f"- 前期解出题目的难度中位数：**{t['earlier_solved_median_rating'] or '—'}**"
        f"（样本 {t['earlier_sample']}）",
        f"- 近期解出题目的难度中位数：**{t['recent_solved_median_rating'] or '—'}**"
        f"（样本 {t['recent_sample']}）",
        "",
    ]
    if t["earlier_solved_median_rating"] and t["recent_solved_median_rating"]:
        diff = t["recent_solved_median_rating"] - t["earlier_solved_median_rating"]
        if diff < -50:
            lines.append(f"⚠️ **近期解题难度中位数下降了 {abs(diff)}**——"
                         "说明在舒适区做题，天花板在下移。这是掉分最可能的原因。")
        elif diff > 50:
            lines.append(f"✅ 近期解题难度上升了 {diff}——在向更难的方向走，"
                         "rating 的波动更可能是运气或发挥问题。")
        else:
            lines.append("解题难度基本持平——瓶颈可能不在题目难度，"
                         "而在特定类型的题（见薄弱点诊断）。")

    lines += [
        "",
        "## 五、解题速度（容易被忽略的掉分原因）",
        "",
        "rating 掉分往往不是「不会做」，而是**做得太慢，没时间做后面的题**。",
        "下表是从比赛开始到首次 AC 的中位耗时（分钟）：",
        "",
        "| 题目 | 前期中位耗时 | 近期中位耗时 | 全部 |",
        "|---|---|---|---|",
    ]
    sp = p["speed"]
    for letter in ("A", "B", "C", "D", "E"):
        early = sp["median_minutes_earlier"].get(letter)
        late = sp["median_minutes_recent"].get(letter)
        allv = sp["median_minutes_overall"].get(letter)
        f = lambda v: f"{v} 分钟" if v is not None else "—"   # noqa: E731
        lines.append(f"| {letter} | {f(early)} | {f(late)} | {f(allv)} |")

    lines += [
        "",
        "> 说明：只统计**在比赛中 AC 的题**；未 AC 的题看不到耗时。",
        "",
        "## 六、逐场记录",
        "",
        "| # | 比赛 | 排名 | 变化 | 解出（分钟） |",
        "|---|---|---|---|---|",
    ]
    speed_map = {s["contestId"]: s for s in sp["by_contest"]}
    for i, r in enumerate(p["contests"], 1):
        delta = f"{r['delta']:+d}"
        spd = speed_map.get(r["contestId"], {}).get("minutes", {})
        detail = "、".join(f"{k}:{v}" for k, v in spd.items()) or "—"
        lines.append(f"| {i} | {r['name'][:32]} | {r['rank']} | {delta} | {detail} |")

    lines += [
        "",
        "## 七、试过但没解出的题",
        "",
        f"共 **{p['unsolved_problem_count']}** 道（按难度降序，含尝试次数）：",
        "",
        "| 题目 | 难度 | 尝试次数 | 标签 |",
        "|---|---|---|---|",
    ]
    for u in p["unsolved_sample"]:
        tags = "、".join(u["tags"])
        lines.append(f"| {u['name'] or '—'} | {u['rating'] or '—'} "
                     f"| {u['attempts']} | {tags} |")

    lines += [
        "",
        "## 八、结论",
        "",
        "> 本报告由 `coach.py` 自动生成，数据来自 Codeforces 公开接口。",
        "",
        "**两个必须知道的数据局限**：",
        "",
        "1. **只能看到「提交过」的题**。看到题但没思路、完全没提交的，接口里不存在。",
        "   所以「薄弱点」只能从「提交了但没过」推断，会低估真实的薄弱面。",
        "2. **未 AC 的题没有耗时数据**。速度分析只覆盖做出来的题。",
        "",
        "### 自动生成的观察",
        "",
    ]

    # 练习难度 vs 当前 rating 的差距
    med = d["median_solved_rating"] or 0
    cur = p.get("current_rating") or 0
    if med and cur and cur - med >= 200:
        lines.append(
            f"- ⚠️ **练习难度显著低于当前水平**：解出题目的难度中位数是 **{med}**，"
            f"而当前 rating 是 **{cur}**，差 **{cur - med}** 分。"
            "说明大量时间花在偏简单的题上。")
    if t["earlier_solved_median_rating"] and t["recent_solved_median_rating"]:
        diff = t["recent_solved_median_rating"] - t["earlier_solved_median_rating"]
        if diff <= -50:
            lines.append(
                f"- ⚠️ **近期解题难度下移**：从 {t['earlier_solved_median_rating']} "
                f"降到 {t['recent_solved_median_rating']}（{diff:+d}），"
                "在舒适区做题。")
    if o["submissions"] < 500:
        lines.append(
            f"- ⚠️ **总提交量偏少**：只有 {o['submissions']} 次提交、"
            f"{o['problems_solved']} 道题。"
            "这个量级通常不足以支撑 rating 持续上升——"
            "**rating 主要靠题量堆出来**。")

    lines += [
        "",
        "### 建议的下一步（供参考，不替代你自己的判断）",
        "",
        "| 优先级 | 动作 | 理由 |",
        "|---|---|---|",
        "| 🔴 | **练习难度上移到 1300–1600** | 当前中位数明显低于实际水平，"
        "在舒适区做题难以涨分 |",
        "| 🔴 | **提高题量** | 提交量偏少是硬约束，"
        "每场只做 A/B/C 很难突破 |",
        "| 🟡 | **专项攻薄弱标签** | 见第三节的诊断表 |",
        "| 🟡 | **赛后复盘未 AC 的题** | 见第七节清单，那些是真实的知识缺口 |",
        "",
        "> 薄弱点判据（尝试 ≥5 且通过率 <60%）是启发式的，",
        "> **建议结合自己的主观感受交叉验证**——你比任何统计更清楚哪里别扭。",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    handle = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HANDLE
    subs, rating, starts = load_data(handle)
    print("分析中…")
    p = analyze(subs, rating, starts)
    p["handle"] = handle
    OUT_PROFILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(p)

    o, c = p["overall"], p["comparison"]
    print()
    print("=" * 60)
    print(f"选手 {handle}")
    print("=" * 60)
    print(f"  提交 {o['submissions']}，解出 {o['problems_solved']} 题"
          f"（{o['solve_rate_problem']:.1%}）")
    print(f"  最高难度 {p['difficulty']['max_solved_rating']}，"
          f"中位数 {p['difficulty']['median_solved_rating']}")
    print()
    print(f"  前期 {c['earlier_contests']} 场：平均 {c['earlier_avg_delta']:+} 分，"
          f"平均排名 {c['earlier_avg_rank']}")
    print(f"  近期 {c['recent_contests']} 场：平均 {c['recent_avg_delta']:+} 分，"
          f"平均排名 {c['recent_avg_rank']}")
    print()
    if p["weak_tags"]:
        print("  薄弱标签：")
        for w in p["weak_tags"][:6]:
            print(f"    {w['tag']:<28} 尝试 {w['tried']:>2} 通过率 {w['rate']:.0%}")
    print()
    print(f"  已写出：\n    {OUT_PROFILE}\n    {OUT_REPORT}")


if __name__ == "__main__":
    main()
