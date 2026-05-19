"""
通用键盘选择器 —— 上下箭头选择，Enter 确认，ESC取消
参考 fzf / gh cli 风格，简洁高亮。
"""

import sys
import tty
import termios
import os
import select


def pick(items, title="", current_idx=0):
    """
    显示可选列表，用户上下键选择，Enter 确认。
    items: [{"label": "显示文本", "hint": "灰色提示(可选)"}, ...]
    返回选中的 index，取消返回 None。
    """
    if not items:
        return None

    selected = min(current_idx, len(items) - 1)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    total_printed = 0

    def _render():
        nonlocal total_printed
        for i, item in enumerate(items):
            label = item.get("label", "")
            hint = item.get("hint", "")
            if i == selected:
                sys.stdout.write(f"  \033[36m▸\033[0m \033[97m{label}\033[0m")
            else:
                sys.stdout.write(f"    \033[90m{label}\033[0m")
            if hint:
                sys.stdout.write(f"  \033[90m{hint}\033[0m")
            sys.stdout.write("\033[K\n")
        status = f"  \033[90m[{selected + 1}/{len(items)}] ↑↓ 选择  Enter 确认  ESC 取消\033[0m\033[K\n"
        sys.stdout.write(status)
        sys.stdout.flush()
        total_printed = len(items) + 1

    def _clear():
        if total_printed > 0:
            sys.stdout.write(f"\033[{total_printed}A")
            for _ in range(total_printed):
                sys.stdout.write("\033[2K\n")
            sys.stdout.write(f"\033[{total_printed}A")
            sys.stdout.flush()

    try:
        tty.setcbreak(fd)

        while select.select([sys.stdin], [], [], 0.01)[0]:
            os.read(fd, 4096)

        if title:
            sys.stdout.write(f"\n  \033[1m{title}\033[0m\n\n")
            sys.stdout.flush()

        _render()

        while True:
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    seq = os.read(fd, 2)
                    if seq == b"[A":
                        selected = (selected - 1) % len(items)
                    elif seq == b"[B":
                        selected = (selected + 1) % len(items)
                    else:
                        while select.select([sys.stdin], [], [], 0.02)[0]:
                            os.read(fd, 1)
                    _clear()
                    _render()
                else:
                    _clear()
                    return None
            elif ch in (b"\r", b"\n"):
                _clear()
                chosen = items[selected]
                sys.stdout.write(f"  \033[36m▸\033[0m {chosen.get('label', '')}\n")
                sys.stdout.flush()
                return selected
            elif ch in (b"q", b"Q", b"\x03"):
                _clear()
                return None
            elif ch == b"k":
                selected = (selected - 1) % len(items)
                _clear()
                _render()
            elif ch == b"j":
                selected = (selected + 1) % len(items)
                _clear()
                _render()
    finally:
        try:
            while select.select([sys.stdin], [], [], 0.05)[0]:
                os.read(fd, 4096)
        except Exception:
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
