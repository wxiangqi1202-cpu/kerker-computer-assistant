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
    _console.print(f"  [green]✓ 模型: {config.MODELS[model_name]['name']}[/green]")


@command("/role", "切换/新建/管理角色")
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
    items.append({"label": "  管理角色", "hint": "查看/编辑/删除"})

    idx = pick(items, title="↑↓ 选择角色, Enter 确认, ESC 取消", current_idx=current_idx)
    if idx is None:
        return
    if idx == len(role_names):
        _create_role(ctx)
    elif idx == len(role_names) + 1:
        _manage_roles(ctx)
    else:
        _apply_role(role_names[idx], ctx)


def _apply_role(role_name, ctx):
    config.CURRENT_ROLE = role_name
    config.SYSTEM_PROMPTS = config.ROLES[role_name]
    non_system = [m for m in ctx["messages"] if m["role"] != "system"]
    ctx["messages"] = clean_for_api(build_system_messages() + non_system)
    config.save_user_config()
    _console.print(f"  [green]✓ 已切换: {role_name}[/green]")


def _create_role(ctx):
    _console.print("  [cyan]新建角色[/cyan]")
    _console.print("  [dim]提示：也可以在对话中说'帮我创建一个xxx角色'来自动蒸馏[/dim]")
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

        inject_items = [
            {"label": "是，自动注入", "hint": "推荐"},
            {"label": "否，纯净角色", "hint": "不带工具能力"},
        ]
        inject_idx = pick(inject_items, title="是否注入工具/探索/智能体能力？")
        if inject_idx is None:
            return
        if inject_idx == 0:
            prompts.append(config.TOOL_DIRECTIVE)
            prompts.append(config.EXPLORE_DIRECTIVE)
            prompts.append(config.AGENT_DIRECTIVE)

        config.ROLES[name] = prompts
        _apply_role(name, ctx)
        _console.print(f"  [green]✓ 已创建: {name}[/green]")
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")


def _manage_roles(ctx):
    builtin = config._BUILTIN_ROLES
    user_roles = [name for name in config.ROLES if name not in builtin]

    if not user_roles:
        _console.print("  [dim]没有用户自建角色。内置角色不可编辑。[/dim]")
        return

    items = [{"label": name, "hint": "✓" if name == config.CURRENT_ROLE else ""} for name in user_roles]
    idx = pick(items, title="选择要管理的角色")
    if idx is None:
        return

    role_name = user_roles[idx]
    actions = [
        {"label": "查看 Prompt", "hint": ""},
        {"label": "编辑 Prompt", "hint": ""},
        {"label": "删除角色", "hint": ""},
    ]
    action_idx = pick(actions, title=f"管理: {role_name}")
    if action_idx is None:
        return

    if action_idx == 0:
        _view_role(role_name)
    elif action_idx == 1:
        _edit_role(role_name, ctx)
    elif action_idx == 2:
        _delete_role(role_name, ctx)


def _view_role(role_name):
    prompts = config.ROLES.get(role_name, [])
    _console.print(f"\n  [cyan]{role_name}[/cyan] [dim]({len(prompts)} 条提示词)[/dim]\n")
    for i, p in enumerate(prompts, 1):
        display = p[:80] + "..." if len(p) > 80 else p
        _console.print(f"  [dim]{i}.[/dim] {display}")
    _console.print()


def _edit_role(role_name, ctx):
    prompts = list(config.ROLES.get(role_name, []))
    _console.print(f"  [cyan]编辑: {role_name}[/cyan]")
    _console.print("  [dim]当前提示词:[/dim]")
    for i, p in enumerate(prompts, 1):
        display = p[:60] + "..." if len(p) > 60 else p
        _console.print(f"  [dim]{i}.[/dim] {display}")
    _console.print()
    _console.print("  [dim]输入新的提示词（每行一条，空行结束）。留空保持原样:[/dim]")
    try:
        new_prompts = []
        while True:
            line = input("  > ").strip()
            if not line:
                break
            new_prompts.append(line)
        if new_prompts:
            config.ROLES[role_name] = new_prompts
            if config.CURRENT_ROLE == role_name:
                _apply_role(role_name, ctx)
            config.save_user_config()
            _console.print(f"  [green]✓ 已更新: {role_name}[/green]")
        else:
            _console.print("  [dim]未修改[/dim]")
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")


