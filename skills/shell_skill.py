"""技能：执行 Shell 命令（带安全确认）"""

import re
import subprocess
from skills import register

DANGEROUS_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*(/|~|\.\.|--no-preserve-root)",
    r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f",
    r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r",
    r"\bmkfs\b",
    r"\bdd\s+.*of\s*=\s*/dev/",
    r">\s*/dev/sd",
    r"\bformat\b.*[cC]:",
    r":(){ :\|:& };:",
    r"\bchmod\s+(-[a-zA-Z]*\s+)*777\s+/",
    r"\bchown\s+.*\s+/",
    r"\bkill\s+-9\s+-1",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\s+0",
]

_compiled = [re.compile(p) for p in DANGEROUS_PATTERNS]


def _is_dangerous(command):
    for pattern in _compiled:
        if pattern.search(command):
            return True
    return False


def run_shell(command):
    if _is_dangerous(command):
        print(f"\n  ⚠ 危险命令检测: {command}")
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
