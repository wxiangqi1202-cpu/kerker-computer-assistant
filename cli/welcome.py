"""
启动页面 —— 三套大气风格（含动画），持久化到 ~/.kerker/config.json
"""

import sys
import os
import json
import time
import math
import random
from core import config

WELCOME_STYLES = ["cyber", "hologram", "typewriter"]
_STYLE_DESC = {
    "cyber": "ASCII Art 赛博风",
    "hologram": "全息投影 (动画)",
    "typewriter": "打字机 (动画)",
}
_DEFAULT_STYLE = "cyber"


def _load_welcome_style():
    cfg_path = config.CONFIG_FILE
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            style = data.get("WELCOME_STYLE", _DEFAULT_STYLE)
            if style in WELCOME_STYLES:
                return style
        except Exception:
            pass
    return _DEFAULT_STYLE


def save_welcome_style(style):
    if style not in WELCOME_STYLES:
        return
    cfg_path = config.CONFIG_FILE
    data = {}
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["WELCOME_STYLE"] = style
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_style_desc():
    return _STYLE_DESC


def show_welcome(style=None):
    import agents as agents_mod
    import skills as skills_mod

    if style is None:
        style = _load_welcome_style()

    agent_count = len(agents_mod.get_all_agents())
    skill_count = len(skills_mod.get_skill_names())

    ctx = {
        "model": config.MODEL,
        "role": config.CURRENT_ROLE,
        "skills": skill_count,
        "agents": agent_count,
        "version": "0.2.0",
    }
    try:
        from cli.loop import VERSION
        ctx["version"] = VERSION
    except Exception:
        try:
            import importlib.metadata
            ctx["version"] = importlib.metadata.version("kerker")
        except Exception:
            pass

    renderer = {
        "cyber": _welcome_cyber,
        "hologram": _welcome_hologram,
        "typewriter": _welcome_typewriter,
    }.get(style, _welcome_cyber)

    renderer(ctx)

    autosave_path = os.path.join(config.HISTORY_DIR, "_autosave.json")
    if os.path.isfile(autosave_path):
        sys.stdout.write("  \033[90m检测到上次对话，输入 /resume 恢复\033[0m\n")
    sys.stdout.write("\n")
    sys.stdout.flush()


_LOGO_LINES = [
    "██╗  ██╗███████╗██████╗ ██╗  ██╗███████╗██████╗ ",
    "██║ ██╔╝██╔════╝██╔══██╗██║ ██╔╝██╔════╝██╔══██╗",
    "█████╔╝ █████╗  ██████╔╝█████╔╝ █████╗  ██████╔╝",
    "██╔═██╗ ██╔══╝  ██╔══██╗██╔═██╗ ██╔══╝  ██╔══██╗",
    "██║  ██╗███████╗██║  ██║██║  ██╗███████╗██║  ██║",
    "╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝",
]
_LOGO_COLORS = [36, 36, 96, 96, 97, 97]

_INFO_TEMPLATE = (
    "  \033[90m模型\033[0m {model}    \033[90m技能\033[0m {skills}    \033[90m智能体\033[0m {agents}\n"
    "  \033[90m角色\033[0m {role}\n\n"
    "  \033[90m/help · /fast · /deep · ESC · /exit\033[0m\n"
)


def _print_final_logo(ctx):
    """输出最终稳定的 logo + 配置信息"""
    for i, line in enumerate(_LOGO_LINES):
        sys.stdout.write(f"  \033[{_LOGO_COLORS[i]}m{line}\033[0m\033[K\n")
    sys.stdout.write(f"  \033[90mComputational Agent Framework  v{ctx['version']}\033[0m\033[K\n\n")
    sys.stdout.write(_INFO_TEMPLATE.format(**ctx))


# ── cyber ──────────────────────────────

def _welcome_cyber(ctx):
    sys.stdout.write("\n")
    _print_final_logo(ctx)


# ── hologram ───────────────────────────

def _welcome_hologram(ctx):
    """全息投影：logo 从干扰噪点中逐行浮现，伴随扫描线从上往下扫"""
    noise_chars = "░▒▓█▄▀■□▪▫"
    total_frames = 18
    line_count = len(_LOGO_LINES)
    total_height = line_count + 1
    scan_colors = [17, 18, 19, 20, 21, 27, 33, 39, 45, 75, 111, 117]

    sys.stdout.write("\n\033[?25l")

    for _ in range(total_height):
        sys.stdout.write("\n")

    for frame in range(total_frames):
        progress = frame / (total_frames - 1)
        scan_y = int(progress * (line_count - 1))

        sys.stdout.write(f"\033[{total_height}A")

        for row in range(line_count):
            original = _LOGO_LINES[row]
            row_progress = max(0.0, min(1.0, (progress * 1.6) - (row / line_count) * 0.6))

            line = "  "
            for ch in original:
                if ch == " ":
                    line += " "
                    continue

                if random.random() < row_progress:
                    if row == scan_y:
                        sc = scan_colors[frame % len(scan_colors)]
                        line += f"\033[1;38;5;{sc}m{ch}\033[0m"
                    else:
                        bright = int(232 + row_progress * 23)
                        line += f"\033[38;5;{bright}m{ch}\033[0m"
                else:
                    nc = random.choice(noise_chars)
                    line += f"\033[38;5;{random.choice([17, 18, 19, 23, 24])}m{nc}\033[0m"

            sys.stdout.write(f"{line}\033[K\n")

        sub_alpha = max(0, int((progress - 0.5) * 2 * 23))
        sub_color = 232 + sub_alpha
        sys.stdout.write(f"  \033[38;5;{sub_color}mComputational Agent Framework  v{ctx['version']}\033[0m\033[K\n")

        sys.stdout.flush()
        time.sleep(0.09)

    sys.stdout.write(f"\033[{total_height}A")
    _print_final_logo(ctx)
    sys.stdout.write("\033[?25h")


# ── typewriter ─────────────────────────

def _welcome_typewriter(ctx):
    """打字机：logo 大字逐行从左到右敲出，速度有微妙的不均匀感"""
    chars_per_frame = 5

    sys.stdout.write("\n\033[?25l")

    for row in range(len(_LOGO_LINES)):
        original = _LOGO_LINES[row]
        color = _LOGO_COLORS[row]
        sys.stdout.write(f"  \033[{color}m")
        pos = 0
        while pos < len(original):
            chunk_end = min(pos + chars_per_frame, len(original))
            sys.stdout.write(original[pos:chunk_end])
            sys.stdout.flush()
            time.sleep(0.012 + random.random() * 0.018)
            pos = chunk_end
        sys.stdout.write("\033[0m\n")

    sys.stdout.write("\n")

    subtitle = f"  Computational Agent Framework  v{ctx['version']}"
    for ch in subtitle:
        sys.stdout.write(f"\033[90m{ch}\033[0m")
        sys.stdout.flush()
        time.sleep(0.018)
    sys.stdout.write("\n\n")

    sys.stdout.write("\033[?25h")
    sys.stdout.write(_INFO_TEMPLATE.format(**ctx))
