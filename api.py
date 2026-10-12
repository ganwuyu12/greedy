from fastapi import FastAPI
from pydantic import BaseModel
from my_agent import run_agent
import json
import requests
from pathlib import Path

CF_HANDLE = "ganwuyu"
STATE_FILE = Path("data/cf_state.json")
CF_CODE_DIR = Path("D:/c语言/cf")
CONTEST_CACHE = {}

app = FastAPI(title="贪心 API")


class ChatRequest(BaseModel):
    message: str
    history: list = []


class ChatResponse(BaseModel):
    reply: str
    history: list


class SyncResponse(BaseModel):
    with_notes: list[str]
    without_notes: list[str]


def get_contest_name(contest_id: int) -> str:
    if contest_id in CONTEST_CACHE:
        return CONTEST_CACHE[contest_id]
    r = requests.get("https://codeforces.com/api/contest.list")
    for c in r.json()["result"]:
        CONTEST_CACHE[c["id"]] = c["name"]
    return CONTEST_CACHE.get(contest_id, "")


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        reply, new_history = run_agent(req.message, req.history)
        return ChatResponse(reply=reply, history=new_history)
    except Exception as e:
        return ChatResponse(reply=f"哼，出错了：{e}。等下再试。", history=req.history)


@app.post("/sync", response_model=SyncResponse)
def sync() -> SyncResponse:
    last_id = 0
    if STATE_FILE.exists():
        last_id = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_submission_id", 0)

    r = requests.get(f"https://codeforces.com/api/user.status?handle={CF_HANDLE}&from=1&count=20")
    subs = r.json()["result"]

    new_accepted = [s for s in subs if s["id"] > last_id and s["verdict"] == "OK"]

    if subs:
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({"last_submission_id": subs[0]["id"]}),
            encoding="utf-8",
        )

    with_notes = []
    without_notes = []

    for s in new_accepted:
        contest_id = s["contestId"]
        index = s["problem"]["index"]
        problem_id = f"{contest_id}{index}"

        contest_name = get_contest_name(contest_id)
        code_path = CF_CODE_DIR / contest_name / f"{index}.cpp"

        if not code_path.exists():
            without_notes.append(problem_id)
            continue

        content = code_path.read_text(encoding="utf-8", errors="ignore")
        has_notes = "//标签" in content or "/*思路" in content

        if has_notes:
            with_notes.append(problem_id)
        else:
            without_notes.append(problem_id)

    return SyncResponse(with_notes=with_notes, without_notes=without_notes)


@app.get("/")
def root():
    return {"name": "贪心", "status": "ok"}