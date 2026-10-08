import json
from pathlib import Path
from client import chat_with_tools
import logging
import inspect
from personality import SYSTEM_PROMPT
from datetime import datetime
from rag_search import Retriever
import subprocess

retriever = Retriever(Path("data/index"))

TOOL_REGISTRY: list[dict] = []

logger = logging.getLogger(__name__)

MAX_TOKENS = 50000

def tool(description: str,params: dict):
    """装饰器，用于注册工具函数"""
    def decorator(func):
        sig = inspect.signature(func)
        properties = {}
        required = []
        # 类型映射表：Python 类型 → JSON Schema 类型
        type_map = {int: "integer", float: "number", str: "string", bool: "boolean"}
        for name, param in sig.parameters.items():
            properties[name] = {
                "type": type_map.get(param.annotation, "string"),
                "description": params.get(name,"")
            }
            if param.default is inspect.Parameter.empty:    # ← 加这行
                required.append(name)

        TOOL_REGISTRY.append({
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }

        })
        return func
    return decorator


DATA_DIR = Path("data/solutions")
OUTPUT_DIR = Path("data/output")
CF_CODE_DIR = Path("D:/c语言/cf")


@tool(description="读取文件的指定区间内容，支持绝对路径和相对路径", params={
    "path": "文件路径（绝对路径或相对路径）",
    "start": "起始字符位置，默认 0",
    "limit": "读取长度，默认 2000",
})
def read_file(path: str, start: int = 0, limit: int = 2000) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = DATA_DIR / path
    try:
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="gbk")
        return content[start:start+limit]
    except OSError as e:
        return f"文件 {path} 读取失败: {e}"


@tool(description="写入文件", params={
    "filename": "文件名",
    "content": "内容",
    "directory": "目录，如 solutions 或 output，默认 output",
})
def write_file(filename: str, content: str, directory: str = "output") -> str:
    target_dir = Path("data") / directory
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    try:
        path.write_text(content, encoding="utf-8")
        return f"已写入 {path}，共 {len(content)} 字符"
    except OSError as e:
        return f"写入失败: {filename}，错误: {e}"

@tool(description="列出本地语料目录下的所有文件名，需要知道有哪些文件时使用", params={})
def list_files() -> str:
    files = [f.name for f in DATA_DIR.iterdir() if f.is_file()]
    return "\n".join(files)


@tool(description="获取当前日期，格式 YYYY-MM-DD", params={})
def get_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")

@tool(description="搜索用户的题解库，回答「我之前怎么做的」这类问题时使用", params={
    "query": "搜索关键词或问题",
})
def search_solutions(query: str) -> str:
    hits = retriever.search(query, top_k=3)
    if not hits:
        return "语料库里没有相关记录"
    return "\n\n".join(f"[来源: {h.source}]\n{h.text}" for h in hits)

@tool(description="重建题解检索索引，整理完新题解后必须调用", params={})
def rebuild_index() -> str:
    result = subprocess.run(
        ["uv", "run", "python", "rag_load.py"],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent),
    )
    if result.returncode == 0:
        return "索引重建完成"
    return f"索引重建失败：{result.stderr}"

@tool(description="根据题目编号查找代码文件，如「1121C」", params={
    "problem_id": "题目编号，如 1121C",
})
def find_code(problem_id: str) -> str:
    """在 CF_CODE_DIR 下查找题目对应的代码文件"""
    import re
    m = re.match(r"(\d+)([A-Za-z])", problem_id.strip())
    if not m:
        return f"无法解析题目编号: {problem_id}"
    round_num, letter = m.group(1), m.group(2).upper()

    if not CF_CODE_DIR.exists():
        return f"代码目录不存在: {CF_CODE_DIR}"

    # 遍历所有子目录，找含 round_num 的（用单词边界，避免 1121 匹配 11210）
    for d in CF_CODE_DIR.iterdir():
        if not d.is_dir():
            continue
        if not re.search(rf"\b{round_num}\b", d.name):
            continue
        # 在这个目录里找 letter.cpp（大小写兼容）
        for f in d.iterdir():
            if f.name.upper() == f"{letter}.CPP":
                return str(f)
        return f"找到目录 {d.name}，但没有 {letter}.cpp"

    return f"没有找到含 {round_num} 的目录"




def run_agent(user_input: str, history: list | None = None, max_turns: int = 8) -> tuple[str, list]:
    if history is None:
        history = []

    logger.info(f"开始执行代理，用户输入: {user_input}")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_input},
    ]
    recent_calls: list[str] = []
    total_tokens = 0

    for turn in range(max_turns):
        response = chat_with_tools(messages, TOOL_REGISTRY)
        message = response["choices"][0]["message"]
        usage = response["usage"]
        total_tokens += usage["total_tokens"]

        logger.info(f"第 {turn + 1} 轮对话，输入 {usage['prompt_tokens']} tokens, 输出 {usage['completion_tokens']} tokens, 总计 {usage['total_tokens']} tokens, 累计总费用: ¥{total_tokens * 0.02 / 1e6:.6f}")

        if total_tokens > MAX_TOKENS:
            logger.warning(f"达到 token 预算上限（{total_tokens}），已停止")
            return f"达到 token 预算上限（{total_tokens}），已停止", history

        if not message.get("tool_calls"):
            logger.info(f"任务结束，总轮数={turn+1}，总 tokens={total_tokens}")
            answer = message["content"]
            new_history = history + [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": answer},
            ]
            return answer, new_history

        messages.append(message)

        for call in message["tool_calls"]:
            name = call["function"]["name"]
            args = json.loads(call["function"]["arguments"])
            logger.info(f"[轮 {turn+1}] 调用工具 {name}, 参数 {args}")

            signature = f"{name}:{json.dumps(args, sort_keys=True)}"
            if recent_calls.count(signature) >= 3:
                messages.append({
                    "role": "user",
                    "content": "你已经重复调用同一个工具多次，请换一种方式，或直接给出最终答案。"
                })
                continue

            if name == "read_file":
                result = read_file(**args)
            elif name == "write_file":
                result = write_file(**args)
            elif name == "list_files":
                result = list_files()
            elif name == "get_date":
                result = get_date()
            elif name == "search_solutions":
                result = search_solutions(**args)
            elif name == "find_code":
                result = find_code(**args)
            elif name == "rebuild_index":
                result = rebuild_index()
            else:
                result = f"未知工具: {name}"

            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "content": result,
            })
            recent_calls.append(signature)

    return "达到最大轮数", history

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        filename="agent.log",
        encoding="utf-8",
    )
    print("贪心：哼，来了？说吧，什么事。")
    history = []
    while True:
        user_input = input("你: ")
        if user_input.strip() in ("exit", "quit", "拜拜"):
            print("贪心：……行吧")
            break
        answer, history = run_agent(user_input, history)
        print(f"贪心: {answer}")