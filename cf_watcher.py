import json
import time
import requests
from pathlib import Path
from my_agent import run_agent

CF_HANDLE = "ganwuyu"
CF_CODE_DIR = Path("D:/c语言/cf")
STATE_FILE = Path("data/cf_state.json")

CONTEST_CACHE = {}


def get_contest_name(contest_id: int) -> str:
    """从 CF API 拿比赛名（带缓存）"""
    if contest_id in CONTEST_CACHE:
        return CONTEST_CACHE[contest_id]
    r = requests.get("https://codeforces.com/api/contest.list")
    for c in r.json()["result"]:
        CONTEST_CACHE[c["id"]] = c["name"]
    return CONTEST_CACHE.get(contest_id, "")


def get_new_accepted() -> list[dict]:
    """拿“新的 AC 提交”"""
    r = requests.get(
        f"https://codeforces.com/api/user.status?handle={CF_HANDLE}&from=1&count=20"
    )
    submissions = r.json()["result"]

    last_id = 0
    if STATE_FILE.exists():
        last_id = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_submission_id", 0)

    new_accepted = []
    for s in submissions:
        if s["id"] <= last_id:
            continue
        if s["verdict"] != "OK":
            continue
        new_accepted.append(s)

    if submissions:
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({"last_submission_id": submissions[0]["id"]}),
            encoding="utf-8",
        )

    return new_accepted


def watch_once():
    """查一次，处理新 AC"""
    new = get_new_accepted()
    for s in new:
        contest_id = s["contestId"]
        index = s["problem"]["index"]
        contest_name = get_contest_name(contest_id)
        problem_id = f"{contest_id}{index}"

        code_path = CF_CODE_DIR / contest_name / f"{index}.cpp"
        if not code_path.exists():
            print(f"找不到代码：{code_path}")
            continue

        print(f"新 AC：{problem_id}，代码在 {code_path}")
        answer, _ = run_agent(f"我做了 {problem_id}，代码在 {code_path}，帮我整理")
        print(answer)


if __name__ == "__main__":
    print("开始监听 CF 提交...")
    while True:
        try:
            watch_once()
        except Exception as e:
            print(f"出错：{e}")
        time.sleep(60)