"""
单轮执行循环 —— 从用户消息到完整回复的核心流程

职责：
- 路由判定 + 系统消息注入
- API 调用循环（最多 _MAX_ROUNDS 轮）
- 工具分发（agent 并行 / 普通串行）
- Metrics 记录、Prefetch 提示、Replan 检测

调用链：
  loop.py → turn.send() → client.api_call_with_retry()
                         → context.trim/compress
                         → prompt.sync_system_messages
"""

import asyncio
from core import config
from core.client import api_call_with_retry, build_kwargs, handle_stream, handle_sync
from core.prompt import sync_system_messages, clean_route_messages
from core.context import (
    trim_tool_result, compress_tool_results, should_compress,
    wrap_untrusted, is_web_tool, tool_display_name,
)
import skills

_MAX_ROUNDS = 40


def _try_auto_route(messages):
    """
    最小路由：只在确定性场景注入系统消息。
    PASS_THROUGH 不注入任何路由指令，完全信任 LLM 自主判断。
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
        if decision.reason == "算子任务强制规划":
            directive = (
                "[自动路由] 检测到算子开发/调试任务。必须先调用 agent_planner 进行任务规划，"
                "然后严格按照规划步骤逐个调用相应子智能体执行（ascend_dev / ascend_debug）。"
                "不要跳过规划直接开发，不要一次性完成所有步骤。"
                "每完成一个步骤等返回后再执行下一个。"
            )
        elif decision.reason == "继承上轮规划":
            context_prompt = tracker.build_context_prompt()
            plan_steps = tracker.plan_steps
            if plan_steps:
                step_lines = []
                for i, step in enumerate(plan_steps, 1):
                    agent_hint = f"agent_{step.agent}" if step.agent else "主模型"
                    step_lines.append(f"  {i}. {step.name} → 调用 {agent_hint}")
                plan_detail = "\n".join(step_lines)
                directive = (
                    f"[自动路由] 继续执行上轮规划。以下是完整规划，请严格按顺序执行:\n"
                    f"{plan_detail}\n\n"
                    f"请立即调用第一个待执行步骤对应的子智能体。"
                    f"每次只调一个，等返回后再调下一个。全部完成后给出总结。"
                )
                if context_prompt:
                    directive += f"\n\n{context_prompt}"
            else:
                directive = "[自动路由] 用户要求继续，请根据上下文继续执行任务。"
        else:
            directive = "[自动路由] 检测到需要规划的任务。请调用 agent_planner 进行任务规划。"
        return decision, [{"role": "system", "content": directive}]

    return decision, None


async def _dispatch_agent_calls(agent_calls, messages, tracker):
    """分发 agent 调用（多个并行，单个串行）"""
    results = []

    if len(agent_calls) > 1:
        for tc in agent_calls:
            tracker.agent_start(tc["name"].replace("agent_", "", 1))

        async def _run(tc):
            return await skills.async_call(tc["name"], tc["args"])

        raw_results = await asyncio.gather(
            *[_run(tc) for tc in agent_calls],
            return_exceptions=True,
        )

        for tc, raw in zip(agent_calls, raw_results):
            agent_name = tc["name"].replace("agent_", "", 1)
            if isinstance(raw, Exception):
                tool_result = f"[{agent_name}] 执行失败: {str(raw)[:150]}"
                tracker.agent_error(agent_name, error=tool_result[:100])
            else:
                tool_result = trim_tool_result(raw)
                if "执行失败" in tool_result:
                    tracker.agent_error(agent_name, error=tool_result[:100])
                else:
                    tracker.agent_done(agent_name, summary=tool_result[:100] if tool_result else "")
            results.append((tc, tool_result))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
    else:
        for tc in agent_calls:
            agent_name = tc["name"].replace("agent_", "", 1)
            tracker.agent_start(agent_name)
            tool_result = await skills.async_call(tc["name"], tc["args"])
            tool_result = trim_tool_result(tool_result)
            if "执行失败" in tool_result:
                tracker.agent_error(agent_name, error=tool_result[:100])
            else:
                tracker.agent_done(agent_name, summary=tool_result[:100] if tool_result else "")
            results.append((tc, tool_result))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

    return results


async def _dispatch_tool_calls(other_calls, messages, tracker, metrics):
    """分发普通工具调用（串行）"""
    import time as _time
    results = []

    if other_calls and tracker.has_plan:
        tracker.advance_unbound_step()

    for tc in other_calls:
        display_name = tool_display_name(tc["name"])
        tracker.tool_start(display_name)
        _tool_start = _time.time()
        tool_result = await skills.async_call(tc["name"], tc["args"])
        tool_result = trim_tool_result(tool_result)
        if is_web_tool(tc["name"]):
            tool_result = wrap_untrusted(tool_result)
        _tool_duration = (_time.time() - _tool_start) * 1000
        _tool_success = "执行出错" not in tool_result and "执行失败" not in tool_result
        metrics.record_tool_call(tc["name"], _tool_duration, success=_tool_success)
        tracker.tool_done(display_name)
        results.append((tc, tool_result))
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

    if other_calls and tracker.has_plan:
        tracker.complete_unbound_step()

    return results


def _post_round_inject(messages, tracker, agent_calls):
    """每轮工具调用后的注入：replan 检测 + prefetch 提示"""
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
    elif agent_calls and tracker.has_plan:
        next_step, next_agent = tracker.peek_next_pending()
        if next_step and next_agent:
            messages.append({
                "role": "system",
                "content": (
                    f"[执行提示] 上一步已完成。下一步: \"{next_step}\"，"
                    f"请立即调用 agent_{next_agent} 执行，不要停下来询问用户。"
                ),
            })


async def send(client, messages):
    """
    单轮执行循环：从用户消息到完整回复。

    流程：
    1. 清理旧路由消息 → 路由判定 → 注入路由指令
    2. while 循环：同步 prompt → 构建参数 → API 调用 → 解析响应
    3. 有工具调用：分发执行 → 记录结果 → 注入提示 → 继续循环
    4. 无工具调用：结束
    """
    from core.progress import get_tracker
    from core.metrics import get_metrics

    tracker = get_tracker()
    metrics = get_metrics()
    metrics.start_turn(model=config.MODEL)

    clean_route_messages(messages)

    _route_action = None
    if config.AUTO_ROUTE:
        decision, route_msgs = _try_auto_route(messages)
        if decision:
            _route_action = decision.action
            yield {"type": "route", "decision": decision}
        if route_msgs:
            for msg in route_msgs:
                messages.append(msg)

    _round = 0
    _first_token_recorded = False
    while True:
        _round += 1
        if _round > _MAX_ROUNDS:
            tracker.finish_all()
            metrics.end_turn(error="max_rounds_exceeded")
            yield {
                "type": "done",
                "content": "达到最大工具调用轮次限制，已停止。",
                "assistant_msg": {"role": "assistant", "content": "达到最大工具调用轮次限制，已停止。"},
                "usage": None,
                "_max_rounds_hit": True,
            }
            break

        tracker.ensure_step_active()
        if _round == 1:
            sync_system_messages(messages, route_action=_route_action)
        if should_compress(_round):
            compress_tool_results(messages)

        _last_user_input = None
        if _round == 1:
            user_msgs = [m for m in messages if m.get("role") == "user"]
            if user_msgs:
                _last_user_input = user_msgs[-1].get("content", "")

        kwargs = build_kwargs(messages,
                              route_action=_route_action if _round == 1 else "pass_through",
                              user_input=_last_user_input)
        response = await api_call_with_retry(client, kwargs)

        if config.STREAM:
            result = yield_result = None
            async for event in handle_stream(response):
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
            async for event in handle_sync(response):
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

        for tc in agent_calls:
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
        agent_results = await _dispatch_agent_calls(agent_calls, messages, tracker)
        for tc, tool_result in agent_results:
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}

        for tc in other_calls:
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
        tool_results = await _dispatch_tool_calls(other_calls, messages, tracker, metrics)
        for tc, tool_result in tool_results:
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}

        _post_round_inject(messages, tracker, agent_calls)
