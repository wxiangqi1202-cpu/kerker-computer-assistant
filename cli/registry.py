"""
命令注册表 —— 装饰器模式，新增命令只需 @command("/xxx", "说明")
"""

_registry = {}


def command(name, description=""):
    """命令注册装饰器"""
    def decorator(func):
        _registry[name] = {"func": func, "desc": description}
        return func
    return decorator


def dispatch(text, ctx):
    """根据输入分发命令，返回 True 表示已处理"""
    parts = text.split(maxsplit=1)
    cmd_name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd_name in _registry:
        _registry[cmd_name]["func"](args, ctx)
        return True

    for registered in _registry:
        if cmd_name.startswith(registered) and registered != cmd_name:
            suffix = cmd_name[len(registered):]
            combined_args = (suffix + " " + args).strip()
            _registry[registered]["func"](combined_args, ctx)
            return True

    return False


def get_all():
    """返回所有命令 {name: description}"""
    return {name: info["desc"] for name, info in _registry.items()}
