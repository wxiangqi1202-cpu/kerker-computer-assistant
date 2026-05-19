"""
技能系统 —— 注册表 + 自动加载

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

from core import config

_registry = {}


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


def get_tool_specs(include_agent_only=False):
    """返回技能描述列表。主模型调用时默认排除 agent_only 技能。"""
    return [
        item["spec"] for item in _registry.values()
        if include_agent_only or not item.get("agent_only")
    ]


def get_all_specs():
    """返回所有技能描述（含 agent_only），供子智能体使用"""
    return [item["spec"] for item in _registry.values()]


def get_skill_names():
    return list(_registry.keys())


def call(name, arguments_json):
    if name not in _registry:
        return f"未知技能: {name}"
    args = json.loads(arguments_json) if arguments_json else {}
    result = _registry[name]["func"](**args)
    return str(result)


async def async_call(name, arguments_json):
    import asyncio
    import inspect
    if name not in _registry:
        return f"未知技能: {name}"
    args = json.loads(arguments_json) if arguments_json else {}
    func = _registry[name]["func"]
    if inspect.iscoroutinefunction(func):
        result = await func(**args)
    else:
        result = await asyncio.to_thread(func, **args)
    return str(result)


def _auto_load():
    package = importlib.import_module("skills")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"skills.{module_name}")


def _load_user_skills():
    user_dir = config.USER_SKILLS_DIR
    if not os.path.isdir(user_dir):
        return
    for filename in sorted(os.listdir(user_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        filepath = os.path.join(user_dir, filename)
        module_name = f"user_skill_{filename[:-3]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            print(f"⚠ 加载用户技能 {filename} 失败: {e}")


_auto_load()
_load_user_skills()
