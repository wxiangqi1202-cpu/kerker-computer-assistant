"""
技能：角色管理 —— 切换/查看已有角色 + 保存蒸馏角色
"""

import json
from skills import register
from core import config


def list_roles():
    """列出所有可用角色"""
    roles = list(config.ROLES.keys())
    current = config.CURRENT_ROLE
    lines = [f"当前角色: {current}", f"可用角色: {', '.join(roles)}"]
    return "\n".join(lines)


def switch_role(role_name):
    """切换到已有角色。如果角色不存在，返回提示。"""
    role_name = role_name.strip()
    if role_name in config.ROLES:
        config.CURRENT_ROLE = role_name
        config.SYSTEM_PROMPTS = config.ROLES[role_name]
        config.save_user_config()
        return f"已切换到角色: {role_name}"

    available = ", ".join(config.ROLES.keys())
    return f"角色 [{role_name}] 不存在。可用角色: {available}。如果你想创建新角色，请使用 distill_role 工具。"


def save_distilled_role(role_json, inject_tools=True):
    """将蒸馏结果保存为角色并切换。"""
    try:
        data = json.loads(role_json) if isinstance(role_json, str) else role_json
    except Exception as err:
        return f"JSON 解析失败: {err}"

    role_name = data.get("role_name", "").strip()
    prompts = data.get("prompts", [])
    greeting = data.get("greeting", "")

    if not role_name:
        return "缺少 role_name"
    if not prompts:
        return "缺少 prompts"

    if inject_tools:
        prompts.append(config.TOOL_DIRECTIVE)
        prompts.append(config.EXPLORE_DIRECTIVE)
        prompts.append(config.AGENT_DIRECTIVE)

    config.ROLES[role_name] = prompts
    config.CURRENT_ROLE = role_name
    config.SYSTEM_PROMPTS = prompts
    config.save_user_config()

    result = f"角色 [{role_name}] 已创建并切换。"
    if greeting:
        result += f"\n角色开场白: {greeting}"
    return result


register(
    name="list_roles",
    description="列出所有可用角色和当前角色。当用户问'有哪些角色'、'当前是什么角色'时调用。",
    parameters={"type": "object", "properties": {}, "required": []},
    func=list_roles,
)

register(
    name="switch_role",
    description=(
        "切换到已有角色。当用户说'切换到xxx'、'换成xxx'、'用xxx角色'、'扮演xxx'时调用。"
        "如果角色不存在会返回提示。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "role_name": {
                "type": "string",
                "description": "要切换到的角色名称",
            },
        },
        "required": ["role_name"],
    },
    func=switch_role,
)

register(
    name="save_distilled_role",
    description=(
        "保存蒸馏生成的角色：将 distill_role 返回的 JSON 保存为可用角色并自动切换。"
        "仅在 distill_role 完成后调用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "role_json": {
                "type": "string",
                "description": "distill_role 返回的完整 JSON 字符串",
            },
            "inject_tools": {
                "type": "boolean",
                "description": "是否自动注入工具和探索能力（默认 true）",
            },
        },
        "required": ["role_json"],
    },
    func=save_distilled_role,
)
