"""
状态栏样式系统 —— 8 种 context token 用量展示风格
通过 /statusbar 命令切换，持久化到 config.STATUSBAR_STYLE
"""

import sys

_ESC = "\033["
_R   = f"{_ESC}0m"

def _c(code):
    return f"{_ESC}{code}m"

# ── 模块级常量（不在函数内重复分配） ─────────────────────
_SEGS = " ▏▎▍▌▋▊▉█"   # 8 级亮度细线进度字符（索引 0 为空格占位）
_PIE  = ["○", "◔", "◑", "◕", "●"]


def _smooth_color(pct):
    """5 级渐变色：暗灰 → 雾绿 → 柔黄 → 橙 → 红"""
    if pct < 0.30:
        return "90"           # 暗灰 — 使用正常，不需要提示
    if pct < 0.60:
        return "38;5;71"      # 雾绿 — 舒适区
    if pct < 0.75:
        return "38;5;220"     # 柔黄 — 开始注意
    if pct < 0.90:
        return "38;5;208"     # 橙   — 偏高
    return "31"               # 红   — 即将溢出


def _gradient_fill(filled, total, filled_char, empty_char):
    """带位置渐变的进度条：每格颜色由其位置决定（绿→橙→红）"""
    result = ""
    for i in range(total):
        if i < filled:
            result += f"{_c(_smooth_color((i + 1) / total))}{filled_char}{_R}"
        else:
            result += f"{_c('238')}{empty_char}{_R}"
    return result


def _fmt_k(n):
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


# ── 8 种样式渲染函数 ─────────────────────────────────────
# 签名: (pct: float[0,1], used: int, max_ctx: int) -> str

def _style_a(pct, used, max_ctx):
    """A: 纯文字 + 5 级渐变色；接近满载时追加 remaining 提示"""
    col = _smooth_color(pct)
    base = f"{_c(col)}{_fmt_k(used)}/{_fmt_k(max_ctx)} ctx{_R}"
    if pct >= 0.75:
        remaining = max_ctx - used
        base += f" {_c('238')}({_fmt_k(remaining)} left){_R}"
    return base


def _style_b(pct, used, max_ctx):
    """B: 分块进度条，每块颜色随位置渐变 [■■■□□□□□□□] 30%"""
    filled = min(round(pct * 10), 10)
    bar = _gradient_fill(filled, 10, "█", "░")
    col = _smooth_color(pct)
    return f"{_c('238')}[{bar}{_c('238')}]{_R} {_c(col)}{int(pct * 100)}%{_R}"


def _style_c(pct, used, max_ctx):
    """C: 8 级精度细线进度条，逐格渐变 [███▊      ] 3.2k/48k"""
    eighths = min(round(pct * 80), 80)
    full      = eighths // 8
    remainder = eighths % 8
    result = ""
    for i in range(10):
        pos = (i + 1) / 10
        if i < full:
            result += f"{_c(_smooth_color(pos))}█{_R}"
        elif i == full and remainder > 0:
            result += f"{_c(_smooth_color(pos))}{_SEGS[remainder]}{_R}"
        else:
            result += f"{_c('238')} {_R}"
    col = _smooth_color(pct)
    return (
        f"{_c('238')}[{result}{_c('238')}]{_R} "
        f"{_c(col)}{_fmt_k(used)}{_R}{_c('238')}/{_fmt_k(max_ctx)}{_R}"
    )


def _style_d(pct, used, max_ctx):
    """D: 圆点指示器，已填充点逐个渐变色 ●●●●○○○○ 30%"""
    filled = min(round(pct * 8), 8)
    dots = ""
    for i in range(8):
        if i < filled:
            dots += f"{_c(_smooth_color((i + 1) / 8))}●{_R}"
        else:
            dots += f"{_c('238')}○{_R}"
    col = _smooth_color(pct)
    return f"{dots} {_c(col)}{int(pct * 100)}%{_R}"


