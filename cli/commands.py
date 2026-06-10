"""
斜杠命令 —— 使用 @command 装饰器注册
每个命令接收 (args, ctx)，ctx 是运行时上下文 dict
"""

import os
from datetime import datetime
from rich.console import Console
from rich.table import Table

from core import config

from core.async_client import create_client
from core import history
from core.history import clean_for_api
import skills
import agents as agents_module
from cli.registry import command
from cli.picker import pick

_console = Console()


def build_system_messages():
    return [{"role": "system", "content": p} for p in config.SYSTEM_PROMPTS]


@command("/help", "显示帮助信息")
def cmd_help(args, ctx):
    from cli.registry import get_all
    table = Table(title="KerKer 命令列表", show_header=True, header_style="bold cyan")
    table.add_column("命令", style="green", width=20)
    table.add_column("说明")
    for name, desc in get_all().items():
        table.add_row(name, desc)
    _console.print(table)


@command("/skills", "查看已加载技能")
def cmd_skills(args, ctx):
    specs = skills.get_tool_specs()
    if not specs:
        _console.print("  [dim]当前没有已加载的技能。[/dim]")
        return
    table = Table(title="已加载技能", show_header=True, header_style="bold cyan")
    table.add_column("技能名称", style="green", width=20)
    table.add_column("说明")
    for spec in specs:
        func = spec["function"]
        table.add_row(func["name"], func["description"])
    _console.print(table)


@command("/agents", "查看已加载子智能体")
def cmd_agents(args, ctx):
    all_agents = agents_module.get_all_agents()
    if not all_agents:
        _console.print("  [dim]当前没有已加载的子智能体。[/dim]")
        return
    table = Table(title="子智能体", show_header=True, header_style="bold cyan")
    table.add_column("名称", style="green", width=16)
    table.add_column("说明", width=30)
    table.add_column("模型", style="dim")
    for name, agent in all_agents.items():
        model = agent.model or config.MODEL
        table.add_row(name, agent.description, model)
    _console.print(table)


@command("/model", "切换模型")
def cmd_model(args, ctx):
    if args.strip():
        model_name = args.strip()
        if model_name in config.MODELS:
            _apply_model(model_name, ctx)
        else:
            _console.print(f"  [red]未知模型: {model_name}[/red]")
        return

    model_ids = list(config.MODELS.keys())
    current_idx = model_ids.index(config.MODEL) if config.MODEL in model_ids else 0
    items = [
        {"label": mid, "hint": info["name"] + (" ✓" if mid == config.MODEL else "")}
        for mid, info in config.MODELS.items()
    ]
    idx = pick(items, title="↑↓ 选择模型, Enter 确认, ESC 取消", current_idx=current_idx)
    if idx is not None:
        _apply_model(model_ids[idx], ctx)


def _apply_model(model_name, ctx):
    config.MODEL = model_name
    config.BASE_URL = config.MODELS[model_name]["base_url"]
    ctx["api_client"] = create_client()
    config.save_user_config()


@command("/role", "切换/新建角色")
def cmd_role(args, ctx):
    if args.strip() == "new":
        _create_role(ctx)
        return

    if args.strip():
        role_name = args.strip()
        if role_name in config.ROLES:
            _apply_role(role_name, ctx)
        else:
            _console.print(f"  [red]未知角色: {role_name}[/red]")
        return

    role_names = list(config.ROLES.keys())
    current_idx = role_names.index(config.CURRENT_ROLE) if config.CURRENT_ROLE in role_names else 0
    items = [
        {"label": name, "hint": "✓" if name == config.CURRENT_ROLE else ""}
        for name in role_names
    ]
    items.append({"label": "+ 新建角色", "hint": ""})

    idx = pick(items, title="↑↓ 选择角色, Enter 确认, ESC 取消", current_idx=current_idx)
    if idx is None:
        return
    if idx == len(role_names):
        _create_role(ctx)
    else:
        _apply_role(role_names[idx], ctx)


