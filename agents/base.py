"""
SubAgent 基类 —— 所有子智能体继承此类
"""

import os
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

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            api_key = load_api_key()
            model = self.model or config.MODEL
            base_url = config.MODELS.get(model, {}).get("base_url", config.BASE_URL)
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        return self._client

    def _get_tools(self):
        if self.allowed_skills is None:
            return []
        all_specs = skills_module.get_all_specs()
        return [s for s in all_specs if s["function"]["name"] in self.allowed_skills]

    async def run(self, task, on_status=None):
        """
        执行子任务。
        on_status: 可选回调 on_status(text)，用于向外部汇报进度。
        返回结果字符串。
        """
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
                    on_status(f"子智能体 [{self.name}] 调用技能 {tc.function.name}")
                result = await skills_module.async_call(tc.function.name, tc.function.arguments)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

        return messages[-1].get("content", "子智能体达到最大轮次限制")