def _style_e(pct, used, max_ctx):
    """E: 弧形图标 ○◔◑◕● + 渐变色文字（最小噪音）"""
    icon = _PIE[min(int(pct * 4), 4)]
    col  = _smooth_color(pct)
    return f"{_c(col)}{icon} {_fmt_k(used)}/{_fmt_k(max_ctx)}{_R}"


def _style_f(pct, used, max_ctx):
    """F: 背景色块宽度 + 渐变前景文字"""
    filled = min(round(pct * 10), 10)
    if pct < 0.60:
        bg = "100"          # 暗灰背景
    elif pct < 0.85:
        bg = "43"           # 黄背景
    else:
        bg = "41"           # 红背景
    col   = _smooth_color(pct)
    block = f"{_c('30;' + bg)}{' ' * filled}{_R}"
    return f"{block} {_c(col)}{_fmt_k(used)}/{_fmt_k(max_ctx)}{_R}"


def _style_g(pct, used, max_ctx):
    """G: Badge 徽标，4 级色彩方案（暗/绿/黄/红）"""
    if pct < 0.30:
        style = "90"           # 暗灰文字，无背景
        text  = f" ctx {int(pct * 100)}% "
        return f"{_c(style)}{text}{_R}"
    elif pct < 0.60:
        return f"{_c('30;100')} ctx {_c('38;5;71')}■ {int(pct * 100)}%{_c('30;100')} {_R}"
    elif pct < 0.85:
        return f"{_c('30;43')} ctx {int(pct * 100)}% {_R}"
    else:
        return f"{_c('97;41')} ctx {int(pct * 100)}% {_R}"


def _style_h(pct, used, max_ctx):
    """H: 安静模式，正常时完全隐藏，超限才用图标+渐变色弹出"""
    if pct < 0.60:
        return ""
    col  = _smooth_color(pct)
    icon = "▲" if pct < 0.75 else ("⚠" if pct < 0.90 else "✖")
    return f"{_c(col)}{icon} {_fmt_k(used)}/{_fmt_k(max_ctx)}{_R}"


# ── 注册表 ────────────────────────────────────────────────

STYLES = {
    "a": ("纯文字+颜色",  "3.2k/48k ctx，>75% 追加 remaining 提示"),
    "b": ("分块进度条",   "[■■■░░░░░░░] 30%，每块渐变色"),
    "c": ("细线进度条",   "[███▊      ] 3.2k/48k，8 级精度 + 渐变"),
    "d": ("圆点指示器",   "●●●●○○○○ 30%，渐变圆点"),
    "e": ("弧形图标",     "◔ 3.2k/48k，单字符图标 + 渐变色"),
    "f": ("渐变色块",     "背景块宽度随用量变化，3 级背景色"),
    "g": ("Badge 徽标",   "[ ctx 30% ] 4 级色彩 badge"),
    "h": ("安静模式",     "正常隐藏，>60% 弹出 ▲⚠✖ 图标"),
}

_RENDERERS = {
    "a": _style_a, "b": _style_b, "c": _style_c, "d": _style_d,
    "e": _style_e, "f": _style_f, "g": _style_g, "h": _style_h,
}


def render_statusbar(style, model, role, tool_count, messages=None):
    """渲染并输出状态栏。style 为 'a'~'h'，无效值 fallback 到 'a'。"""
    token_part = ""

    if messages:
        from core.tokens import count_message_tokens, get_max_context_tokens
        used    = sum(count_message_tokens(m) for m in messages)
        max_ctx = get_max_context_tokens() or 1
        pct     = min(used / max_ctx, 1.0)   # 修复：clamp 到 [0, 1]

        renderer = _RENDERERS.get(style, _style_a)
        rendered = renderer(pct, used, max_ctx)
        if rendered:
            token_part = f" · {_c('90')}{rendered}{_c('90')}"

    bar = f"  {_c('90')}─── {model} · {role} · {tool_count} tools{token_part} ───{_R}"
    sys.stdout.write(f"{bar}\n")
    sys.stdout.flush()
