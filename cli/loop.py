"""
主循环 —— 用户交互入口
"""

import sys
import asyncio
import skills
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns

from core import config
from core.async_client import create_client, send
from core.history import ensure_dirs
from core import history
from display import Spinner, TaskBoard, render
from display.spinner import CONNECTING_TIPS
from cli.completer import create_session
from cli.registry import dispatch
from cli.commands import build_system_messages
import cli.commands  # noqa: F401  触发 @command 注册
import agents  # noqa: F401  触发子智能体加载

_console = Console()

VERSION = "0.2.0"

try:
    import importlib.metadata
    VERSION = importlib.metadata.version("kerker")
except Exception:
    pass


def _show_welcome():
    width = min(_console.width, 60)
    logo = Text()
    logo.append("\n")
    logo.append("  K e r K e r\n", style="bold cyan")
    logo.append("  Computational Agent Framework\n", style="dim italic")
    panel = Panel(logo, border_style="cyan", width=width, padding=(0, 2))
    _console.print()
    _console.print(panel)
    _console.print()
    agent_count = len(agents.get_all_agents())
    skill_count = len(skills.get_skill_names())
    mode = "流式" if config.STREAM else "非流式"
    col_left = Text()
    col_left.append("  模型  ", style="dim")
    col_left.append(f"{config.MODEL}\n", style="white")
    col_left.append("  角色  ", style="dim")
    col_left.append(config.CURRENT_ROLE, style="white")
    col_right = Text()
    col_right.append("  技能  ", style="dim")
    col_right.append(f"{skill_count} 个\n", style="white")
    col_right.append("  智能体  ", style="dim")
    col_right.append(f"{agent_count} 个", style="white")
    _console.print(Columns([col_left, col_right], padding=(0, 4)))
    _console.print()
    _console.print('  [dim]/help 命令 · /fast 极速 · /deep 深度 · ESC 中断 · /exit 退出[/dim]')

    import os
    autosave_path = os.path.join(config.HISTORY_DIR, "_autosave.json")
    if os.path.isfile(autosave_path):
        _console.print('  [dim]检测到上次对话，输入 /resume 恢复[/dim]')

    _console.print()


async def _read_multiline(session):
    """读取多行输入直到遇到结束的 \"\"\""""
    lines = []
    while True:
        try:
            line = await session.prompt_async("  … ")
        except (EOFError, KeyboardInterrupt):
            return None
        if line.rstrip().endswith('"""'):
            tail = line.rstrip()[:-3]
            if tail:
                lines.append(tail)
            break
        lines.append(line)
    return "\n".join(lines)


def _trim_context(messages):
    """
    智能上下文裁剪：超出限制的旧消息压缩为摘要保留，而不是丢弃。
    保留 system 消息，确保 tool 链完整。
    """
    from core.history import clean_for_api
    limit = config.MAX_CONTEXT_MESSAGES
    system_msgs = [m for m in messages if m["role"] == "system"]
    non_system = [m for m in messages if m["role"] != "system"]

    if len(non_system) <= limit:
        return clean_for_api(system_msgs + non_system)

    overflow = non_system[:-limit]
    kept = non_system[-limit:]

    summary_parts = []
    for msg in overflow:
        role = msg.get("role", "")
        content = msg.get("content", "") or ""
        if role == "user" and content:
            line = content.split("\n")[0][:80]
            summary_parts.append(f"用户: {line}")
        elif role == "assistant" and content:
            line = content.split("\n")[0][:80]
            summary_parts.append(f"助手: {line}")

    if summary_parts:
        summary_text = (
            "[以下是更早的对话摘要，供参考]\n"
            + "\n".join(summary_parts[-8:])
        )
        summary_msg = {"role": "system", "content": summary_text}
        result = system_msgs + [summary_msg] + kept
    else:
        result = system_msgs + kept

    return clean_for_api(result)


def _autosave(messages):
    """退出前自动保存当前对话"""
    non_system = [m for m in messages if m["role"] != "system"]
    if non_system:
        history.save(messages, "_autosave.json")


async def _async_main():
    ensure_dirs()

    from cli.setup import needs_setup, run_setup
    if needs_setup():
        run_setup()

    session = create_session()
    api_client = create_client()
    taskboard = TaskBoard()
    spinner = Spinner()
    spinner.set_taskboard(taskboard)
    agents.set_spinner(spinner)
    agents.set_taskboard(taskboard)
    messages = build_system_messages()
    _show_welcome()

    ctx = {
        "messages": messages,
        "api_client": api_client,
        "should_exit": False,
    }

    while True:
        try:
            user_input = (await session.prompt_async("  › ")).strip()
        except (EOFError, KeyboardInterrupt):
            _autosave(messages)
            config.save_user_config()
            _console.print("\n  [dim]再见！[/dim]")
            break

        if not user_input:
            continue

        if user_input.startswith('"""'):
            first_line = user_input[3:]
            body = await _read_multiline(session)
            if body is None:
                continue
            user_input = (first_line + "\n" + body).strip() if first_line.strip() else body.strip()
            if not user_input:
                continue

        if user_input.startswith("/"):
            if dispatch(user_input, ctx):
                if ctx["should_exit"]:
                    _autosave(messages)
                    config.save_user_config()
                    _console.print("  [dim]再见！[/dim]")
                    break
                messages = ctx["messages"]
                api_client = ctx["api_client"]
                continue
            _console.print(f"  [red]未知命令: {user_input.split()[0]}[/red]")
            _console.print("  [dim]输入 /help 查看可用命令[/dim]")
            continue

        messages.append({"role": "user", "content": user_input})
        messages = _trim_context(messages)
        ctx["messages"] = messages

        width = _console.width
        display_text = user_input.split("\n")[0]
        if "\n" in user_input:
            display_text += " ..."
        label = f"  › {display_text} "
        sys.stdout.write("\033[A\r\033[K")
        _console.print(
            f"[white on grey23]{label}{' ' * max(0, width - len(label))}[/white on grey23]"
        )

        try:
            spinner.update(tips=CONNECTING_TIPS)
            event_stream = send(api_client, messages)
            reply, assistant_msg = await render(event_stream, spinner=spinner, taskboard=taskboard)

            if assistant_msg:
                messages.append(assistant_msg)
            elif reply:
                messages.append({"role": "assistant", "content": reply})
            else:
                messages.pop()
            ctx["messages"] = messages

        except asyncio.CancelledError:
            spinner.stop()
            taskboard.clear()
            messages.pop()
        except Exception as error:
            spinner.stop()
            taskboard.clear()
            _console.print(f"\n  [red]请求出错: {error}[/red]")
            messages.pop()


def main():
    asyncio.run(_async_main())
