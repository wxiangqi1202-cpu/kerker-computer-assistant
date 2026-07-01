"""技能：执行 Shell 命令（带安全确认）"""

import re
import subprocess
from skills import register

DANGEROUS_PATTERNS = [
    # ── 文件系统破坏 ─────────────────────────────
    r"\brm\s+(-[a-zA-Z]*\s+)*(/|~|\.\.|--no-preserve-root)",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f",
    r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r",
    r"\brm\s+-[a-zA-Z]*[rf][a-zA-Z]*/",
    r"\bmkfs\b",
    r"\bdd\s+.*of\s*=\s*/dev/",
    r">\s*/dev/sd",
    r"\bformat\b.*[cC]:",
    r"\btruncate\s+-s\s+0\b",
    # ── Fork 炸弹 ────────────────────────────────
    r":\(\)\s*\{",
    # ── 权限与系统控制 ───────────────────────────
    r"\bchmod\s+(-[a-zA-Z]*\s+)*777\s+/",
    r"\bchown\s+.*\s+/",
    r"\bkill\s+-9\s+-1",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+0",
    r"\bsudo\s",             # sudo 后接空白 = 真正调用；which sudo / man sudo 不触发
    r"\bsu\s",               # su 后接空白 = 切换用户（su -、su root 等）；submodule 不触发
    # ── 远程代码执行（管道执行） ──────────────────
    r"(curl|wget|fetch)\b.{0,80}[|]\s*(sh|bash|zsh|python\d*|ruby|node|perl)\b",
    r"\beval\s+.{0,20}(curl|wget|base64)",
]

_compiled = [re.compile(p) for p in DANGEROUS_PATTERNS]


def _is_dangerous(command):
    for pattern in _compiled:
        if pattern.search(command):
            return True
    return False


def _is_interactive():
    """检测当前是否在交互式终端中（非 tool-call 自动循环）"""
    import sys
    return sys.stdin.isatty()


def run_shell(command):
    from core import config
    if not config.ALLOW_SHELL:
        return "Shell 执行已被禁用。如需开启，请运行 /config shell true"

    if _is_dangerous(command):
        try:
            from display.spinner import is_terminal_locked
            if is_terminal_locked():
                return f"安全限制: 检测到危险命令，终端被占用时自动拒绝: {command}"
        except ImportError:
            pass
        if not _is_interactive():
            return f"安全限制: 检测到危险命令，非交互环境下已拒绝执行: {command}"
        import sys as _sys
        print(f"\n  ⚠ 危险命令检测: {command}", file=_sys.stderr)
        try:
            confirm = input("  确认执行? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "用户取消执行"
        if confirm != "y":
            return "用户拒绝执行危险命令"

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        if not output:
            output = "(无输出)"
        output += f"\n[退出码: {result.returncode}]"
        if len(output) > 10000:
            output = output[:10000] + "\n...[输出过长，已截断]"
        return output
    except subprocess.TimeoutExpired:
        return "命令执行超时（30秒限制）"
    except Exception as e:
        return f"执行失败: {e}"


register(
    name="run_shell",
    description="执行一条 shell 命令并返回输出结果，超时30秒",
    parameters={
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 shell 命令",
            }
        },
        "required": ["command"],
    },
    func=run_shell,
)
