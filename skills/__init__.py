"""
技能系统 —— 注册表 + 自动加载 + 错误分级重试

添加新技能的方式：
1. 在项目 skills/ 目录下新建 .py 文件（内置技能）
2. 在 ~/.kerker/skills/ 目录下新建 .py 文件（用户自定义技能）
两种方式都会被自动加载。
"""

import json
import importlib
import importlib.util
import os
import pkgutil
import asyncio
import inspect

from core import config

_registry = {}

_TOOL_MAX_RETRIES = 2
_TOOL_RETRY_DELAY = 0.5

_specs_cache = None
_specs_cache_all = None


def _invalidate_specs_cache():
    """注册表变更时清除缓存"""
    global _specs_cache, _specs_cache_all
    _specs_cache = None
    _specs_cache_all = None


class ToolError(Exception):
    """工具执行错误基类"""
    pass


class RetryableError(ToolError):
    """可重试错误（网络超时、临时性服务不可用）"""
    pass


class FatalError(ToolError):
    """不可重试错误（权限不足、文件不存在、参数无效）"""
    pass


def _classify_error(error: Exception) -> str:
    """
    错误分级：判断是否可重试。
    返回 'retryable' 或 'fatal'。
    """
    err_str = str(error).lower()

    retryable_patterns = [
        "timeout", "timed out", "connection", "网络",
        "temporarily", "503", "502", "429", "rate limit",
        "reset by peer", "broken pipe", "eof",
    ]
    for pattern in retryable_patterns:
        if pattern in err_str:
            return "retryable"

    fatal_patterns = [
        "permission", "denied", "not found", "不存在",
        "no such file", "invalid", "unauthorized", "403", "401",
        "syntax error", "type error", "name error",
    ]
    for pattern in fatal_patterns:
        if pattern in err_str:
            return "fatal"

    if isinstance(error, (OSError, IOError)):
        return "retryable"
    if isinstance(error, (ValueError, TypeError, KeyError, AttributeError)):
        return "fatal"

    return "fatal"


def register(name, description, parameters, func, agent_only=False):
    """注册一个技能。agent_only=True 的技能不会暴露给主模型，只有子智能体能用。"""
    _registry[name] = {
        "func": func,
        "agent_only": agent_only,
        "spec": {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        }
    }
    _invalidate_specs_cache()


def get_tool_specs(include_agent_only=False):
    """返回技能描述列表（带缓存）。主模型调用时默认排除 agent_only 技能。"""
    global _specs_cache
    if not include_agent_only:
        if _specs_cache is None:
            _specs_cache = [
                item["spec"] for item in _registry.values()
                if not item.get("agent_only")
            ]
        return _specs_cache
    return [item["spec"] for item in _registry.values()]


def get_all_specs():
    """返回所有技能描述（含 agent_only，带缓存），供子智能体使用"""
    global _specs_cache_all
    if _specs_cache_all is None:
        _specs_cache_all = [item["spec"] for item in _registry.values()]
    return _specs_cache_all


_TOOL_CATEGORIES = {
    "core": [
        "web_search", "web_search_and_read", "web_summary",
        "run_shell", "read_file", "write_file",
        "get_current_time",
    ],
    "agent": [
        "agent_planner", "agent_researcher", "agent_code_reviewer",
        "agent_ascend_dev", "agent_ascend_debug",
    ],
    "memory": ["remember", "forget", "recall"],
    "location": ["get_location", "get_weather"],
    "math": ["calculate"],
    "role": ["list_roles", "switch_role", "save_distilled_role", "distill_role"],
    "ascend": ["npu_info", "ascend_build", "ascend_run"],
}

_ROLE_TOOL_PROFILES = {
    "默认":   ["core", "agent", "memory", "location", "math", "role"],
    "代码助手": ["core", "agent", "math", "role"],
    "翻译官":  ["core", "role"],
    "写作助理": ["core", "role"],
    "算子开发": ["core", "agent", "ascend", "role"],
}

_CONTEXT_TOOL_TRIGGERS = {
    "ascend": [r"算子|npu|ascend|tiling|昇腾"],
    "location": [r"天气|位置|weather|location"],
    "memory": [r"记住|忘记|回忆|remember|forget|recall"],
}