def _apply_role(role_name, ctx):
    config.CURRENT_ROLE = role_name
    config.SYSTEM_PROMPTS = config.ROLES[role_name]
    non_system = [m for m in ctx["messages"] if m["role"] != "system"]
    ctx["messages"] = clean_for_api(build_system_messages() + non_system)
    config.save_user_config()


def _create_role(ctx):
    _console.print("  [cyan]新建角色[/cyan]")
    try:
        name = input("  角色名称: ").strip()
        if not name:
            return
        if name in config.ROLES:
            _console.print(f"  [red]角色 {name} 已存在[/red]")
            return
        _console.print("  [dim]输入提示词（每行一条，空行结束）:[/dim]")
        prompts = []
        while True:
            line = input("  > ").strip()
            if not line:
                break
            prompts.append(line)
        if not prompts:
            _console.print("  [red]至少需要一条提示词[/red]")
            return
        config.ROLES[name] = prompts
        _apply_role(name, ctx)
        _console.print(f"  [green]✓ 已创建: {name}[/green]")
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")


@command("/resume", "对话管理")
def cmd_resume(args, ctx):
    actions = [
        {"label": "恢复历史对话", "hint": ""},
        {"label": "保存当前对话", "hint": ""},
        {"label": "导出为 Markdown", "hint": ""},
    ]

    if args.strip() == "save":
        _do_save(ctx)
        return
    if args.strip() == "export":
        _do_export(ctx)
        return
    if args.strip():
        _do_load(args.strip(), ctx)
        return

    idx = pick(actions, title="↑↓ 选择操作, Enter 确认, ESC 取消")
    if idx is None:
        return
    if idx == 0:
        _do_pick_history(ctx)
    elif idx == 1:
        _do_save(ctx)
    elif idx == 2:
        _do_export(ctx)


def _do_pick_history(ctx):
    files = history.list_all()
    if not files:
        _console.print("  [dim]没有历史对话。[/dim]")
        return

    items = []
    for fname in files[:15]:
        msgs = history.load(fname)
        if not msgs:
            continue
        non_system = [m for m in msgs if m["role"] != "system"]
        user_msgs = [m for m in non_system if m["role"] == "user"]
        rounds = len(user_msgs)
        time_str = "自动保存" if fname == "_autosave.json" else fname.replace(".json", "").replace("_", " ")
        topic = ""
        if user_msgs:
            topic = user_msgs[-1].get("content", "")[:25]
            if len(user_msgs[-1].get("content", "")) > 25:
                topic += "..."
        items.append({
            "label": f"{time_str}  ({rounds}轮)",
            "hint": topic,
            "_file": fname,
        })

    if not items:
        _console.print("  [dim]没有有效的历史对话。[/dim]")
        return

    idx = pick(items, title="↑↓ 选择对话, Enter 恢复, ESC 取消")
    if idx is None:
        return
    target = items[idx]["_file"]
    msgs = history.load(target)
    if not msgs:
        _console.print("  [red]加载失败[/red]")
        return
    ctx["messages"] = msgs
    non_system = [m for m in msgs if m["role"] != "system"]
    user_count = sum(1 for m in non_system if m["role"] == "user")
    _console.print(f"  [green]✓ 已恢复 ({user_count} 轮)[/green]")

    recent = [m for m in non_system if m["role"] in ("user", "assistant")][-4:]
    for msg in recent:
        content = msg.get("content", "") or ""
        preview = content.split("\n")[0][:50]
        tag = "你" if msg["role"] == "user" else "K"
        _console.print(f"  [dim]  {tag} › {preview}[/dim]")
    _console.print()


def _do_load(target, ctx):
    files = history.list_all()
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(files):
            target = files[idx]
        else:
            _console.print("  [red]编号超出范围[/red]")
            return
    msgs = history.load(target)
    if not msgs:
        _console.print(f"  [red]未找到: {target}[/red]")
        return
    ctx["messages"] = msgs
    _console.print(f"  [green]✓ 已恢复[/green]")


