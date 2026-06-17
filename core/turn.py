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
import json
from core import config
from core.client import api_call_with_retry, build_kwargs, handle_stream, handle_sync
from core.prompt import sync_system_messages, clean_route_messages, PREFIX_AUTO_ROUTE, PREFIX_EXEC_HINT, PREFIX_EXEC_FEEDBACK
from core.context import (
    trim_tool_result, compress_tool_results, should_compress,
    wrap_untrusted, is_web_tool, tool_display_name,
    _AGENT_RESULT_MAX_CHARS,
)
from core import tool_registry
from core.tool_registry import is_tool_error

_MAX_ROUNDS = 40


def _can_dispatch_directly(tracker):
    """检查是否可以跳过主 LLM 逐步调度，由框架直接分发。
    条件：处于 PLAN_MODE 且所有 pending 步骤都有 agent 绑定。
    """
    if not tracker.has_plan:
        return False
    steps = tracker.plan_steps
    for s in steps:
        if s.status.value == "pending" and not s.agent:
            return False
    return True


def _try_auto_route(messages):
    """
    最小路由：只在确定性场景注入系统消息。
    PASS_THROUGH 不注入任何路由指令，完全信任 LLM 自主判断。
    """
    from agents.router import route, RouteDecision
    from agents import clear_plan
    from core.progress import get_tracker

    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return None, None

    last_user = user_msgs[-1].get("content", "")
    tracker = get_tracker()
    decision = route(last_user, context=tracker)

    if decision.clear_plan:
        clear_plan()

    if decision.action == RouteDecision.PLAN:
        if decision.reason == "算子任务强制规划":
            directive = (
                f"{PREFIX_AUTO_ROUTE} 检测到算子开发/调试任务。必须先调用 agent_planner 进行任务规划，"
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
                    f"{PREFIX_AUTO_ROUTE} 继续执行上轮规划。以下是完整规划，请严格按顺序执行:\n"
                    f"{plan_detail}\n\n"
                    f"请立即调用第一个待执行步骤对应的子智能体。"
                    f"每次只调一个，等返回后再调下一个。全部完成后给出总结。"
                )
                if context_prompt:
                    directive += f"\n\n{context_prompt}"
            else:
                directive = f"{PREFIX_AUTO_ROUTE} 用户要求继续，请根据上下文继续执行任务。"
        else:
            directive = f"{PREFIX_AUTO_ROUTE} 检测到需要规划的任务。请调用 agent_planner 进行任务规划。"
        return decision, [{"role": "system", "content": directive}]

    return decision, None


async def _dispatch_agent_calls(agent_calls, messages, tracker, metrics):
    """分发 agent 调用（多个并行，单个串行）"""
    import time as _time
    results = []

    if len(agent_calls) > 1:
        for tc in agent_calls:
            tracker.agent_start(tc["name"].replace("agent_", "", 1))

        async def _run(tc):
            return await tool_registry.async_call(tc["name"], tc["args"])

        _start = _time.time()
        raw_results = await asyncio.gather(
            *[_run(tc) for tc in agent_calls],
            return_exceptions=True,
        )
        _avg_ms = (_time.time() - _start) * 1000 / max(len(agent_calls), 1)

        for tc, raw in zip(agent_calls, raw_results):
            agent_name = tc["name"].replace("agent_", "", 1)
            if isinstance(raw, Exception):
                tool_result = f"[{agent_name}] 执行失败: {str(raw)[:150]}"
                tracker.agent_error(agent_name, error=tool_result[:100])
                metrics.record_agent_call(tc["name"], _avg_ms, success=False)
            else:
                tool_result = trim_tool_result(raw, max_chars=_AGENT_RESULT_MAX_CHARS)
                if is_tool_error(tool_result):
                    tracker.agent_error(agent_name, error=tool_result[:100])
                    metrics.record_agent_call(tc["name"], _avg_ms, success=False)
                else:
                    tracker.agent_done(agent_name, summary=tool_result[:100] if tool_result else "")
                    metrics.record_agent_call(tc["name"], _avg_ms, success=True)
            results.append((tc, tool_result))
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
    else:
        for tc in agent_calls:
            agent_name = tc["name"].replace("agent_", "", 1)
            tracker.agent_start(agent_name)
            _start = _time.time()
            tool_result = await tool_registry.async_call(tc["name"], tc["args"])
            _duration_ms = (_time.time() - _start) * 1000
            tool_result = trim_tool_result(tool_result, max_chars=_AGENT_RESULT_MAX_CHARS)
            if is_tool_error(tool_result):
                tracker.agent_error(agent_name, error=tool_result[:100])
                metrics.record_agent_call(tc["name"], _duration_ms, success=False)
            else:
                tracker.agent_done(agent_name, summary=tool_result[:100] if tool_result else "")
                metrics.record_agent_call(tc["name"], _duration_ms, success=True)
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
        tracker.add_sub_activity("", display_name)
        _tool_start = _time.time()
        tool_result = await tool_registry.async_call(tc["name"], tc["args"])
        tool_result = trim_tool_result(tool_result)
        if is_web_tool(tc["name"]):
            tool_result = wrap_untrusted(tool_result)
        _tool_duration = (_time.time() - _tool_start) * 1000
        _tool_success = not is_tool_error(tool_result)
        metrics.record_tool_call(tc["name"], _tool_duration, success=_tool_success)
        tracker.tool_done(display_name)
        results.append((tc, tool_result))
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})

    if other_calls and tracker.has_plan:
        tracker.complete_unbound_step()

    return results


