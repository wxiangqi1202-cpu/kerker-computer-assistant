"""
工具注册表 —— agents 和 skills 的统一注册中心

职责：
- 工具注册、查询、调用（同步/异步）
- 错误分级重试
- 按角色和上下文过滤工具列表

agents 和 skills 都向此模块注册，消除两者之间的直接导入依赖。
"""

import json
import asyncio
import inspect
import re

from core import config

_registry = {}

_TOOL_MAX_RETRIES = 2
_TOOL_RETRY_DELAY = 0.5

_TOOL_ERROR_PREFIX = "[tool_error] "

_specs_cache = None
_specs_cache_all = None


def _invalidate_specs_cache():
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


def is_tool_error(result: str) -> bool:
    return isinstance(result, str) and result.startswith(_TOOL_ERROR_PREFIX)


def _make_error(msg: str) -> str:
    return f"{_TOOL_ERROR_PREFIX}{msg}"


def register(name, description, parameters, func, agent_only=False):
    """注册一个工具。agent_only=True 的工具不会暴露给主模型，只有子智能体能用。"""
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
    global _specs_cache, _specs_cache_all
    if include_agent_only:
        if _specs_cache_all is None:
            _specs_cache_all = [item["spec"] for item in _registry.values()]
        return _specs_cache_all
    if _specs_cache is None:
        _specs_cache = [
            item["spec"] for item in _registry.values()
            if not item.get("agent_only")
        ]
    return _specs_cache


def get_all_specs():
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


def get_filtered_tool_specs(role_name=None, user_input=None):
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
    _categorized: set = set()
    for _cat_tools in _TOOL_CATEGORIES.values():
        _categorized.update(_cat_tools)
    all_specs = get_tool_specs(include_agent_only=False)
    filtered = [
        spec for spec in all_specs
        if spec["function"]["name"] in allowed_tools
        or spec["function"]["name"] not in _categorized
    ]
    return filtered


def get_skill_names():
    return list(_registry.keys())


def call(name, arguments_json):
    if name not in _registry:
        return _make_error(f"未知技能: {name}")
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as err:
        return _make_error(f"参数解析失败（模型返回了不完整的 JSON）: {err}")
    try:
        result = _registry[name]["func"](**args)
        return str(result)
    except Exception as err:
        return _make_error(f"技能 {name} 执行出错: {err}")


async def async_call(name, arguments_json):
    if name not in _registry:
        return _make_error(f"未知技能: {name}")
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError as err:
        return _make_error(f"参数解析失败（模型返回了不完整的 JSON）: {err}")
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
                return _make_error(f"技能 {name} 执行出错: {err}")
            if attempt < _TOOL_MAX_RETRIES:
                delay = _TOOL_RETRY_DELAY * (2 ** attempt)
                await asyncio.sleep(delay)
            else:
                return _make_error(f"技能 {name} 重试 {_TOOL_MAX_RETRIES} 次后仍失败: {err}")
