"""
技能：保存蒸馏角色 —— 将 distill_role 的输出保存为可用角色并自动切换
"""

import json
from skills import register
from core import config


def save_distilled_role(role_json, inject_tools=True):
    """
    将蒸馏结果保存为角色并切换。
    role_json: distill_role 返回的 JSON 字符串
    inject_tools: 是否自动注入工具/Agent/探索能力指令
    """
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
    name="save_distilled_role",
    description=(
        "保存蒸馏生成的角色：将 distill_role 返回的 JSON 保存为可用角色并自动切换。"
        "在 distill_role 完成后调用此工具保存结果。"
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
