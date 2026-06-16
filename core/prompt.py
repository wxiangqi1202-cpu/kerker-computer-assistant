"""
System Prompt 组装 —— 管理 messages 中的系统消息

职责：
- 同步角色 system prompt（角色切换后更新）
- 按路由裁剪 directives（DIRECT 跳过行为指导）
- 管理 [已有角色] / [自动路由] / [相关记忆] 等动态系统消息
- 清理过期的路由消息
"""

from core import config


def sync_system_messages(messages, route_action=None):
    """
    同步 system 消息：角色切换后确保 messages 中的 system 消息是最新的。
    route_action:
      - "direct": 跳过行为 directives（AGENT/EXPLORE），省 ~400 token
      - 其他: 注入完整 directives
    """
    from cli.commands import build_system_messages
    current_system = build_system_messages()

    if route_action == "direct":
        filtered_system = []
        for msg in current_system:
            content = msg["content"]
            if content in (config.TOOL_DIRECTIVE, config.EXPLORE_DIRECTIVE, config.AGENT_DIRECTIVE):
                continue
            filtered_system.append(msg)
        current_system = filtered_system

    current_contents = {m["content"] for m in current_system}

    old_system = [m for m in messages if m["role"] == "system"]
    old_role_contents = set()
    env_msgs = []
    for m in old_system:
        content = m["content"]
        if content.startswith("[自动路由]") or content.startswith("[已有角色]"):
            continue
        if any(content.startswith(p) for p in ("[当前系统可用工具]", "[以下是更早", "[近期对话摘要]")):
            env_msgs.append(m)
        else:
            old_role_contents.add(content)

    if old_role_contents != current_contents:
        non_system = [m for m in messages if m["role"] != "system"]
        messages.clear()
        messages.extend(current_system)
        messages.extend(env_msgs)
        messages.extend(non_system)

    _update_role_info(messages)
    _inject_relevant_memory(messages)


def clean_route_messages(messages):
    """清理上一轮残留的 [自动路由] / [执行提示] / [执行反馈] 消息"""
    i = 0
    while i < len(messages):
        content = messages[i].get("content", "")
        if messages[i].get("role") == "system" and any(
            content.startswith(p) for p in ("[自动路由]", "[执行提示]", "[执行反馈]")
        ):
            messages.pop(i)
        else:
            i += 1


def _update_role_info(messages):
    """更新 [已有角色] 系统消息"""
    role_list = ", ".join(config.ROLES.keys())
    role_info = (
        f"[已有角色] 当前: {config.CURRENT_ROLE}。可切换: {role_list}。\n"
        "角色操作规则（必须遵守）：\n"
        "- 切换已有角色 → 调 switch_role\n"
        "- 创建新角色 → 调 distill_role 提取特征，然后调 save_distilled_role 保存并切换\n"
        "- 绝对不要直接用对话方式'扮演'角色，必须通过工具创建/切换后再以该角色身份回答\n"
        "- 只有 save_distilled_role 成功后，角色才算真正生效"
    )
    existing = [i for i, m in enumerate(messages)
                if m.get("role") == "system" and m.get("content", "").startswith("[已有角色]")]
    if existing:
        messages[existing[0]]["content"] = role_info
    else:
        system_end = 0
        for i, m in enumerate(messages):
            if m["role"] == "system":
                system_end = i + 1
        messages.insert(system_end, {"role": "system", "content": role_info})


def _inject_relevant_memory(messages):
    """基于最新用户输入动态注入相关记忆"""
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if not user_msgs:
        return

    last_q = user_msgs[-1].get("content", "")

    messages[:] = [
        m for m in messages
        if not (m["role"] == "system" and
                any(m.get("content", "").startswith(p)
                    for p in ("[相关记忆]", "[用户记忆]")))
    ]

    if not last_q or len(last_q) < 6:
        return

    from core.memory import get_semantic
    try:
        relevant = get_semantic().search(last_q, limit=5, update_access=False)
    except TypeError:
        relevant = get_semantic().search(last_q, limit=5)

    if not relevant:
        return

    grouped = {}
    for entry in relevant:
        grouped.setdefault(entry.get("category", "事实"), []).append(entry["content"])
    lines = ["[相关记忆]"]
    for cat, items in grouped.items():
        lines.append(f"  [{cat}]")
        for item in items:
            lines.append(f"  - {item}")
    mem_block = "\n".join(lines)

    last_sys = max(
        (i for i, m in enumerate(messages) if m["role"] == "system"),
        default=-1,
    )
    messages.insert(last_sys + 1, {"role": "system", "content": mem_block})
