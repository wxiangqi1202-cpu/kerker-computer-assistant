"""
渲染层 —— Markdown 渲染 + ProgressTracker 联动 + spinner 控制

统一事件流处理：
- route: 路由决策通知
- thinking: 模型推理中
- tool/tool_exec: 工具调用开始
- tool_result: 工具调用结果
- text: 流式文本
- done: 完成

业务副作用（route learning、planner 管理）由调用方负责，
本模块仅返回渲染结果和状态，不直接操作 agents 或 route_learn。
"""

import sys
import asyncio
from rich.console import Console

from display.spinner import Spinner, THINKING_TIPS, GENERATING_TIPS
from display.timer import Timer
from display.md_render import print_markdown
from display import output as _out

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
    """渲染事件流，返回 (reply, assistant_msg, max_rounds_hit, new_messages, interrupted)。"""
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
    new_messages = []
    receiving_text = False
    max_rounds_hit = False
    route_decision = None
    _summarizing = False
    _text_chars = 0

    cancel_task = None

    async def _consume_stream():
        nonlocal reply, assistant_msg, new_messages, receiving_text, route_decision
        nonlocal _summarizing, _text_chars
        async for event in event_stream:
            if spinner.interrupted.is_set():
                break

            etype = event["type"]

            if etype == "route":
                route_decision = event.get("decision")
                if route_decision and route_decision.action == "plan":
                    spinner.update(tips=["正在规划任务..."])

            elif etype == "thinking":
                from core.progress import get_tracker as _gt4
                if not _gt4().has_plan:
                    spinner.update(tips=THINKING_TIPS)

            elif etype == "tool":
                from core.progress import get_tracker as _gt3
                if not _gt3().has_plan:
                    spinner.update(tips=_tool_tip(event.get("name", "")))
                recovery.accumulate_tool_call({"name": event.get("name", "")})

            elif etype == "tool_exec":
                from core.progress import get_tracker as _gt2
                if not _gt2().has_plan:
                    spinner.update(tips=_tool_tip(event.get("name", "")))

            elif etype == "tool_result":
                pass

            elif etype == "summarizing":
                _summarizing = True
                count = event.get("task_count", 0)
                if count:
                    spinner.update(tips=[f"整合 {count} 个子任务结果，等待模型响应..."])
                else:
                    spinner.update(tips=["等待模型生成最终回复..."])

            elif etype == "text":
                chunk = event.get("content", "")
                if not receiving_text:
                    receiving_text = True
                    spinner.update(tips=GENERATING_TIPS)
                if _summarizing:
                    _text_chars += len(chunk)
                    from core.progress import get_tracker as _gt
                    _gt().set_footer(f"模型输出中: 已生成 {_text_chars} 字...")
                recovery.accumulate_text(chunk)

            elif etype == "done":
                timer.stop()
                reply = event.get("content") or reply
                assistant_msg = event.get("assistant_msg")
                new_messages = event.get("new_messages") or []
                usage = event.get("usage")
                stats = _format_stats(usage, timer)
                if event.get("_max_rounds_hit"):
                    nonlocal max_rounds_hit
                    max_rounds_hit = True

                if taskboard:
                    from core.progress import get_tracker
                    tracker = get_tracker()
                    tracker.clear_footer()

                spinner.stop(final_message=stats)
                recovery.stop_accumulating()

                if reply:
                    print_markdown(reply)
                else:
                    _out.write_flush("\n")

    interrupted = False
    try:
        consume_task = asyncio.create_task(_consume_stream())
        cancel_task = asyncio.create_task(_watch_interrupt(spinner, consume_task))
        await consume_task

    finally:
        if cancel_task:
            cancel_task.cancel()
        from core.progress import get_tracker
        tracker = get_tracker()
        if spinner.interrupted.is_set():
            interrupted = True
            recovery.save_on_interrupt()
            if taskboard:
                taskboard.clear()
            spinner.stop()
            tracker.pause_on_interrupt()
            has_partial = recovery.has_state()
            hint = " — /resume 可续接" if has_partial else ""
            _out.write_flush(f"\n  \033[2m⏹ 已中断 (ESC){hint}\033[0m\n\n")
        else:
            recovery.clear()
            if taskboard:
                taskboard.clear()
            spinner.stop()

    return reply, assistant_msg, max_rounds_hit, new_messages, interrupted, route_decision


async def _watch_interrupt(spinner, target_task):
    try:
        while True:
            await asyncio.sleep(0.1)
            if spinner.interrupted.is_set():
                target_task.cancel()
                break
    except asyncio.CancelledError:
        pass
