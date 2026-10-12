from fastapi import FastAPI
from pydantic import BaseModel
from my_agent import run_agent
import json
import requests
from pathlib import Path

CF_HANDLE = "ganwuyu"
STATE_FILE = Path("data/cf_state.json")

app = FastAPI(title="贪心 API")


class ChatRequest(BaseModel):
    message: str
    history: list = []


class ChatResponse(BaseModel):
    reply: str
    history: list


class SyncResponse(BaseModel):
    new_problems: list[str]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        reply, new_history = run_agent(req.message, req.history)
        return ChatResponse(reply=reply, history=new_history)
    except Exception as e:
        return ChatResponse(reply=f"哼，出错了：{e}。等下再试。", history=req.history)


@app.post("/sync", response_model=SyncResponse)
def sync() -> SyncResponse:
    last_time = 0
    if STATE_FILE.exists():
        last_time = json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_time", 0)

    r = requests.get(f"https://codeforces.com/api/user.status?handle={CF_HANDLE}&from=1&count=20")
    subs = r.json()["result"]

    new_accepted = [s for s in subs if s["creationTimeSeconds"] > last_time and s["verdict"] == "OK"]

    if subs:
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({"last_time": subs[0]["creationTimeSeconds"]}),
            encoding="utf-8",
        )

    new_problems = []
    for s in new_accepted:
        problem_id = f"{s['contestId']}{s['problem']['index']}"
        run_agent(f"我做了 {problem_id}，帮我整理")
        new_problems.append(problem_id)

    return SyncResponse(new_problems=new_problems)


@app.get("/")
def root():
    return {"name": "贪心", "status": "ok"}