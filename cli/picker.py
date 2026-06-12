"""
通用键盘选择器 —— 上下箭头选择，Enter 确认，ESC取消
参考 fzf / gh cli 风格，简洁高亮。
非 Unix 系统退化为数字输入选择。
"""

import sys
import os


def _has_unix_terminal():
    try:
        import tty, termios, select  # noqa: F401
        return hasattr(sys.stdin, "fileno") and os.isatty(sys.stdin.fileno())
    except Exception:
        return False


def _pick_fallback(items, title="", current_idx=0):
    """非 Unix 终端的退化选择器：数字输入"""
    if title:
        print(f"\n  {title}\n")
    for i, item in enumerate(items):
        label = item.get("label", "")
        hint = item.get("hint", "")
        marker = " *" if i == current_idx else ""
        suffix = f"  ({hint})" if hint else ""
        print(f"  [{i + 1}] {label}{suffix}{marker}")
    try:
        choice = input(f"\n  输入编号 (1-{len(items)}, 回车取消): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not choice:
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return idx
    except ValueError:
        pass
    return None


def _pick_unix(items, title="", current_idx=0):
    """Unix 终端的交互式选择器 —— 选择后完全清除，不留残余行"""
    import tty
    import termios
    import select

    selected = min(current_idx, len(items) - 1)
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    total_printed = 0
    title_lines = 0

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
        sys.stdout.flush()
        total_printed = len(items)

    def _clear_all():
        """清除所有输出（包括 title）"""
        count = total_printed + title_lines
        if count > 0:
            sys.stdout.write(f"\033[{count}A")
            for _ in range(count):
                sys.stdout.write("\033[2K\n")
            sys.stdout.write(f"\033[{count}A")
            sys.stdout.flush()

    def _clear_list():
        """只清除列表部分（重新渲染用）"""
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
            sys.stdout.write(f"\n  \033[2m{title}\033[0m\n")
            sys.stdout.flush()
            title_lines = 2

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
                    _clear_list()
                    _render()
                else:
                    _clear_all()
                    return None
            elif ch in (b"\r", b"\n"):
                _clear_all()
                return selected
            elif ch in (b"q", b"Q", b"\x03"):
                _clear_all()
                return None
            elif ch == b"k":
                selected = (selected - 1) % len(items)
                _clear_list()
                _render()
            elif ch == b"j":
                selected = (selected + 1) % len(items)
                _clear_list()
                _render()
    finally:
        try:
            while select.select([sys.stdin], [], [], 0.05)[0]:
                os.read(fd, 4096)
        except Exception:
            pass
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def pick(items, title="", current_idx=0):
    """
    显示可选列表，用户上下键选择，Enter 确认。
    items: [{"label": "显示文本", "hint": "灰色提示(可选)"}, ...]
    返回选中的 index，取消返回 None。
    """
    if not items:
        return None
    if _has_unix_terminal():
        return _pick_unix(items, title, current_idx)
    return _pick_fallback(items, title, current_idx)