def _delete_role(role_name, ctx):
    if role_name == config.CURRENT_ROLE:
        _console.print("  [red]不能删除当前使用中的角色，请先切换到其他角色[/red]")
        return
    try:
        confirm = input(f"  确认删除 [{role_name}]? (y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")
        return
    if confirm == "y":
        del config.ROLES[role_name]
        config.save_user_config()
        _console.print(f"  [green]✓ 已删除: {role_name}[/green]")


@command("/resume", "恢复/保存/搜索对话")
def cmd_resume(args, ctx):
    arg = args.strip()

    if arg == "continue" or arg == "":
        from core.interrupt import get_recovery
        recovery = get_recovery()
        if recovery.has_state():
            _do_interrupt_resume(ctx)
            return

    if arg == "save":
        _do_save(ctx)
        return
    if arg == "export":
        _do_export(ctx)
        return
    if arg.startswith("search "):
        _do_search_history(arg[7:].strip())
        return
    if arg:
        _do_load(arg, ctx)
        return

    from core.interrupt import get_recovery
    recovery = get_recovery()
    has_interrupt = recovery.has_state()

    items = []
    if has_interrupt:
        state = recovery.get_state()
        items.append({"label": "续接中断的回复", "hint": state.format_preview()[:40] if state else ""})
    items.extend([
        {"label": "恢复上次对话", "hint": "自动保存的对话"},
        {"label": "浏览历史对话", "hint": ""},
        {"label": "搜索历史", "hint": "按关键词查找"},
        {"label": "保存当前对话", "hint": ""},
        {"label": "导出 Markdown", "hint": ""},
    ])

    idx = pick(items, title="对话管理")
    if idx is None:
        return

    offset = 1 if has_interrupt else 0
    if has_interrupt and idx == 0:
        _do_interrupt_resume(ctx)
    elif idx == offset + 0:
        _do_quick_resume(ctx)
    elif idx == offset + 1:
        _do_pick_history(ctx)
    elif idx == offset + 2:
        _do_search_prompt()
    elif idx == offset + 3:
        _do_save(ctx)
    elif idx == offset + 4:
        _do_export(ctx)


def _do_interrupt_resume(ctx):
    """从流式中断状态恢复，注入续接消息"""
    from core.interrupt import get_recovery
    recovery = get_recovery()
    state = recovery.consume_state()
    if not state or not state.has_content:
        _console.print("  [dim]没有可恢复的中断状态[/dim]")
        return

    messages = ctx["messages"]
    resume_msgs = state.build_resume_messages()
    for msg in resume_msgs:
        messages.append(msg)
    ctx["messages"] = messages
    ctx["_resume_trigger"] = True

    preview = state.partial_reply[-50:].replace("\n", " ").strip() if state.partial_reply else "工具调用中断"
    _console.print(f"  [green]✓ 已注入续接指令[/green]")
    _console.print(f"  [dim]断点: ...{preview}[/dim]")
    _console.print(f"  [dim]发送任意消息即可触发续接[/dim]")
    _console.print()


def _do_quick_resume(ctx):
    """快速恢复上次自动保存的对话"""
    msgs = history.load("_autosave.json")
    if not msgs:
        _console.print("  [dim]没有自动保存的对话[/dim]")
        return
    ctx["messages"] = msgs
    non_system = [m for m in msgs if m["role"] != "system"]
    user_count = sum(1 for m in non_system if m["role"] == "user")
    _console.print(f"  [green]✓ 已恢复上次对话 ({user_count} 轮)[/green]")

    recent = [m for m in non_system if m["role"] in ("user", "assistant")][-4:]
    for msg in recent:
        content = msg.get("content", "") or ""
        preview = content.split("\n")[0][:50]
        tag = "你" if msg["role"] == "user" else "K"
        _console.print(f"  [dim]  {tag} › {preview}[/dim]")
    _console.print()


