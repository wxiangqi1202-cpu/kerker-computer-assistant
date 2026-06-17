"""
首次启动引导 —— Setup Wizard
检测到未配置时自动运行，引导用户完成 API Key 和模型配置。
"""

import sys
import getpass
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from core import config
from core.credentials import save_api_key, has_api_key
from cli.picker import pick

_console = Console()

PROVIDERS = [
    {
        "label": "DeepSeek（推荐）",
        "hint": "deepseek.com",
        "base_url": "https://api.deepseek.com",
        "env_hint": "从 platform.deepseek.com 获取 Key",
    },
    {
        "label": "自定义 API（OpenAI 兼容）",
        "hint": "自行填写地址",
        "base_url": "",
        "env_hint": "",
    },
]


def needs_setup():
    """检查是否需要运行引导"""
    return not has_api_key()


def run_setup():
    """运行首次配置引导"""
    width = min(_console.width, 60)

    welcome = Text()
    welcome.append("\n")
    welcome.append("  欢迎使用 KerKer!\n", style="bold cyan")
    welcome.append("  首次启动，需要简单配置。\n", style="dim")
    panel = Panel(welcome, border_style="cyan", width=width, padding=(0, 2))
    _console.print()
    _console.print(panel)
    _console.print()

    _console.print("  [bold]1/3[/bold] [dim]选择 API 服务商[/dim]\n")
    items = [{"label": p["label"], "hint": p["hint"]} for p in PROVIDERS]
    idx = pick(items, current_idx=0)
    if idx is None:
        _console.print("  [dim]已跳过配置，可稍后用 /config 设置[/dim]")
        return False

    provider = PROVIDERS[idx]

    if provider["base_url"]:
        config.BASE_URL = provider["base_url"]
    else:
        _console.print()
        try:
            url = input("  API 地址: ").strip()
            if url:
                config.BASE_URL = url
            else:
                _console.print("  [dim]使用默认地址[/dim]")
        except (EOFError, KeyboardInterrupt):
            _console.print("\n  [dim]已跳过[/dim]")
            return False

    _console.print()
    _console.print("  [bold]2/3[/bold] [dim]输入 API Key[/dim]\n")
    if provider["env_hint"]:
        _console.print(f"  [dim]{provider['env_hint']}[/dim]")

    try:
        key = getpass.getpass("  API Key (输入已隐藏): ").strip()
    except (EOFError, KeyboardInterrupt):
        _console.print("\n  [dim]已跳过[/dim]")
        return False

    if not key:
        _console.print("  [red]未输入 Key，跳过配置[/red]")
        return False

    save_api_key(key)

    _console.print()
    _console.print("  [bold]3/3[/bold] [dim]选择默认模式[/dim]\n")
    mode_items = [
        {"label": "极速模式", "hint": "flash + 关闭思考，日常对话推荐"},
        {"label": "深度模式", "hint": "pro + 深度思考，复杂推理"},
    ]
    mode_idx = pick(mode_items, current_idx=0)
    if mode_idx == 1:
        config.apply_preset("deep")
    else:
        config.apply_preset("fast")

    if not provider["base_url"]:
        for mid, info in config.MODELS.items():
            if info["base_url"] != config.BASE_URL:
                config.MODELS[mid]["base_url"] = config.BASE_URL

    config.save_user_config()

    _console.print()
    _console.print("  [green]✓ 配置完成！[/green]")
    _console.print("  [dim]提示：随时用 /config 修改配置，/fast /deep 切换模式[/dim]")
    _console.print()
    return True
