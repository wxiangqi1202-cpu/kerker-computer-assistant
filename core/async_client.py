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
                "[自动路由] 检测到多步骤任务。推荐调用 agent_planner 进行任务规划。"
                "如果你选择不调 planner，也请逐个调用工具完成任务，每次只调一个工具，等返回后再调下一个。"
                "全部完成后再给出最终总结回复。"
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


_TOOL_FRIENDLY_NAMES = {
    "distill_role": "提取角色特征",
    "save_distilled_role": "创建角色",
    "web_summary": "获取网页内容",
    "run_shell": "执行命令",
    "read_file": "读取文件",
    "write_file": "写入文件",
    "get_current_time": "获取时间",
    "get_weather": "查询天气",
    "get_location": "获取位置",
    "calculate": "计算",
    "npu_info": "查询 NPU 状态",
    "ascend_build": "编译算子",
    "ascend_run": "运行算子",
    "agent_planner": "任务规划",
    "agent_researcher": "搜索调研",
    "agent_code_reviewer": "代码审查",
    "agent_ascend_dev": "算子开发",
    "agent_ascend_debug": "算子调试",
}


def _tool_display_name(tool_name):
    """工具名 → 用户友好的显示名"""
    if tool_name in _TOOL_FRIENDLY_NAMES:
        return _TOOL_FRIENDLY_NAMES[tool_name]
    if tool_name.startswith("agent_"):
        return tool_name[6:]
    return tool_name


def _sync_system_messages(messages):
    """同步 system 消息：角色切换后确保 messages 中的 system 消息是最新的"""
    from cli.commands import build_system_messages
    current_system = build_system_messages()
    current_contents = {m["content"] for m in current_system}

    old_system = [m for m in messages if m["role"] == "system"]
    old_role_contents = set()
    env_msgs = []
    for m in old_system:
        content = m["content"]
        if content.startswith("[自动路由]") or content.startswith("[已有角色]"):
            continue
        if any(content.startswith(p) for p in ("[当前系统可用工具]", "[以下是更早", "[用户记忆]", "[近期对话摘要]")):
            env_msgs.append(m)
        else:
            old_role_contents.add(content)

    if old_role_contents != current_contents:
        non_system = [m for m in messages if m["role"] != "system"]
        messages.clear()
        messages.extend(current_system)
        messages.extend(env_msgs)
        messages.extend(non_system)

    role_list = ", ".join(config.ROLES.keys())
    role_info = (
        f"[已有角色] 当前: {config.CURRENT_ROLE}。可切换: {role_list}。"
        "用户说'切换到xxx'时，应先调 switch_role 切换已有角色，不要直接创建新角色。"
    )
    existing = [i for i, m in enumerate(messages) if m.get("role") == "system" and m.get("content", "").startswith("[已有角色]")]
    if existing:
        messages[existing[0]]["content"] = role_info
    else:
        system_end = 0
        for i, m in enumerate(messages):
            if m["role"] == "system":
                system_end = i + 1
        messages.insert(system_end, {"role": "system", "content": role_info})


def _clean_route_messages(messages):
    """清理上一轮残留的 [自动路由] 消息，避免累积"""
    i = 0
    while i < len(messages):
        if messages[i].get("role") == "system" and messages[i].get("content", "").startswith("[自动路由]"):
            messages.pop(i)
        else:
            i += 1


def _track_tool_start(tool_name):
    """工具开始执行时，在 taskboard 上显示为 running（第二个工具起才显示）"""
    from agents import _active_taskboard
    if not _active_taskboard:
        return
    display = _tool_display_name(tool_name)
    _active_taskboard.add_or_update(display, "running")


def _track_tool_done(tool_name):
    """工具执行完毕，标记为 done"""
    from agents import _active_taskboard
    if _active_taskboard:
        display = _tool_display_name(tool_name)
        _active_taskboard.add_or_update(display, "done")


def _advance_next_step():
    """有 plan 时推进下一个 pending 步骤"""
    from agents.context import get_context
    from agents import _sync_taskboard
    ctx = get_context()
    if not ctx.has_plan:
        return
    step = ctx.advance_step()
    if step:
        _sync_taskboard()


def _complete_current_step():
    """有 plan 时将当前 running 步骤标记为 done"""
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
    """最终输出前，将所有剩余 pending/running 步骤标记为 done"""
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
    每次调用前清理上一轮残留的路由指令。
    """
    _clean_route_messages(messages)

    if config.AUTO_ROUTE:
        decision, route_msgs = _try_auto_route(messages)
        if decision:
            yield {"type": "route", "decision": decision}
        if route_msgs:
            for msg in route_msgs:
                messages.append(msg)

    _other_tool_count = 0
    _pending_first_tool = None
    while True:
        _sync_system_messages(messages)
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

        from agents.context import get_context as _get_ctx

        agent_calls = [tc for tc in tool_calls if tc["name"].startswith("agent_")]
        other_calls = [tc for tc in tool_calls if not tc["name"].startswith("agent_")]

        for tc in agent_calls:
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
            tool_result = await skills.async_call(tc["name"], tc["args"])
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

        for tc in other_calls:
            _other_tool_count += 1
            has_plan = _get_ctx().has_plan
            if has_plan:
                _advance_next_step()

            if _other_tool_count == 1 and not has_plan:
                _pending_first_tool = tc["name"]
            elif _other_tool_count == 2 and _pending_first_tool and not has_plan:
                _track_tool_done(_pending_first_tool)
                _pending_first_tool = None
                _track_tool_start(tc["name"])
            elif _other_tool_count > 2 and not has_plan:
                _track_tool_start(tc["name"])

            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
            tool_result = await skills.async_call(tc["name"], tc["args"])

            if _other_tool_count >= 2 and not has_plan:
                _track_tool_done(tc["name"])
            if has_plan:
                _complete_current_step()

            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})


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