def _do_save(ctx):
    try:
        name = input("  文件名 (直接回车自动命名): ").strip()
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")
        return
    filename = None
    if name:
        filename = name if name.endswith(".json") else name + ".json"
    filepath = history.save(ctx["messages"], filename)
    _console.print(f"  [green]✓ 已保存: {filepath}[/green]")


def _do_export(ctx):
    history.ensure_dirs()
    try:
        name = input("  文件名 (直接回车自动命名): ").strip()
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")
        return
    if not name:
        filename = datetime.now().strftime("%Y%m%d_%H%M%S") + ".md"
    else:
        filename = name if name.endswith(".md") else name + ".md"
    filepath = os.path.join(config.HISTORY_DIR, filename)
    lines = []
    for msg in ctx["messages"]:
        role = msg["role"]
        content = msg.get("content", "")
        if role == "system":
            continue
        elif role == "user":
            lines.append(f"**你** › {content}\n")
        elif role == "assistant":
            lines.append(f"**KerKer** ›\n\n{content}\n")
        lines.append("---\n")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    _console.print(f"  [green]✓ 已导出: {filepath}[/green]")


@command("/clear", "清空当前对话")
def cmd_clear(args, ctx):
    ctx["messages"] = build_system_messages()
    _console.print("  [green]✓ 对话已清空[/green]")


@command("/exit", "退出程序")
def cmd_exit(args, ctx):
    ctx["should_exit"] = True


@command("/fast", "极速模式 (flash+关思考)")
def cmd_fast(args, ctx):
    config.apply_preset("fast")
    ctx["api_client"] = create_client()
    _console.print("  [green]✓ 极速模式: flash + 关闭思考[/green]")


@command("/deep", "深度模式 (pro+开思考)")
def cmd_deep(args, ctx):
    config.apply_preset("deep")
    ctx["api_client"] = create_client()
    _console.print("  [green]✓ 深度模式: pro + 深度思考[/green]")


@command("/config", "查看/修改配置")
def cmd_config(args, ctx):
    editable = {
        "stream": ("STREAM", bool, "流式输出"),
        "thinking": ("ENABLE_THINKING", bool, "深度思考"),
        "effort": ("REASONING_EFFORT", str, "推理努力 low/medium/high"),
        "context": ("MAX_CONTEXT_MESSAGES", int, "上下文消息上限"),
    }
    if args.strip():
        parts = args.strip().split(maxsplit=1)
        if len(parts) == 2:
            key, value = parts[0].lower(), parts[1]
            if key in editable:
                attr, type_fn, _ = editable[key]
                try:
                    parsed = value.lower() in ("true", "1", "yes", "on") if type_fn is bool else type_fn(value)
                    setattr(config, attr, parsed)
                    config.save_user_config()
                    _console.print(f"  [green]✓ {key} = {parsed}[/green]")
                except Exception as err:
                    _console.print(f"  [red]值无效: {err}[/red]")
            else:
                _console.print(f"  [red]未知配置项: {key}[/red]")
        else:
            _console.print("  [red]格式: /config <键> <值>[/red]")
        return

    keys = list(editable.keys())
    items = [
        {"label": key, "hint": f"{getattr(config, attr)} — {desc}"}
        for key, (attr, _, desc) in editable.items()
    ]
    idx = pick(items, title="↑↓ 选择配置项, Enter 修改, ESC 取消")
    if idx is None:
        return
    key = keys[idx]
    attr, type_fn, desc = editable[key]
    current = getattr(config, attr)
    _console.print(f"  [dim]当前值: {current}[/dim]")
    try:
        new_val = input(f"  新值: ").strip()
        if not new_val:
            _console.print("  [dim]未修改[/dim]")
            return
        parsed = new_val.lower() in ("true", "1", "yes", "on") if type_fn is bool else type_fn(new_val)
        setattr(config, attr, parsed)
        config.save_user_config()
        _console.print(f"  [green]✓ {key} = {parsed}[/green]")
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")
    except Exception as err:
        _console.print(f"  [red]值无效: {err}[/red]")
