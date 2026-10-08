from fastapi import FastAPI
from pydantic import BaseModel
from my_agent import run_agent

app = FastAPI(title="贪心 API")


class ChatRequest(BaseModel):
    message: str
    history: list = []


class ChatResponse(BaseModel):
    reply: str
    history: list


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    try:
        reply, new_history = run_agent(req.message, req.history)
        return ChatResponse(reply=reply, history=new_history)
    except Exception as e:
        return ChatResponse(reply=f"哼，出错了：{e}。等下再试。", history=req.history)


@app.get("/")
def root():
    return {"name": "贪心", "status": "ok"}