async def _dispatch_plan_steps(tracker, metrics, event_callback):
    """框架层直接分发 plan 步骤（拓扑序分层并行）。
    跳过主 LLM 的逐步调度，直接按 planner 的依赖图执行。

    返回 [{step_name, agent, result}, ...] 全部步骤结果。
    event_callback: async callable，用于 yield 事件给调用方。
    """
    import time as _time
    import json as _json

    steps = tracker.plan_steps
    if not steps:
        return []

    step_count = len(steps)
    results = [None] * step_count
    done_set = set()

    while len(done_set) < step_count:
        ready = []
        for idx, step in enumerate(steps):
            if idx in done_set:
                continue
            if step.status.value != "pending":
                if step.status.value in ("done", "error"):
                    done_set.add(idx)
                continue
            if all(d in done_set for d in step.deps):
                ready.append((idx, step))

        if not ready:
            break

        for idx, step in ready:
            tracker.agent_start(step.agent)
            await event_callback({"type": "tool_exec", "name": f"agent_{step.agent}", "args": ""})

        async def _run_step(idx, step):
            task_arg = _json.dumps({"task": step.name}, ensure_ascii=False)
            _start = _time.time()
            raw = await tool_registry.async_call(f"agent_{step.agent}", task_arg)
            _dur = (_time.time() - _start) * 1000
            result_text = trim_tool_result(raw, max_chars=_AGENT_RESULT_MAX_CHARS)
            if is_tool_error(result_text):
                tracker.agent_error(step.agent, error=result_text[:100])
                metrics.record_agent_call(f"agent_{step.agent}", _dur, success=False)
            else:
                tracker.agent_done(step.agent, summary=result_text[:100] if result_text else "")
                metrics.record_agent_call(f"agent_{step.agent}", _dur, success=True)
            return idx, step, result_text

        if len(ready) > 1:
            batch_results = await asyncio.gather(
                *[_run_step(idx, step) for idx, step in ready],
                return_exceptions=True,
            )
            for br in batch_results:
                if isinstance(br, Exception):
                    continue
                idx, step, result_text = br
                results[idx] = {"step_name": step.name, "agent": step.agent, "result": result_text}
                done_set.add(idx)
                await event_callback({"type": "tool_result", "name": f"agent_{step.agent}", "result": result_text})
        else:
            idx, step = ready[0]
            _, _, result_text = await _run_step(idx, step)
            results[idx] = {"step_name": step.name, "agent": step.agent, "result": result_text}
            done_set.add(idx)
            await event_callback({"type": "tool_result", "name": f"agent_{step.agent}", "result": result_text})

        metrics.record_round()

    return [r for r in results if r is not None]


def _post_round_inject(messages, tracker, agent_calls, other_calls):
    """每轮工具调用后的注入：隐式完成检测 + replan 检测 + prefetch 提示"""
    all_tool_names = [tc["name"] for tc in agent_calls] + [tc["name"] for tc in other_calls]
    tracker.check_implicit_completion(all_tool_names)

    if tracker.needs_replan:
        import agents as _agents_mod
        _agents_mod.reset_planner()
        messages.append({
            "role": "system",
            "content": (
                f"{PREFIX_EXEC_FEEDBACK} 多个步骤执行失败，当前规划可能不合理。"
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
                    f"{PREFIX_EXEC_HINT} 上一步已完成。下一步: \"{next_step}\"，"
                    f"请立即调用 agent_{next_agent} 执行，不要停下来询问用户。"
                ),
            })


