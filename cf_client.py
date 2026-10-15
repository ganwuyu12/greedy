#!/usr/bin/env python3
"""
Codeforces API 客户端

为什么单独成模块：
  教练功能的每一步（能力雷达、薄弱点诊断、推荐出题、赛后复盘）都要读 CF 数据。
  如果每个功能自己写一遍请求，就会重复实现限流与容错，而且容易违规。

实测约束（来自官方 apiHelp）：
  > API may be requested at most 1 time per two seconds.
  超过会被临时拒绝，状态为 FAILED + "Call limit exceeded"。

所以本模块负责三件事：
  1. **限流**：全局最小请求间隔 2 秒，绝不并发
  2. **容错**：网络失败指数退避重试；识别 FAILED 状态并给出原因
  3. **缓存**：结果落盘，跨进程复用（避免重复拉全量数据）

用法：
    from cf_client import CFClient

    cf = CFClient()
    info   = cf.user_info("ganwuyu")
    subs   = cf.user_status("ganwuyu", max_pages=3)   # 自动翻页 + 缓存
    rating = cf.user_rating("ganwuyu")
    probs  = cf.problemset()                          # 全量题库（缓存 7 天）

命令行自检：
    python cf_client.py ganwuyu
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

BASE = Path(__file__).parent
CACHE_DIR = BASE / "data" / "cf_cache"
RAW_DIR = BASE / "data" / "cf_raw"

API = "https://codeforces.com/api"
MIN_INTERVAL = 2.0          # 官方限制：每 2 秒最多 1 次
MAX_TRIES = 3
TIMEOUT = 40


class CFError(RuntimeError):
    """接口返回 FAILED"""


class CFClient:
    def __init__(self, cache_dir: Path = CACHE_DIR, min_interval: float = MIN_INTERVAL,
                 verbose: bool = True) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.verbose = verbose
        self._last_call = 0.0      # 上次请求时间（限流用）
        self.api_calls = 0         # 统计真实请求次数（验证限流是否生效）

    # ------------------------------------------------------------ 底层请求

    def _throttle(self) -> None:
        """保证两次请求间隔 >= min_interval"""
        wait = self.min_interval - (time.time() - self._last_call)
        if wait > 0:
            if self.verbose:
                print(f"    [限流] 等待 {wait:.1f}s")
            time.sleep(wait)
        self._last_call = time.time()

    def _get(self, method: str, params: dict | None = None) -> dict:
        q = urllib.parse.urlencode(params or {})
        url = f"{API}/{method}" + (f"?{q}" if q else "")

        last_err: Exception | None = None
        for attempt in range(1, MAX_TRIES + 1):
            self._throttle()
            try:
                self.api_calls += 1
                req = urllib.request.Request(url, headers={"User-Agent": "greedy-agent/0.1"})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    data = json.loads(r.read().decode("utf-8"))
                if data.get("status") != "OK":
                    comment = data.get("comment", "未知原因")
                    # 限流是临时性的，值得重试；参数错误不值得
                    if "limit" in comment.lower() and attempt < MAX_TRIES:
                        if self.verbose:
                            print(f"    [限流命中] {comment}，退避重试")
                        time.sleep(self.min_interval * (2 ** attempt))
                        continue
                    raise CFError(f"{method} 失败：{comment}")
                return data["result"]
            except CFError:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                if self.verbose:
                    print(f"    [重试 {attempt}/{MAX_TRIES}] {type(e).__name__}: {e}")
                if attempt < MAX_TRIES:
                    time.sleep(self.min_interval * (2 ** attempt))
        raise CFError(f"{method} 请求失败：{last_err}")

    # ------------------------------------------------------------ 缓存

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _load_cache(self, key: str, max_age_hours: float) -> dict | None:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        ts = obj.get("_cached_at", 0)
        age_h = (time.time() - ts) / 3600
        if age_h > max_age_hours:
            return None
        if self.verbose:
            print(f"    [缓存命中] {key}（{age_h:.1f} 小时前）")
        return obj.get("data")

    def _save_cache(self, key: str, data) -> None:
        obj = {"_cached_at": time.time(),
               "_cached_at_iso": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
               "data": data}
        self._cache_path(key).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    # ------------------------------------------------------------ 公开接口

    def user_info(self, handle: str, max_age_hours: float = 1) -> dict:
        key = f"user_info_{handle.lower()}"
        cached = self._load_cache(key, max_age_hours)
        if cached:
            return cached
        result = self._get("user.info", {"handles": handle})
        self._save_cache(key, result)
        return result

    def user_rating(self, handle: str, max_age_hours: float = 1) -> list[dict]:
        key = f"user_rating_{handle.lower()}"
        cached = self._load_cache(key, max_age_hours)
        if cached:
            return cached
        result = self._get("user.rating", {"handle": handle})
        self._save_cache(key, result)
        return result

    def user_status(self, handle: str, max_pages: int = 5, page_size: int = 1000,
                    max_age_hours: float = 1) -> list[dict]:
        """拉取提交记录，自动翻页

        max_pages 控制深度：5 页 × 1000 条 = 最多 5000 条提交。
        注意每页一次请求，且间隔 2 秒——拉 5 页要 10 秒，属正常。
        """
        key = f"user_status_{handle.lower()}_{max_pages}"
        cached = self._load_cache(key, max_age_hours)
        if cached:
            return cached

        all_subs: list[dict] = []
        for page in range(max_pages):
            frm = page * page_size + 1
            if self.verbose:
                print(f"    拉取第 {page + 1}/{max_pages} 页（from={frm}）")
            try:
                part = self._get("user.status", {
                    "handle": handle, "from": frm, "count": page_size})
            except CFError as e:
                if not all_subs:
                    raise
                if self.verbose:
                    print(f"    翻页中断（已有 {len(all_subs)} 条）：{e}")
                break
            if not part:
                break
            all_subs.extend(part)
            if len(part) < page_size:      # 最后一页
                break

        self._save_cache(key, all_subs)
        return all_subs

    def problemset(self, max_age_hours: float = 168) -> dict:
        """全量题库（题目 + 提交统计）

        数据量约 2 MB，缓存 7 天——它变化很慢，没必要频繁拉。
        """
        key = "problemset_problems"
        cached = self._load_cache(key, max_age_hours)
        if cached:
            return cached
        result = self._get("problemset.problems")
        self._save_cache(key, result)
        return result

    def contest_list(self, max_age_hours: float = 24) -> list[dict]:
        key = "contest_list"
        cached = self._load_cache(key, max_age_hours)
        if cached:
            return cached
        result = self._get("contest.list", {"gym": "false"})
        self._save_cache(key, result)
        return result

    def contest_name_map(self) -> dict[int, str]:
        """contestId → 比赛名"""
        return {c["id"]: c["name"] for c in self.contest_list()}

    # ------------------------------------------------------------ 便捷封装

    def submissions_with_problem(self, handle: str, max_pages: int = 5) -> list[dict]:
        """提交记录，补上题目名与官方标签

        CF 的 user.status 只给 contestId + index，不给题目名和标签。
        要分析「哪个标签弱」，必须去题库表里查。
        """
        subs = self.user_status(handle, max_pages=max_pages)
        ps = self.problemset()
        table = {}
        for p in ps["problems"]:
            cid, idx = p.get("contestId"), p.get("index")
            if cid is None:
                continue
            table[(int(cid), str(idx))] = {
                "name": p.get("name", ""),
                "rating": p.get("rating"),
                "tags": p.get("tags", []),
            }
        out = []
        for s in subs:
            prob = s.get("problem", {})
            cid, idx = prob.get("contestId"), prob.get("index")
            meta = table.get((int(cid), str(idx)), {}) if cid is not None else {}
            out.append({
                **s,
                "problem_name": meta.get("name") or prob.get("name", ""),
                "problem_rating": meta.get("rating") if meta else prob.get("rating"),
                "problem_tags": meta.get("tags") or prob.get("tags", []),
            })
        return out


# ---------------------------------------------------------------- 命令行自检

def main() -> None:
    handle = sys.argv[1] if len(sys.argv) > 1 else "ganwuyu"
    cf = CFClient()

    print("=" * 60)
    print(f"自检：{handle}")
    print("=" * 60)

    print("\n1) 用户信息")
    try:
        info = cf.user_info(handle)
        u = info[0] if isinstance(info, list) else info
        print(f"   rating={u.get('rating')} max={u.get('maxRating')} rank={u.get('rank')}")
    except CFError as e:
        print(f"   失败：{e}")

    print("\n2) 参赛记录")
    try:
        rs = cf.user_rating(handle)
        print(f"   {len(rs)} 场，当前 {rs[-1]['newRating']}，最高 {max(r['newRating'] for r in rs)}")
    except CFError as e:
        print(f"   失败：{e}")

    print("\n3) 提交记录（1 页）")
    try:
        subs = cf.user_status(handle, max_pages=1)
        ac = sum(1 for s in subs if s.get("verdict") == "OK")
        print(f"   拉到 {len(subs)} 条，其中 AC {ac} 条")
    except CFError as e:
        print(f"   失败：{e}")

    print(f"\n本次真实请求次数：{cf.api_calls}（限流间隔 {MIN_INTERVAL}s）")


if __name__ == "__main__":
    main()
