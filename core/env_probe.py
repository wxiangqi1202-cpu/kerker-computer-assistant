"""
环境探测 —— 启动时扫描系统可用的 CLI 工具，供 agent 感知
结果缓存，避免每次对话都重新扫描。
"""

import subprocess
import os
import json

_KERKER_HOME = os.path.expanduser("~/.kerker")
_ENV_CACHE = os.path.join(_KERKER_HOME, "env_cache.json")
_CACHE_MAX_AGE = 3600

_PROBE_COMMANDS = {
    "lark-cli": ("lark-cli", "飞书/Lark CLI，可发消息、管理文档、日历等"),
    "git": ("git --version", "版本控制"),
    "docker": ("docker --version", "容器管理"),
    "python3": ("python3 --version", "Python 运行环境"),
    "node": ("node --version", "Node.js 运行环境"),
    "npm": ("npm --version", "Node 包管理"),
    "pip3": ("pip3 --version", "Python 包管理"),
    "brew": ("brew --version", "macOS 包管理器"),
    "conda": ("conda --version", "Conda 环境管理"),
    "curl": ("curl --version", "HTTP 请求工具"),
    "ssh": ("ssh -V", "远程连接"),
    "npu-smi": ("npu-smi info", "昇腾 NPU 管理工具"),
    "kubectl": ("kubectl version --client --short", "Kubernetes CLI"),
    "ffmpeg": ("ffmpeg -version", "音视频处理"),
    "code": ("code --version", "VS Code CLI"),
}


def _probe_tool(name, cmd):
    """检测单个工具是否可用，返回版本信息或 None"""
    try:
        result = subprocess.run(
            cmd.split(), capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip().split("\n")[0][:80]
            return version
    except Exception:
        pass
    return None


def _scan_path_tools():
    """扫描 PATH 中有意义的非标准工具"""
    extras = []
    path_dirs = os.environ.get("PATH", "").split(":")
    seen = set()
    interesting_prefixes = ("lark", "feishu", "ascend", "npu", "cann")
    for d in path_dirs:
        if not os.path.isdir(d):
            continue
        try:
            for f in os.listdir(d):
                if f in seen:
                    continue
                lower = f.lower()
                if any(lower.startswith(p) for p in interesting_prefixes):
                    full = os.path.join(d, f)
                    if os.access(full, os.X_OK):
                        seen.add(f)
                        extras.append(f)
        except OSError:
            continue
    return extras


def probe_environment(force=False):
    """
    探测系统环境，返回 dict:
      {"tools": {"name": {"version": "...", "desc": "..."}}, "extras": [...]}
    带文件缓存（1小时有效）。
    """
    if not force and os.path.isfile(_ENV_CACHE):
        try:
            with open(_ENV_CACHE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            age = os.path.getmtime(_ENV_CACHE)
            import time
            if time.time() - age < _CACHE_MAX_AGE:
                return cached
        except Exception:
            pass

    tools = {}
    for name, (cmd, desc) in _PROBE_COMMANDS.items():
        version = _probe_tool(name, cmd)
        if version:
            tools[name] = {"version": version, "desc": desc}

    extras = _scan_path_tools()

    result = {"tools": tools, "extras": extras}

    try:
        os.makedirs(_KERKER_HOME, exist_ok=True)
        with open(_ENV_CACHE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return result


def format_env_prompt(env_info=None):
    """将环境信息格式化为 system prompt 文本"""
    if env_info is None:
        env_info = probe_environment()

    tools = env_info.get("tools", {})
    extras = env_info.get("extras", [])

    if not tools and not extras:
        return ""

    lines = ["[当前系统可用工具]"]
    for name, info in tools.items():
        lines.append(f"- {name}: {info['desc']} ({info['version']})")
    if extras:
        lines.append(f"- 其他已安装: {', '.join(extras)}")

    lines.append("")
    lines.append(
        "当用户的需求涉及以上工具时，你可以通过 run_shell 直接调用它们来完成任务。"
        "不要说做不到，先用 run_shell 探索系统上有什么可用的命令和工具。"
    )

    return "\n".join(lines)
