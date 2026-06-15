"""
主循环 —— 用户交互入口
"""

import sys
import asyncio
import skills
from rich.console import Console

from core import config
from core.async_client import create_client, send
from core.history import ensure_dirs
from core import history
from display import Spinner, TaskBoard, render
from display.spinner import CONNECTING_TIPS
from cli.completer import create_session
from cli.registry import dispatch
from cli.commands import build_system_messages
from cli.welcome import show_welcome
import cli.commands  # noqa: F401  触发 @command 注册
import agents  # noqa: F401  触发子智能体加载

_console = Console()

VERSION = "0.2.0"

try:
    import importlib.metadata
    VERSION = importlib.metadata.version("kerker")
except Exception:
    pass



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


from core.tokens import count_tokens, count_message_tokens, get_max_context_tokens


def _estimate_tokens(text):
    """Token 计数（优先 tiktoken 精确计算，fallback 启发式）"""
    return count_tokens(text)


def _msg_tokens(msg):
    """计算单条消息的 token 数"""
    return count_message_tokens(msg)


def _trim_context(messages):
    """
    Token-aware 上下文裁剪：按 token 预算保留尽可能多的近期消息，
    超出部分压缩为摘要。保留 system 消息，确保 tool 链完整。
    """
    from core.history import clean_for_api
    system_msgs = [m for m in messages if m["role"] == "system"]
    non_system = [m for m in messages if m["role"] != "system"]

    msg_limit = config.MAX_CONTEXT_MESSAGES
    if len(non_system) > msg_limit:
        non_system = non_system[-msg_limit:]

    system_tokens = sum(_msg_tokens(m) for m in system_msgs)
    max_context = get_max_context_tokens()
    budget = max_context - system_tokens

    kept = []
    used_tokens = 0
    for msg in reversed(non_system):
        mt = _msg_tokens(msg)
        if used_tokens + mt > budget:
            break
        kept.insert(0, msg)
        used_tokens += mt

    overflow = non_system[:len(non_system) - len(kept)]

    if overflow:
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
    else:
        result = system_msgs + kept

    return clean_for_api(result)


def _autosave(messages):
    """退出前自动保存当前对话 + 索引情景记忆"""
    non_system = [m for m in messages if m["role"] != "system"]
    if non_system:
        filepath = history.save(messages, "_autosave.json")
        from core.memory import get_episodic
        get_episodic().add_episode(messages, filename="_autosave.json")


async def _async_main():
    ensure_dirs()

    from cli.setup import needs_setup, run_setup
    if needs_setup():
        run_setup()

    session = create_session()
    api_client = create_client()

    from core.progress import get_tracker
    tracker = get_tracker()

    taskboard = TaskBoard()
    taskboard.set_tracker(tracker)
    spinner = Spinner()
    spinner.set_taskboard(taskboard)
    agents.set_spinner(spinner)
    messages = build_system_messages()

    from core.env_probe import format_env_prompt
    env_prompt = format_env_prompt()
    if env_prompt:
        messages.append({"role": "system", "content": env_prompt})

    from core.memory import get_semantic, get_episodic
    sem_prompt = get_semantic().format_for_prompt(limit=8)
    if sem_prompt:
        messages.append({"role": "system", "content": sem_prompt})
    epi_prompt = get_episodic().format_recent_for_prompt(limit=3)
    if epi_prompt:
        messages.append({"role": "system", "content": epi_prompt})

    role_list = ", ".join(config.ROLES.keys())
    messages.append({"role": "system", "content":
        f"[已有角色] 当前: {config.CURRENT_ROLE}。可用: {role_list}"
    })

    show_welcome()

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
            _console.print(f"   [red]未知命令: {user_input.split()[0]}[/red]")
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
        pad_line = " " * width
        sys.stdout.write("\033[A\r\033[K")
        _console.print(
            f"[white on grey23]{pad_line}\n{label}{' ' * max(0, width - len(label))}\n{pad_line}[/white on grey23]"
        )

        try:
            messages_backup = list(messages)
            spinner.update(tips=CONNECTING_TIPS)
            event_stream = send(api_client, messages)
            reply, assistant_msg = await render(event_stream, spinner=spinner, taskboard=taskboard)

            if spinner.interrupted:
                messages.clear()
                messages.extend(messages_backup)
                ctx["messages"] = messages
            else:
                if assistant_msg:
                    messages.append(assistant_msg)
                elif reply:
                    messages.append({"role": "assistant", "content": reply})
                ctx["messages"] = messages

        except asyncio.CancelledError:
            spinner.stop()
            taskboard.clear()
            messages.clear()
            messages.extend(messages_backup)
        except Exception as error:
            spinner.stop()
            taskboard.clear()
            agents.clear_plan()
            messages.clear()
            messages.extend(messages_backup)
            err_str = str(error)
            if "api_key" in err_str.lower() or "auth" in err_str.lower() or "401" in err_str:
                _console.print("\n  [red]API Key 无效或已过期，请运行 /config 重新配置[/red]")
            elif "connect" in err_str.lower() or "timeout" in err_str.lower() or "网络" in err_str:
                _console.print("\n  [red]网络连接失败，请检查网络后重试[/red]")
            elif "rate" in err_str.lower() or "429" in err_str:
                _console.print("\n  [red]请求过于频繁，请稍后再试[/red]")
            elif "model" in err_str.lower() and ("not found" in err_str.lower() or "不存在" in err_str):
                _console.print(f"\n   [red]模型 {config.MODEL} 不可用，请用 /model 切换[/red]")
            else:
                short = err_str[:120] + "..." if len(err_str) > 120 else err_str
                _console.print(f"\n   [red]出错: {short}[/red]")
                _console.print("  [dim]如果持续出错，试试 /clear 清空对话或 /fast 切换模式[/dim]")


def main():
    asyncio.run(_async_main())