def _do_search_prompt():
    """交互式搜索历史"""
    try:
        query = input("  搜索关键词: ").strip()
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已取消[/dim]")
        return
    if not query:
        return
    _do_search_history(query)


def _do_search_history(query):
    """按关键词搜索情景记忆"""
    from core.memory import get_episodic
    epi = get_episodic()
    results = epi.search(query, limit=10)
    if not results:
        _console.print(f"  [dim]没有找到关于'{query}'的历史对话[/dim]")
        return
    _console.print(f"\n  [cyan]搜索: {query}[/cyan]\n")
    for ep in results:
        ts = ep.get("timestamp", "")[:16].replace("T", " ")
        summary = ep.get("summary", "")[:50]
        rounds = ep.get("rounds", 0)
        _console.print(f"  [dim]{ts}[/dim]  {summary}  [dim]({rounds}轮)[/dim]")
    _console.print()


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
    from core.memory import get_episodic
    get_episodic().add_episode(ctx["messages"], filename=filename)
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


@command("/memory", "查看/管理记忆")
def cmd_memory(args, ctx):
    from core.memory import get_semantic, get_episodic
    sem = get_semantic()

    arg = args.strip()

    if arg == "clear":
        try:
            confirm = input("  确认清空所有记忆? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            _console.print("\n  [dim]已取消[/dim]")
            return
        if confirm == "y":
            sem.clear_all()
            _console.print("  [green]✓ 记忆已清空[/green]")
        return

    entries = sem.get_all()
    if not entries:
        _console.print("  [dim]还没有记忆。在对话中说'记住xxx'来添加。[/dim]")
        return

    _console.print(f"\n  [cyan]记忆 ({len(entries)} 条)[/cyan]\n")
    for e in entries:
        importance = e.get("importance", 5)
        source = e.get("source", "auto")
        marker = "★" if importance >= 8 else "·"
        src_tag = f" [dim]({source})[/dim]" if source != "auto" else ""
        _console.print(f"  {marker} {e['content']}{src_tag}")
    _console.print(f"\n  [dim]使用 /memory clear 清空，或在对话中说'忘掉xxx'删除单条[/dim]\n")


@command("/exit", "退出程序")
def cmd_exit(args, ctx):
    ctx["should_exit"] = True


@command("/welcome", "切换启动页风格")
def cmd_welcome(args, ctx):
    from cli.welcome import show_welcome, save_welcome_style, WELCOME_STYLES, get_style_desc

    if args.strip() in WELCOME_STYLES:
        save_welcome_style(args.strip())
        show_welcome(args.strip())
        return

    desc = get_style_desc()
    items = [
        {"label": name, "hint": desc.get(name, "")}
        for name in WELCOME_STYLES
    ]
    idx = pick(items, title="选择启动页风格，Enter 预览并保存")
    if idx is not None:
        chosen = WELCOME_STYLES[idx]
        save_welcome_style(chosen)
        show_welcome(chosen)


@command("/theme", "切换渲染主题")
def cmd_theme(args, ctx):
    from display.theme import get_theme, set_theme, get_theme_names
    names = get_theme_names()
    current = get_theme().get("name", "minimal")

    if args.strip():
        name = args.strip()
        if set_theme(name):
            _console.print(f"  [green]✓ 主题: {name}[/green]")
        else:
            _console.print(f"  [red]未知主题: {name}  可选: {', '.join(names)}[/red]")
        return

    items = [
        {"label": name, "hint": "✓" if name == current else ""}
        for name in names
    ]
    current_idx = names.index(current) if current in names else 0
    idx = pick(items, title="↑↓ 选择主题, Enter 确认, ESC 取消", current_idx=current_idx)
    if idx is not None:
        set_theme(names[idx])
        _console.print(f"  [green]✓ 主题: {names[idx]}[/green]")


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


@command("/metrics", "查看性能统计")
def cmd_metrics(args, ctx):
    from core.metrics import get_metrics
    metrics = get_metrics()
    _console.print()
    _console.print(metrics.format_summary())
    _console.print()
