"""
渲染层 —— Markdown 渲染 + ProgressTracker 联动 + spinner 控制

统一事件流处理：
- route: 路由决策通知
- thinking: 模型推理中
- tool/tool_exec: 工具调用开始
- tool_result: 工具调用结果
- text: 流式文本
- done: 完成
"""

import sys
import asyncio
from rich.console import Console

from display.spinner import Spinner, THINKING_TIPS, GENERATING_TIPS
from display.timer import Timer
from display.md_render import print_markdown

_console = Console()


def _format_stats(usage, timer):
    parts = []
    if timer:
        parts.append(f"耗时 {timer.format()}")
    if usage:
        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)
        total = usage.get("total_tokens", 0)
        parts.append(f"输入 {prompt} + 输出 {completion} = {total} tokens")
    return " | ".join(parts) if parts else None


def _tool_tip(tool_name):
    from core.context import tool_display_name
    display = tool_display_name(tool_name)
    return [f"{display}..."]


async def render(event_stream, spinner=None, taskboard=None):
    if spinner is None:
        spinner = Spinner()

    from core.interrupt import get_recovery
    recovery = get_recovery()
    from core import config as _cfg
    recovery.start_accumulating(model=_cfg.MODEL)

    timer = Timer()
    timer.start()

    reply = ""
    assistant_msg = None
    receiving_text = False
    max_rounds_hit = False

    cancel_task = None

    async def _consume_stream():
        nonlocal reply, assistant_msg, receiving_text
        async for event in event_stream:
            if spinner.interrupted:
                break

            etype = event["type"]

            if etype == "route":
                decision = event.get("decision")
                if decision and decision.action == "plan":
                    spinner.update(tips=["正在规划任务..."])

            elif etype == "thinking":
                spinner.update(tips=THINKING_TIPS)

            elif etype == "tool":
                spinner.update(tips=_tool_tip(event.get("name", "")))
                recovery.accumulate_tool_call({"name": event.get("name", "")})

            elif etype == "tool_exec":
                spinner.update(tips=_tool_tip(event.get("name", "")))

            elif etype == "tool_result":
                pass

            elif etype == "text":
                if not receiving_text:
                    receiving_text = True
                    spinner.update(tips=GENERATING_TIPS)
                recovery.accumulate_text(event.get("content", ""))

            elif etype == "done":
                timer.stop()
                reply = event.get("content") or reply
                assistant_msg = event.get("assistant_msg")
                usage = event.get("usage")
                stats = _format_stats(usage, timer)
                if event.get("_max_rounds_hit"):
                    nonlocal max_rounds_hit
                    max_rounds_hit = True

                if taskboard:
                    from core.progress import get_tracker
                    tracker = get_tracker()
                    if tracker.is_finished and tracker.is_visible:
                        wait_start = asyncio.get_event_loop().time()
                        while asyncio.get_event_loop().time() - wait_start < 2.0:
                            if taskboard.is_finishing:
                                break
                            await asyncio.sleep(0.05)
                        while taskboard.is_finishing:
                            await asyncio.sleep(0.06)
                            if asyncio.get_event_loop().time() - wait_start > 3.0:
                                break

                spinner.stop(final_message=stats)
                recovery.stop_accumulating()

                if reply:
                    print_markdown(reply)
                else:
                    sys.stdout.write("\n")
                    sys.stdout.flush()

    try:
        consume_task = asyncio.ensure_future(_consume_stream())
        cancel_task = asyncio.ensure_future(_watch_interrupt(spinner, consume_task))
        await consume_task

    finally:
        if cancel_task:
            cancel_task.cancel()
        import agents
        from core.progress import get_tracker
        from core.route_learn import get_route_learner
        tracker = get_tracker()
        learner = get_route_learner()
        if spinner.interrupted:
            learner.record_outcome(success=False, interrupted=True)
            recovery.save_on_interrupt()
            if taskboard:
                taskboard.clear()
            spinner.stop()
            tracker.pause_on_interrupt()
            import agents as _agents_mod
            _agents_mod._planner_used = False
            has_partial = recovery.has_state()
            hint = " — /resume 可续接" if has_partial else ""
            sys.stdout.write(f"\n  \033[2m⏹ 已中断 (ESC){hint}\033[0m\n\n")
            sys.stdout.flush()
        else:
            learner.record_outcome(success=True, interrupted=False,
                                   replanned=tracker.needs_replan if tracker.has_plan else False)
            recovery.clear()

            has_pending_plan = (
                tracker.has_plan and
                any(s.status.value == "pending" for s in tracker.plan_steps)
            )

            if has_pending_plan:
                if taskboard:
                    taskboard.clear()
                spinner.stop()
                tracker.pause_on_interrupt()
                import agents as _agents_mod
                _agents_mod._planner_used = False
            else:
                if taskboard:
                    taskboard.clear()
                spinner.stop()
                agents.clear_plan()

    return reply, assistant_msg, max_rounds_hit


async def _watch_interrupt(spinner, target_task):
    try:
        while True:
            await asyncio.sleep(0.1)
            if spinner.interrupted:
                target_task.cancel()
                break
    except asyncio.CancelledError:
        pass
