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
        base_url = config.MODELS.get(model, {}).get("base_url", config.BASE_URL)
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
            except Exception as err:
                last_error = str(err)
                if attempt >= self.max_retries:
                    raise

        return last_error or "子智能体执行失败"

    async def _execute(self, task, on_status=None):
        """实际执行逻辑（单次尝试）"""
        client = self._get_client()
        model = self.model or config.MODEL

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task},
        ]

        tools = self._get_tools()
        total_tokens = 0

        for turn in range(self.max_turns):
            kwargs = dict(
                model=model,
                messages=messages,
                stream=False,
            )
            if tools:
                kwargs["tools"] = tools
            if self.enable_thinking:
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                kwargs["reasoning_effort"] = "low"

            if on_status:
                on_status(f"子智能体 [{self.name}] 第 {turn + 1} 轮推理...")

            response = await client.chat.completions.create(**kwargs)
            msg = response.choices[0].message

            usage = getattr(response, "usage", None)
            if usage:
                total_tokens += getattr(usage, "total_tokens", 0) or 0

            reasoning = getattr(msg, "reasoning_content", None)

            if not msg.tool_calls:
                return msg.content or ""

            assistant_msg = {
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            }
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            messages.append(assistant_msg)

            for tc in msg.tool_calls:
                if on_status:
                    on_status(f"子智能体 [{self.name}] 调用 {tc.function.name}")
                result = await skills_module.async_call(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return messages[-1].get("content", "子智能体达到最大轮次限制")