def get_filtered_tool_specs(role_name=None, user_input=None, route_action=None):
    """
    按角色和上下文过滤工具列表。

    策略：
    - 所有路由（含 DIRECT）都保留工具能力，LLM 始终可以调用工具
    - 按角色获取基础工具集
    - 按用户输入关键词动态追加相关工具
    """
    import re

    from core import config as cfg
    role = role_name or cfg.CURRENT_ROLE

    profile_categories = _ROLE_TOOL_PROFILES.get(role, _ROLE_TOOL_PROFILES["默认"])
    allowed_tools = set()
    for cat in profile_categories:
        for tool_name in _TOOL_CATEGORIES.get(cat, []):
            allowed_tools.add(tool_name)

    if user_input:
        input_lower = user_input.lower()
        for cat, patterns in _CONTEXT_TOOL_TRIGGERS.items():
            if cat in profile_categories:
                continue
            for pat in patterns:
                if re.search(pat, input_lower, re.IGNORECASE):
                    for tool_name in _TOOL_CATEGORIES.get(cat, []):
                        allowed_tools.add(tool_name)
                    break

    all_specs = get_tool_specs(include_agent_only=False)
    filtered = [
        spec for spec in all_specs
        if spec["function"]["name"] in allowed_tools
    ]

    return filtered


def get_skill_names():
    return list(_registry.keys())


def call(name, arguments_json):
    if name not in _registry:
        return f"未知技能: {name}"
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as err:
        return f"参数解析失败（模型返回了不完整的 JSON）: {err}"
    try:
        result = _registry[name]["func"](**args)
        return str(result)
    except Exception as err:
        return f"技能 {name} 执行出错: {err}"


async def async_call(name, arguments_json):
    """
    异步调用技能，带错误分级重试。
    可重试错误自动重试最多 _TOOL_MAX_RETRIES 次；
    不可重试错误立即返回错误信息。
    """
    if name not in _registry:
        return f"未知技能: {name}"
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as err:
        return f"参数解析失败（模型返回了不完整的 JSON）: {err}"

    func = _registry[name]["func"]
    last_error = None

    for attempt in range(_TOOL_MAX_RETRIES + 1):
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**args)
            else:
                result = await asyncio.to_thread(func, **args)
            return str(result)
        except Exception as err:
            last_error = err
            error_class = _classify_error(err)

            if error_class == "fatal":
                return f"技能 {name} 执行出错: {err}"

            if attempt < _TOOL_MAX_RETRIES:
                delay = _TOOL_RETRY_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
            else:
                return f"技能 {name} 重试 {_TOOL_MAX_RETRIES} 次后仍失败: {err}"

    return f"技能 {name} 执行出错: {last_error}"


def _auto_load():
    package = importlib.import_module("skills")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"skills.{module_name}")


def _check_skill_file_safe(filepath):
    """
    校验用户技能文件安全性（仅 Unix）：
    - 文件必须由当前用户所有
    - 组/其他用户不可写（防止供应链注入）
    Windows 下跳过校验直接通过。
    """
    try:
        import stat as _stat
        st = os.stat(filepath)
        if os.name == "nt":
            return True, ""
        if st.st_uid != os.getuid():
            return False, "文件不属于当前用户"
        if st.st_mode & (_stat.S_IWGRP | _stat.S_IWOTH):
            return False, "组或其他用户可写（存在供应链风险）"
        return True, ""
    except OSError as err:
        return False, str(err)


def _load_user_skills():
    user_dir = config.USER_SKILLS_DIR
    if not os.path.isdir(user_dir):
        return
    for filename in sorted(os.listdir(user_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        filepath = os.path.join(user_dir, filename)
        safe, reason = _check_skill_file_safe(filepath)
        if not safe:
            print(f"⚠ 跳过用户技能 {filename}: {reason}")
            continue
        module_name = f"user_skill_{filename[:-3]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"⚠ 加载用户技能 {filename} 失败: {e}")


_auto_load()
_load_user_skills()
