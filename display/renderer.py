"""
渲染层 —— Markdown 渲染 + 自适应显示 + 任务面板
spinner 全程运行直到回复完成，然后一次性 Markdown 渲染。
短回复（≤3行）直接平铺，长回复用左侧竖线包裹。
"""

import sys
import asyncio
from rich.console import Console
from rich.markdown import Markdown

from display.spinner import (
    Spinner,
    THINKING_TIPS, GENERATING_TIPS, TOOL_TIPS, AGENT_TIPS,
)
from display.timer import Timer

_console = Console()

ANSI_BAR = "\033[36m│\033[0m"
SHORT_THRESHOLD = 3


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


def _render_md_lines(text):
    md = Markdown(text)
    with _console.capture() as capture:
        _console.print(md, width=_console.width - 6)
    return capture.get().rstrip("\n").split("\n")


def _print_short(lines):
    sys.stdout.write("\n")
    for line in lines:
        sys.stdout.write(f"  {line}\n")
    sys.stdout.write("\n")
    sys.stdout.flush()


def _print_long(lines):
    sys.stdout.write(f"  {ANSI_BAR}\n")
    for line in lines:
        sys.stdout.write(f"  {ANSI_BAR} {line}\n")
    sys.stdout.write(f"  {ANSI_BAR}\n\n")
    sys.stdout.flush()


async def render(event_stream, spinner=None, taskboard=None):
    if spinner is None:
        spinner = Spinner()

    timer = Timer()
    timer.start()

    reply = ""
    assistant_msg = None
    receiving_text = False

    cancel_task = asyncio.ensure_future(_watch_interrupt(spinner))

    try:
        async for event in event_stream:
            if spinner.interrupted:
                break

            etype = event["type"]

            if etype == "thinking":
                spinner.update(tips=THINKING_TIPS)

            elif etype == "tool":
                tool_name = event.get("name", "")
                if tool_name.startswith("agent_"):
                    spinner.update(tips=AGENT_TIPS)
                else:
                    spinner.update(tips=TOOL_TIPS)

            elif etype == "tool_exec":
                tool_name = event.get("name", "")
                if not tool_name.startswith("agent_"):
                    spinner.update(tips=TOOL_TIPS)

            elif etype == "tool_result":
                tool_name = event.get("name", "")
                if not tool_name.startswith("agent_"):
                    spinner.update(tips=TOOL_TIPS)

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

                if taskboard and taskboard._visible:
                    await asyncio.sleep(0.8)
                    taskboard.clear()

                spinner.stop(final_message=stats)

                if reply:
                    md_lines = _render_md_lines(reply)
                    if len(md_lines) <= SHORT_THRESHOLD:
                        _print_short(md_lines)
                    else:
                        _print_long(md_lines)
                else:
                    sys.stdout.write("\n")
                    sys.stdout.flush()

    finally:
        cancel_task.cancel()
        import agents
        agents.clear_plan()
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

    return reply, assistant_msg


async def _watch_interrupt(spinner):
    try:
        while True:
            await asyncio.sleep(0.1)
            if spinner.interrupted:
                for task in asyncio.all_tasks():
                    if task is not asyncio.current_task():
                        task.cancel()
                break
    except asyncio.CancelledError:
        pass
