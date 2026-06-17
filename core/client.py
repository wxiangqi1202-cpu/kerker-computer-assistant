"""
API 客户端 —— 纯网络层

职责：
- 创建 AsyncOpenAI 客户端
- 带重试的 API 调用
- 构建 API 请求参数
- 响应解析（流式 / 同步）

不涉及业务逻辑（路由、工具执行、上下文管理等）。
"""

import asyncio
from openai import AsyncOpenAI, APIStatusError, APIConnectionError, APITimeoutError
from core import config
from core.credentials import load_api_key

_API_MAX_RETRIES = 3
_API_RETRY_BASE_DELAY = 1.0

_bg_clients = {}


def get_background_client(model="deepseek-v4-flash", timeout=30.0):
    """获取后台任务共享客户端（被动提取、记忆合并等），按 base_url 缓存复用。
    避免每次后台任务都新建+关闭客户端的开销。
    """
    base_url = config.get_model_base_url(model)
    cache_key = base_url
    if cache_key in _bg_clients:
        return _bg_clients[cache_key]
    api_key = load_api_key()
    if not api_key:
        return None
    client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    _bg_clients[cache_key] = client
    return client


def create_client():
    """创建 AsyncOpenAI 客户端"""
    api_key = load_api_key()
    if not api_key:
        print("未配置 API Key，请运行 kerker 进行首次配置。")
        api_key = input("API Key: ").strip()
    base_url = config.get_model_base_url()
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


async def api_call_with_retry(client, kwargs):
    """带指数退避重试的 API 调用"""
    last_error = None
    for attempt in range(_API_MAX_RETRIES):
        try:
            return await client.chat.completions.create(**kwargs)
        except (APIStatusError, APIConnectionError, APITimeoutError) as err:
            last_error = err
            status = getattr(err, "status_code", 0)
            if isinstance(err, APIStatusError) and status in (400, 401, 403, 404):
                raise
            if attempt < _API_MAX_RETRIES - 1:
                delay = _API_RETRY_BASE_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
    raise last_error


def build_kwargs(messages, tool_specs=None):
    """构建 API 请求参数"""
    extra_body = {}
    if config.ENABLE_THINKING:
        extra_body["thinking"] = {"type": "enabled"}

    kwargs = dict(
        model=config.MODEL,
        messages=messages,
        stream=config.STREAM,
        reasoning_effort=config.REASONING_EFFORT,
    )
    if config.MAX_TOKENS:
        kwargs["max_tokens"] = config.MAX_TOKENS
    if extra_body:
        kwargs["extra_body"] = extra_body
    if config.STREAM:
        kwargs["stream_options"] = {"include_usage": True}

    if tool_specs:
        kwargs["tools"] = tool_specs

    return kwargs


def extract_usage(usage_obj):
    """从 API 响应中提取 token 使用量"""
    if not usage_obj:
        return None
    return {
        "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
    }


async def handle_stream(response):
    """处理流式 API 响应，yield 事件"""
    phase = "init"
    reply = ""
    reasoning = ""
    tool_calls_data = {}
    usage = None

    async for chunk in response:
        if hasattr(chunk, "usage") and chunk.usage:
            usage = extract_usage(chunk.usage)

        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta

        rc = getattr(delta, "reasoning_content", None)
        if rc:
            reasoning += rc
            if phase != "thinking":
                phase = "thinking"
                yield {"type": "thinking"}

        tc_list = getattr(delta, "tool_calls", None)
        if tc_list:
            for tc in tc_list:
                idx = tc.index
                if idx not in tool_calls_data:
                    tool_calls_data[idx] = {"id": "", "name": "", "args": ""}
                if tc.id:
                    tool_calls_data[idx]["id"] = tc.id
                func = getattr(tc, "function", None)
                if func:
                    if func.name:
                        tool_calls_data[idx]["name"] = func.name
                        yield {"type": "tool", "name": func.name}
                    if func.arguments:
                        tool_calls_data[idx]["args"] += func.arguments

        if delta.content:
            if phase != "replying":
                phase = "replying"
            reply += delta.content
            yield {"type": "text", "content": delta.content}

    parsed_calls = list(tool_calls_data.values()) if tool_calls_data else []

    assistant_msg = {"role": "assistant", "content": reply or None}
    if reasoning:
        assistant_msg["reasoning_content"] = reasoning
    if parsed_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["args"]},
            }
            for tc in parsed_calls
        ]

    if not parsed_calls:
        yield {"type": "done", "content": reply, "assistant_msg": assistant_msg, "usage": usage}

    yield {"_result": {"tool_calls": parsed_calls, "assistant_msg": assistant_msg}}


async def handle_sync(response):
    """处理同步 API 响应，yield 事件"""
    msg = response.choices[0].message
    usage = extract_usage(getattr(response, "usage", None))

    reasoning_content = getattr(msg, "reasoning_content", None)
    if reasoning_content:
        yield {"type": "thinking"}

    parsed_calls = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            yield {"type": "tool", "name": tc.function.name}
            parsed_calls.append({
                "id": tc.id,
                "name": tc.function.name,
                "args": tc.function.arguments,
            })

    content = msg.content or ""
    if content:
        yield {"type": "text", "content": content}

    assistant_msg = {"role": "assistant", "content": content or None}
    if reasoning_content:
        assistant_msg["reasoning_content"] = reasoning_content
    if parsed_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["args"]},
            }
            for tc in parsed_calls
        ]

    if not parsed_calls:
        yield {"type": "done", "content": content, "assistant_msg": assistant_msg, "usage": usage}

    yield {"_result": {"tool_calls": parsed_calls, "assistant_msg": assistant_msg}}
