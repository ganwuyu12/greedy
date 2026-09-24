import time
import requests
import logging
from config import API_KEY, API_URL

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用相关的统一异常基类"""


class LLMClientError(LLMError):
    """4xx：参数/鉴权问题，重试无意义"""


class LLMTransientError(LLMError):
    """429/5xx/超时：可重试，已耗尽重试次数"""

def calc_cost(prompt_tokens: int, completion_tokens: int) -> float:
    input_price = 0.02/1e6
    output_price = 4/1e6
    total_price = prompt_tokens * input_price + completion_tokens * output_price
    return total_price


def chat(messages: list, max_retries: int = 3) -> str:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": messages,
    }

    for attempt in range(max_retries):
        response = None
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            response_dict = response.json()
            return response_dict['choices'][0]['message']['content']
        except requests.RequestException as e:
            status = response.status_code if response is not None else None
            if status is not None and 400 <= status < 500 and status != 429:
                raise LLMClientError(f"请求错误（不重试）: {e} 状态码: {status}")
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"第 {attempt + 1} 次请求失败，错误: {e}. 正在等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                raise LLMTransientError(f"重试 {max_retries} 次仍失败: {e}")
    raise LLMTransientError("重试次数耗尽")



def chat_with_tools(messages: list, tools: list, max_retries: int = 3) -> dict:
    """带工具调用的聊天，返回完整的 message 对象"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "tools": tools,
    }

    for attempt in range(max_retries):
        response = None
        try:
            response = requests.post(API_URL, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            response_dict = response.json()
            return response_dict      # ← 返回完整 message
        except requests.RequestException as e:
            status = response.status_code if response is not None else None
            if status is not None and 400 <= status < 500 and status != 429:
                raise LLMClientError(f"请求错误（不重试）: {e} 状态码: {status}")
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning(f"第 {attempt + 1} 次请求失败，错误: {e}. 正在等待 {wait} 秒后重试...")
                time.sleep(wait)
            else:
                raise LLMTransientError(f"重试 {max_retries} 次仍失败: {e}")
    raise LLMTransientError("重试次数耗尽")