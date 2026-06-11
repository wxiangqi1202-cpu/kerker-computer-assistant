"""
渲染层 —— Markdown 渲染 + 任务面板 + spinner 联动
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
    from core.async_client import _tool_display_name
    display = _tool_display_name(tool_name)
    return [f"{display}..."]


async def render(event_stream, spinner=None, taskboard=None):
    if spinner is None:
        spinner = Spinner()

    timer = Timer()
    timer.start()

    reply = ""
    assistant_msg = None
    receiving_text = False

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
                elif decision and decision.action == "single_agent" and decision.agent_name:
                    from core.async_client import _tool_display_name
                    name = _tool_display_name(f"agent_{decision.agent_name}")
                    spinner.update(tips=[f"{name}..."])

            elif etype == "thinking":
                spinner.update(tips=THINKING_TIPS)

            elif etype == "tool":
                spinner.update(tips=_tool_tip(event.get("name", "")))

            elif etype == "tool_exec":
                spinner.update(tips=_tool_tip(event.get("name", "")))

            elif etype == "tool_result":
                pass

            elif etype == "text":
                if not receiving_text:
                    receiving_text = True
                    spinner.update(tips=GENERATING_TIPS)

            elif etype == "done":
                timer.stop()
                reply = event.get("content") or reply
                assistant_msg = event.get("assistant_msg")
                usage = event.get("usage")
                stats = _format_stats(usage, timer)

                if taskboard and taskboard.is_finishing:
                    while taskboard._visible:
                        await asyncio.sleep(0.08)

                spinner.stop(final_message=stats)

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
        if spinner.interrupted:
            if taskboard:
                taskboard.clear()
            spinner.stop()
            sys.stdout.write(f"\n  \033[2m⏹ 已中断 (ESC)\033[0m\n\n")
            sys.stdout.flush()
        else:
            if taskboard:
                taskboard.clear()
            spinner.stop()
            agents.clear_plan()

    return reply, assistant_msg


async def _watch_interrupt(spinner, target_task):
    try:
        while True:
            await asyncio.sleep(0.1)
            if spinner.interrupted:
                target_task.cancel()
                break
    except asyncio.CancelledError:
        pass