async def send(client, messages):
    """
    单轮执行循环：从用户消息到完整回复。

    设计：在 messages 的副本上操作，不修改调用方的原始列表。
    通过 done 事件的 new_messages 字段返回本轮新增的会话消息，
    由调用方决定是否 apply。中断/出错时原始 messages 不受影响。

    流程：
    1. 清理旧路由消息 → 复制 → 路由判定 → 注入路由指令
    2. while 循环：同步 prompt → 构建参数 → API 调用 → 解析响应
    3. 有工具调用：分发执行 → 记录结果 → 注入提示 → 继续循环
    4. 无工具调用：收集 delta → 结束
    """
    from core.progress import get_tracker
    from core.metrics import get_metrics

    tracker = get_tracker()
    metrics = get_metrics()
    metrics.start_turn(model=config.MODEL)

    clean_route_messages(messages)

    working = list(messages)
    baseline = len([m for m in working if m["role"] != "system"])

    _route_action = None
    if config.AUTO_ROUTE:
        decision, route_msgs = _try_auto_route(working)
        if decision:
            _route_action = decision.action
            yield {"type": "route", "decision": decision}
        if route_msgs:
            for msg in route_msgs:
                working.append(msg)

    _round = 0
    _first_token_recorded = False
    while True:
        _round += 1
        if _round > _MAX_ROUNDS:
            tracker.finish_all()
            metrics.end_turn(error="max_rounds_exceeded")
            non_sys = [m for m in working if m["role"] != "system"]
            yield {
                "type": "done",
                "content": "达到最大工具调用轮次限制，已停止。",
                "assistant_msg": {"role": "assistant", "content": "达到最大工具调用轮次限制，已停止。"},
                "usage": None,
                "new_messages": non_sys[baseline:],
                "_max_rounds_hit": True,
            }
            break

        tracker.ensure_step_active()
        if _round == 1:
            sync_system_messages(working, route_action=_route_action)
        if should_compress(_round):
            compress_tool_results(working)

        _last_user_input = None
        if _round == 1:
            user_msgs = [m for m in working if m.get("role") == "user"]
            if user_msgs:
                _last_user_input = user_msgs[-1].get("content", "")

        tool_specs = tool_registry.get_filtered_tool_specs(
            role_name=config.CURRENT_ROLE,
            user_input=_last_user_input,
        )
        kwargs = build_kwargs(working, tool_specs=tool_specs)
        response = await api_call_with_retry(client, kwargs)

        handler = handle_stream(response) if config.STREAM else handle_sync(response)
        result = yield_result = None
        _buffered_done = None
        async for event in handler:
            if isinstance(event, dict) and event.get("_result"):
                yield_result = event["_result"]
            else:
                if not _first_token_recorded and isinstance(event, dict) and event.get("type") in ("text", "thinking"):
                    metrics.record_first_token()
                    _first_token_recorded = True
                if isinstance(event, dict) and event.get("type") == "done":
                    if event.get("usage"):
                        metrics.record_usage(event["usage"])
                    _buffered_done = event
                else:
                    yield event
        result = yield_result

        if not result or not result["tool_calls"]:
            tracker.finish_all()
            metrics.end_turn()
            if _buffered_done:
                non_sys = [m for m in working if m["role"] != "system"]
                _buffered_done["new_messages"] = non_sys[baseline:]
                yield _buffered_done
            break

        metrics.record_round()
        working.append(result["assistant_msg"])

        tool_calls = result["tool_calls"]
        agent_calls = [tc for tc in tool_calls if tc["name"].startswith("agent_")]
        other_calls = [tc for tc in tool_calls if not tc["name"].startswith("agent_")]

        for tc in agent_calls:
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
        agent_results = await _dispatch_agent_calls(agent_calls, working, tracker, metrics)
        for tc, tool_result in agent_results:
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}

        if agent_calls and _can_dispatch_directly(tracker):
            _events_to_yield = []

            async def _yield_event(ev):
                _events_to_yield.append(ev)

            plan_results = await _dispatch_plan_steps(tracker, metrics, _yield_event)
            for ev in _events_to_yield:
                yield ev

            if plan_results:
                for pr in plan_results:
                    working.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": f"direct_{pr['agent']}",
                            "type": "function",
                            "function": {
                                "name": f"agent_{pr['agent']}",
                                "arguments": json.dumps({"task": pr["step_name"]}, ensure_ascii=False),
                            },
                        }],
                    })
                    working.append({
                        "role": "tool",
                        "tool_call_id": f"direct_{pr['agent']}",
                        "content": pr["result"] or "",
                    })

                count = tracker.total_steps
                tracker.set_footer(f"整合 {count} 个子任务结果，等待模型响应...")
                yield {"type": "summarizing", "task_count": count}
                continue

        for tc in other_calls:
            yield {"type": "tool_exec", "name": tc["name"], "args": tc["args"]}
        tool_results = await _dispatch_tool_calls(other_calls, working, tracker, metrics)
        for tc, tool_result in tool_results:
            yield {"type": "tool_result", "name": tc["name"], "result": tool_result}

        _post_round_inject(working, tracker, agent_calls, other_calls)

        if tracker.has_plan and tracker.done_count >= tracker.total_steps:
            count = tracker.total_steps
            tracker.set_footer(f"整合 {count} 个子任务结果，等待模型响应...")
            yield {"type": "summarizing", "task_count": count}
