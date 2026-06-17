"""
技能系统 —— 加载器 + 向后兼容 re-export

添加新技能的方式：
1. 在项目 skills/ 目录下新建 .py 文件（内置技能）
2. 在 ~/.kerker/skills/ 目录下新建 .py 文件（用户自定义技能）
两种方式都会被自动加载。

注册表逻辑位于 core.tool_registry，本模块完整 re-export 所有公开符号，
确保 `from skills import register` 等现有路径兼容。
"""

import importlib
import importlib.util
import os
import pkgutil

from core import config

from core.tool_registry import (
    register,
    get_tool_specs,
    get_all_specs,
    get_filtered_tool_specs,
    get_skill_names,
    call,
    async_call,
    is_tool_error,
    ToolError,
    RetryableError,
    FatalError,
)


def _auto_load():
    package = importlib.import_module("skills")
    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"skills.{module_name}")


def _check_skill_file_safe(filepath):
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
            import sys as _sys
            print(f"⚠ 跳过用户技能 {filename}: {reason}", file=_sys.stderr)
            continue
        module_name = f"user_skill_{filename[:-3]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            import sys as _sys
            print(f"⚠ 加载用户技能 {filename} 失败: {e}", file=_sys.stderr)


_initialized = False


def init():
    """显式初始化：加载内置技能 + 用户技能。由 cli/loop.py 启动时调用。"""
    global _initialized
    if _initialized:
        return
    _initialized = True
    _auto_load()
    _load_user_skills()
