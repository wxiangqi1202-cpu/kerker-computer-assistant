"""
异步 API 客户端 —— 基于 AsyncOpenAI
"""

import os
import asyncio
from openai import AsyncOpenAI
from core import config
from core.credentials import load_api_key
import skills


def create_client():
    api_key = load_api_key()
    if not api_key:
        print("未配置 API Key，请运行 kerker 进行首次配置。")
        api_key = input("API Key: ").strip()
    return AsyncOpenAI(api_key=api_key, base_url=config.BASE_URL)


def _build_kwargs(messages):
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

    tool_specs = skills.get_tool_specs()
    if tool_specs:
        kwargs["tools"] = tool_specs

    return kwargs


def _extract_usage(usage_obj):
    if not usage_obj:
        return None
    return {
        "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
    }


def _try_auto_route(messages):
    """
    检查最后一条 user 消息 + 对话上下文，判断是否需要自动注入路由指令。
    返回 (RouteDecision, 需要追加的消息列表) 或 (None, None)。
    """
    from agents.router import route, RouteDecision
    from agents import get_all_agents
    from agents.context import get_context

    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return None, None

    last_user = user_msgs[-1].get("content", "")
    available = set(get_all_agents().keys())
    ctx = get_context()
    decision = route(last_user, available, context=ctx)

    if decision.action == RouteDecision.PLAN:
        return decision, [{
            "role": "system",
            "content": (
                "[自动路由] 检测到复杂任务，请先调用 agent_planner 进行任务规划，"
                "然后严格按照规划的步骤顺序，逐个调用相应子智能体执行。"
                "重要：每次只调用一个子智能体，等它返回结果后再调用下一个，不要并行调用多个。"
                "全部步骤完成后再给出最终总结回复。"
            ),
        }]

    if decision.action == RouteDecision.SINGLE_AGENT and decision.agent_name:
        return decision, [{
            "role": "system",
            "content": (
                f"[自动路由] 检测到该任务适合由 {decision.agent_name} 处理，"
                f"请调用 agent_{decision.agent_name} 执行此任务。"
            ),
        }]

    return decision, None


def _advance_next_step():
    """主模型直接调用基础 skill 时，推进下一个 pending 步骤为 running"""
    from agents.context import get_context
    from agents import _sync_taskboard
    ctx = get_context()
    if not ctx.has_plan:
        return
    step = ctx.advance_step()
    if step:
        _sync_taskboard()


def _complete_current_step():
    """基础 skill 执行完毕后，将当前 running 步骤标记为 done"""
    from agents.context import get_context
    from agents import _sync_taskboard
    ctx = get_context()
    if not ctx.has_plan:
        return
    for s in ctx.plan_steps:
        if s.status == "running":
            ctx.complete_step(s.step, summary="已完成")
            _sync_taskboard()
            return


def _complete_remaining_steps():
    """主模型最终输出文本前，将所有剩余 pending/running 步骤标记为 done"""
    from agents.context import get_context
    from agents import _sync_taskboard
    ctx = get_context()
    if not ctx.has_plan:
        return
    changed = False
    for s in ctx.plan_steps:
        if s.status in ("pending", "running"):
            ctx.complete_step(s.step, summary="已完成")
            changed = True
    if changed:
        _sync_taskboard()


async def send(client, messages):
    """
    异步发送消息并自动处理工具调用循环。
    支持自动路由 + 自动推进任务板步骤。
    """
    if config.AUTO_ROUTE:
        decision, route_msgs = _try_auto_route(messages)
        if decision:
            yield {"type": "route", "decision": decision}
        if route_msgs:
            for msg in route_msgs:
                messages.append(msg)
    while True:
        kwargs = _build_kwargs(messages)
        response = await client.chat.completions.create(**kwargs)

        if config.STREAM:
            result = yield_result = None
            async for event in _handle_stream(response):
                if isinstance(event, dict) and event.get("_result"):
                    yield_result = event["_result"]
                else:
                    yield event
            result = yield_result
        else:
            result = None
            async for event in _handle_sync(response):
                if isinstance(event, dict) and event.get("_result"):
                    result = event["_result"]
                else:
                    yield event

        if not result or not result["tool_calls"]:
            _complete_remaining_steps()
            break

        messages.append(result["assistant_msg"])

        tool_calls = result["tool_calls"]

        for tc in tool_calls:
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}

        agent_calls = [tc for tc in tool_calls if tc["name"].startswith("agent_")]
        other_calls = [tc for tc in tool_calls if not tc["name"].startswith("agent_")]

        for tc in agent_calls:
            tool_result = await skills.async_call(tc["name"], tc["args"])
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

        if other_calls:
            _advance_next_step()

        for tc in other_calls:
            tool_result = await skills.async_call(tc["name"], tc["args"])
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

        if other_calls:
            _complete_current_step()


async def _handle_stream(response):
    phase = "init"
    reply = ""
    reasoning = ""
    tool_calls_data = {}
    usage = None

    async for chunk in response:
        if hasattr(chunk, "usage") and chunk.usage:
            usage = _extract_usage(chunk.usage)

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


async def _handle_sync(response):
    msg = response.choices[0].message
    usage = _extract_usage(getattr(response, "usage", None))

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
