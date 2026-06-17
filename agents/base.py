"""
SubAgent 基类 v2 —— 共享上下文注入 + 链式调用 + 重试 + 预算控制
"""

import asyncio
from openai import AsyncOpenAI
from core import config
from core.credentials import load_api_key
import skills as skills_module


class SubAgent:
    """子智能体基类"""

    name = ""
    description = ""
    model = None
    system_prompt = ""
    allowed_skills = None
    max_turns = 5
    enable_thinking = False
    can_call_agents = False
    max_retries = 1
    timeout_seconds = 120

    def __init__(self):
        self._client = None
        self._client_base_url = None

    def _get_client(self):
        model = self.model or config.MODEL
        base_url = config.get_model_base_url(model)
        if self._client is None or self._client_base_url != base_url:
            api_key = load_api_key()
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._client_base_url = base_url
        return self._client

    def _get_tools(self):
        if self.allowed_skills is None:
            return []
        all_specs = skills_module.get_all_specs()
        allowed = set(self.allowed_skills)
        if self.can_call_agents:
            for spec in all_specs:
                fname = spec["function"]["name"]
                if fname.startswith("agent_") and fname != f"agent_{self.name}":
                    allowed.add(fname)
        return [s for s in all_specs if s["function"]["name"] in allowed]

    async def run(self, task, on_status=None):
        """
        执行子任务，带重试和超时保护。
        on_status: 可选回调 on_status(text)。
        返回结果字符串。
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0 and on_status:
                    on_status(f"子智能体 [{self.name}] 第 {attempt + 1} 次尝试...")
                result = await asyncio.wait_for(
                    self._execute(task, on_status),
                    timeout=self.timeout_seconds,
                )
                return result
            except asyncio.TimeoutError:
                last_error = f"子智能体 [{self.name}] 执行超时 ({self.timeout_seconds}s)"
                if on_status:
                    on_status(last_error)
                if attempt >= self.max_retries:
                    raise asyncio.TimeoutError(last_error)
            except Exception as err:
                last_error = str(err)
                if attempt >= self.max_retries:
                    raise

    async def _execute(self, task, on_status=None):
        """实际执行逻辑（单次尝试），支持流式进度回调"""
        client = self._get_client()
        model = self.model or config.MODEL

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]

        tools = self._get_tools()

        for turn in range(self.max_turns):
            kwargs = dict(
                model=model,
                messages=messages,
                stream=True,
            )
            if tools:
                kwargs["tools"] = tools
            if self.enable_thinking:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                kwargs["reasoning_effort"] = "low"

            response = await client.chat.completions.create(**kwargs)

            content = ""
            reasoning = ""
            tool_calls_data = {}
            preview_len = 0

            async for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning += rc

                if delta.content:
                    content += delta.content
                    if on_status and len(content) - preview_len >= 20:
                        snippet = content[-40:].replace("\n", " ").strip()
                        on_status(f"...{snippet}")
                        preview_len = len(content)

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
                            if func.arguments:
                                tool_calls_data[idx]["args"] += func.arguments

            parsed_calls = list(tool_calls_data.values()) if tool_calls_data else []

            if not parsed_calls:
                return content or ""

            assistant_msg = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    }
                    for tc in parsed_calls
                ],
            }
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            messages.append(assistant_msg)

            for tc in parsed_calls:
                if on_status:
                    on_status(f"🔧 {tc['name']}")
                result = await skills_module.async_call(tc["name"], tc["args"])
                if on_status:
                    first_line = (result or "").strip().split("\n")[0][:50]
                    if first_line and "执行出错" not in first_line:
                        on_status(f"  → {first_line}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        try:
            summary_resp = await client.chat.completions.create(
                model=model, messages=messages + [
                    {"role": "user", "content": "请根据以上工具调用结果，给出最终总结回复。"}
                ], stream=False,
            )
            if summary_resp.choices:
                return summary_resp.choices[0].message.content or "子智能体达到最大轮次限制"
            return "子智能体达到最大轮次限制"
        except Exception:
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    return msg["content"]
            return "子智能体达到最大轮次限制"
