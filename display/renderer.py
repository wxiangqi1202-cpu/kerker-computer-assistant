"""
渲染层 —— Markdown 渲染 + 自适应显示 + 任务面板
spinner 全程运行直到回复完成，然后一次性 Markdown 渲染。
短回复（≤3行）直接平铺，长回复用左侧竖线包裹。
"""

import sys
import asyncio
from rich.console import Console

from display.spinner import (
    Spinner,
    THINKING_TIPS, GENERATING_TIPS, TOOL_TIPS, AGENT_TIPS,
)
from display.timer import Timer
from display.md_render import print_markdown

_console = Console()

_ROUTE_TIPS = {
    "plan": ["启动任务规划...", "拆解子步骤中..."],
    "single_agent": ["调度专属智能体..."],
}


def _show_route_hint(decision, spinner):
    """将路由决策转化为 spinner 提示"""
    action = decision.action
    if action == "plan":
        spinner.update(tips=_ROUTE_TIPS["plan"])
    elif action == "single_agent" and decision.agent_name:
        spinner.update(tips=[f"调度 {decision.agent_name}..."])


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
                if decision:
                    _show_route_hint(decision, spinner)

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
            agents.clear_plan()
            if taskboard:
                taskboard.clear()
            spinner.stop()

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
