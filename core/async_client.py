"""
异步 API 客户端 —— 基于 AsyncOpenAI
"""

import os
import asyncio
from openai import AsyncOpenAI, APIStatusError, APIConnectionError, APITimeoutError
from core import config
from core.credentials import load_api_key
import skills


_API_MAX_RETRIES = 3
_API_RETRY_BASE_DELAY = 1.0


async def _api_call_with_retry(client, kwargs):
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


def create_client():
    api_key = load_api_key()
    if not api_key:
        print("未配置 API Key，请运行 kerker 进行首次配置。")
        api_key = input("API Key: ").strip()
    base_url = config.get_model_base_url()
    return AsyncOpenAI(api_key=api_key, base_url=base_url)


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

    当 decision.clear_plan 为 True 时，主动清除旧 plan 状态。
    """
    from agents.router import route, RouteDecision
    from agents import get_all_agents, clear_plan
    from core.progress import get_tracker

    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return None, None

    last_user = user_msgs[-1].get("content", "")
    available = set(get_all_agents().keys())
    tracker = get_tracker()
    decision = route(last_user, available, context=tracker)

    if decision.clear_plan:
        clear_plan()

    if decision.action == RouteDecision.PLAN:
        if decision.reason == "继承上轮规划":
            plan_steps = tracker.get_step_names()
            if plan_steps:
                steps_preview = "、".join(plan_steps[:5])
                directive = (
                    f"[自动路由] 继续执行上轮规划（剩余步骤: {steps_preview}）。"
                    "严格按照规划的步骤顺序，逐个调用相应子智能体执行。"
                    "每次只调一个，等返回后再调下一个。全部完成后给出总结。"
                )
            else:
                directive = (
                    "[自动路由] 检测到多步骤任务。推荐调用 agent_planner 进行任务规划。"
                )
        elif decision.reason == "算子任务强制规划":
            directive = (
                "[自动路由] 检测到算子开发/调试任务。必须先调用 agent_planner 进行任务规划，"
                "然后严格按照规划步骤逐个调用相应子智能体执行（ascend_dev / ascend_debug）。"
                "不要跳过规划直接开发，不要一次性完成所有步骤。"
                "每完成一个步骤等返回后再执行下一个。"
            )
        else:
            directive = (
                "[自动路由] 检测到多步骤任务。推荐调用 agent_planner 进行任务规划。"
                "如果你选择不调 planner，也请逐个调用工具完成任务，每次只调一个工具，等返回后再调下一个。"
                "全部完成后再给出最终总结回复。"
            )
        return decision, [{"role": "system", "content": directive}]

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
    "web_summary": "读取网页",
    "web_search": "搜索",
    "web_search_and_read": "搜索并阅读",
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
    if not tool_name:
        return "处理中"
    if tool_name in _TOOL_FRIENDLY_NAMES:
        return _TOOL_FRIENDLY_NAMES[tool_name]
    if tool_name.startswith("agent_"):
        return tool_name[6:]
    return tool_name


def _sync_system_messages(messages, route_action=None):
    """
    同步 system 消息：角色切换后确保 messages 中的 system 消息是最新的。
    route_action: 路由决策，用于动态裁剪 directive（减少无关 token）。
    """
    from cli.commands import build_system_messages
    current_system = build_system_messages()

    if route_action:
        directives = config.get_directives_for_route(route_action)
        directive_contents = {d for d in directives}
        filtered_system = []
        for msg in current_system:
            content = msg["content"]
            if content in (config.TOOL_DIRECTIVE, config.EXPLORE_DIRECTIVE, config.AGENT_DIRECTIVE):
                if content in directive_contents:
                    filtered_system.append(msg)
            else:
                filtered_system.append(msg)
        current_system = filtered_system

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


async def send(client, messages):
    """
    异步发送消息并自动处理工具调用循环。
    通过 ProgressTracker 统一追踪所有工具和智能体执行进度。
    通过 MetricsCollector 记录性能指标。
    """
    from core.progress import get_tracker
    from core.metrics import get_metrics
    import time as _time

    tracker = get_tracker()
    metrics = get_metrics()
    metrics.start_turn(model=config.MODEL)

    _clean_route_messages(messages)

    _route_action = None
    if config.AUTO_ROUTE:
        decision, route_msgs = _try_auto_route(messages)
        if decision:
            _route_action = decision.action
            yield {"type": "route", "decision": decision}
        if route_msgs:
            for msg in route_msgs:
                messages.append(msg)

    _max_rounds = 20
    _round = 0
    _first_token_recorded = False
    _kwargs_cache = None
    while True:
        _round += 1
        if _round > _max_rounds:
            tracker.finish_all()
            metrics.end_turn(error="max_rounds_exceeded")
            yield {"type": "done", "content": "达到最大工具调用轮次限制，已停止。", "assistant_msg": {"role": "assistant", "content": "达到最大工具调用轮次限制，已停止。"}, "usage": None}
            break

        tracker.ensure_step_active()
        if _round == 1:
            _sync_system_messages(messages, route_action=_route_action)
        kwargs = _build_kwargs(messages)
        response = await _api_call_with_retry(client, kwargs)

        if config.STREAM:
            result = yield_result = None
            async for event in _handle_stream(response):
                if isinstance(event, dict) and event.get("_result"):
                    yield_result = event["_result"]
                else:
                    if not _first_token_recorded and isinstance(event, dict) and event.get("type") in ("text", "thinking"):
                        metrics.record_first_token()
                        _first_token_recorded = True
                    if isinstance(event, dict) and event.get("type") == "done" and event.get("usage"):
                        metrics.record_usage(event["usage"])
                    yield event
            result = yield_result
        else:
            result = None
            async for event in _handle_sync(response):
                if isinstance(event, dict) and event.get("_result"):
                    result = event["_result"]
                else:
                    if not _first_token_recorded and isinstance(event, dict) and event.get("type") in ("text", "thinking"):
                        metrics.record_first_token()
                        _first_token_recorded = True
                    if isinstance(event, dict) and event.get("type") == "done" and event.get("usage"):
                        metrics.record_usage(event["usage"])
                    yield event

        if not result or not result["tool_calls"]:
            tracker.finish_all()
            metrics.end_turn()
            break

        metrics.record_round()

        messages.append(result["assistant_msg"])

        tool_calls = result["tool_calls"]
        agent_calls = [tc for tc in tool_calls if tc["name"].startswith("agent_")]
        other_calls = [tc for tc in tool_calls if not tc["name"].startswith("agent_")]

        if len(agent_calls) > 1:
            for tc in agent_calls:
                agent_name = tc["name"].replace("agent_", "", 1)
                tracker.agent_start(agent_name)
                yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}

            async def _run_agent_call(tc):
                return await skills.async_call(tc["name"], tc["args"])

            agent_results = await asyncio.gather(
                *[_run_agent_call(tc) for tc in agent_calls],
                return_exceptions=True,
            )

            for tc, result in zip(agent_calls, agent_results):
                agent_name = tc["name"].replace("agent_", "", 1)
                if isinstance(result, Exception):
                    tool_result = f"[{agent_name}] 执行失败: {str(result)[:150]}"
                    tracker.agent_error(agent_name, error=tool_result[:100])
                else:
                    tool_result = result
                    if "执行失败" in tool_result:
                        tracker.agent_error(agent_name, error=tool_result[:100])
                    else:
                        tracker.agent_done(agent_name, summary=tool_result[:100] if tool_result else "")
                yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
        else:
            for tc in agent_calls:
                agent_name = tc["name"].replace("agent_", "", 1)
                tracker.agent_start(agent_name)
                yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
                tool_result = await skills.async_call(tc["name"], tc["args"])
                if "执行失败" in tool_result:
                    tracker.agent_error(agent_name, error=tool_result[:100])
                else:
                    tracker.agent_done(agent_name, summary=tool_result[:100] if tool_result else "")
                yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

        if other_calls and tracker.has_plan:
            tracker.advance_unbound_step()

        for tc in other_calls:
            display_name = _tool_display_name(tc["name"])
            tracker.tool_start(display_name)
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
            _tool_start = _time.time()
            tool_result = await skills.async_call(tc["name"], tc["args"])
            _tool_duration = (_time.time() - _tool_start) * 1000
            _tool_success = "执行出错" not in tool_result and "执行失败" not in tool_result
            metrics.record_tool_call(tc["name"], _tool_duration, success=_tool_success)
            tracker.tool_done(display_name)
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

        if other_calls and tracker.has_plan:
            tracker.complete_unbound_step()

        if tracker.needs_replan:
            import agents as _agents_mod
            _agents_mod._planner_used = False
            messages.append({
                "role": "system",
                "content": (
                    "[执行反馈] 多个步骤执行失败，当前规划可能不合理。"
                    "请重新调用 agent_planner 制定新的规划方案，"
                    "或者调整策略直接完成剩余任务。"
                ),
            })


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
