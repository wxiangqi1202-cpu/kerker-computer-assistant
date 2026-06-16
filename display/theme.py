"""
渲染主题系统 —— 集中管理所有终端样式参数
支持 ~/.kerker/theme.json 用户自定义覆盖
"""

import os
import json

_KERKER_HOME = os.path.expanduser("~/.kerker")
_THEME_FILE = os.path.join(_KERKER_HOME, "theme.json")

ESC = "\033["
RESET = f"{ESC}0m"


def _c(code):
    return f"{ESC}{code}m"


BUILTIN_THEMES = {
    "minimal": {
        "name": "minimal",

        "heading1": _c("1;97"),
        "heading2": _c("1;38;5;75"),
        "heading3": _c("1;38;5;252"),
        "heading4": _c("2;37"),

        "bold": _c("1"),
        "italic": _c("3"),
        "bold_italic": _c("1;3"),
        "strikethrough": _c("9"),
        "inline_code": _c("38;5;180"),
        "link": _c("4;38;5;75"),

        "bullet_l0": ("-", _c("38;5;75")),
        "bullet_l1": ("-", _c("38;5;242")),
        "bullet_l2": ("-", _c("38;5;240")),
        "ol_num": _c("38;5;75"),

        "quote_bar": ("▍", _c("38;5;240")),
        "quote_text": _c("3;38;5;250"),

        "hr_char": "─",
        "hr_style": _c("38;5;238"),
        "hr_width": 36,

        "code_lang_style": _c("38;5;242"),
        "code_border": _c("38;5;238"),
        "code_theme": "monokai",
        "code_background": "default",

        "table_header": _c("1;38;5;75"),
        "table_cell": _c("38;5;252"),
        "table_border": _c("38;5;238"),
        "table_sep": "  ",
        "table_pad": 2,

        "paragraph": "",

        "indent": "  ",
        "block_gap": "\n\n",
    },

    "warm": {
        "name": "warm",

        "heading1": _c("1;38;5;216"),
        "heading2": _c("1;38;5;180"),
        "heading3": _c("1;38;5;252"),
        "heading4": _c("2;37"),

        "bold": _c("1"),
        "italic": _c("3"),
        "bold_italic": _c("1;3"),
        "strikethrough": _c("9"),
        "inline_code": _c("38;5;216"),
        "link": _c("4;38;5;180"),

        "bullet_l0": ("-", _c("38;5;216")),
        "bullet_l1": ("-", _c("38;5;242")),
        "bullet_l2": ("-", _c("38;5;240")),
        "ol_num": _c("38;5;216"),

        "quote_bar": ("▍", _c("38;5;240")),
        "quote_text": _c("3;38;5;250"),

        "hr_char": "─",
        "hr_style": _c("38;5;238"),
        "hr_width": 36,

        "code_lang_style": _c("38;5;242"),
        "code_border": _c("38;5;238"),
        "code_theme": "monokai",
        "code_background": "default",

        "table_header": _c("1;38;5;216"),
        "table_cell": _c("38;5;252"),
        "table_border": _c("38;5;238"),
        "table_sep": "  ",
        "table_pad": 2,

        "paragraph": "",

        "indent": "  ",
        "block_gap": "\n\n",
    },

    "plain": {
        "name": "plain",

        "heading1": _c("1"),
        "heading2": _c("1"),
        "heading3": _c("1"),
        "heading4": _c("2"),

        "bold": _c("1"),
        "italic": _c("3"),
        "bold_italic": _c("1;3"),
        "strikethrough": _c("9"),
        "inline_code": _c("7"),
        "link": _c("4"),

        "bullet_l0": ("-", ""),
        "bullet_l1": ("-", ""),
        "bullet_l2": ("-", ""),
        "ol_num": "",

        "quote_bar": ("|", _c("2")),
        "quote_text": _c("3"),

        "hr_char": "-",
        "hr_style": _c("2"),
        "hr_width": 36,

        "code_lang_style": _c("2"),
        "code_border": _c("2"),
        "code_theme": "native",
        "code_background": "default",

        "table_header": _c("1"),
        "table_cell": "",
        "table_border": _c("2"),
        "table_sep": "  ",
        "table_pad": 2,

        "paragraph": "",

        "indent": "  ",
        "block_gap": "\n\n",
    },
}

_current_theme = None


def get_theme():
    global _current_theme
    if _current_theme is not None:
        return _current_theme
    _current_theme = dict(BUILTIN_THEMES["minimal"])
    _load_user_overrides()
    return _current_theme


def set_theme(name):
    global _current_theme
    if name in BUILTIN_THEMES:
        _current_theme = dict(BUILTIN_THEMES[name])
        _save_theme_choice(name)
        return True
    return False


def get_theme_names():
    return list(BUILTIN_THEMES.keys())


def _load_user_overrides():
    global _current_theme
    if not os.path.isfile(_THEME_FILE):
        return
    try:
        with open(_THEME_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        chosen = data.get("theme", "minimal")
        if chosen in BUILTIN_THEMES and _current_theme.get("name") != chosen:
            _current_theme = dict(BUILTIN_THEMES[chosen])
    except json.JSONDecodeError as err:
        import sys
        print(f"[kerker] 主题配置损坏，已使用默认主题: {err}", file=sys.stderr)
    except Exception as err:
        import sys
        print(f"[kerker] 加载主题出错，已使用默认主题: {err}", file=sys.stderr)


def _save_theme_choice(name):
    os.makedirs(_KERKER_HOME, exist_ok=True)
    data = {"theme": name}
    if os.path.isfile(_THEME_FILE):
        try:
            with open(_THEME_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    data["theme"] = name
    with open(_THEME_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
