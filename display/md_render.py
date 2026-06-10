"""
Markdown 渲染器 v2 —— 极简高级风格
正文/标题/列表/表格: 自研 ANSI 渲染 (基于 theme)
代码块: Rich Syntax (语法高亮)
表格: 纯 ANSI 自研 (无 Rich Table 依赖，彻底解决乱码)
"""

import re
import sys
import unicodedata
from rich.console import Console
from rich.syntax import Syntax

from display.theme import get_theme, RESET

_console = Console()

# ── Markdown 块级解析 ─────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.+)$")
_OL_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.+)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_HR_RE = re.compile(r"^[-*_]{3,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\|?[\s:]*-{2,}[\s:]*(\|[\s:]*-{2,}[\s:]*)*\|?\s*$")


def _parse_blocks(text):
    lines = text.split("\n")
    blocks = []
    idx = 0
    total = len(lines)

    while idx < total:
        line = lines[idx]

        if not line.strip():
            idx += 1
            continue

        if _HR_RE.match(line.strip()):
            blocks.append({"type": "hr"})
            idx += 1
            continue

        heading = _HEADING_RE.match(line.strip())
        if heading:
            level = len(heading.group(1))
            blocks.append({"type": "heading", "level": level, "text": heading.group(2)})
            idx += 1
            continue

        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            code_lines = []
            idx += 1
            while idx < total and not lines[idx].strip().startswith("```"):
                code_lines.append(lines[idx])
                idx += 1
            idx += 1
            blocks.append({"type": "code", "lang": lang, "code": "\n".join(code_lines)})
            continue

        if _is_table_start(lines, idx):
            table_lines = []
            while idx < total and "|" in lines[idx] and lines[idx].strip():
                table_lines.append(lines[idx])
                idx += 1
            blocks.append({"type": "table", "lines": table_lines})
            continue

        if _QUOTE_RE.match(line):
            quote_lines = []
            while idx < total and _QUOTE_RE.match(lines[idx]):
                quote_lines.append(_QUOTE_RE.match(lines[idx]).group(1))
                idx += 1
            blocks.append({"type": "quote", "text": "\n".join(quote_lines)})
            continue

        ul_match = _UL_RE.match(line)
        ol_match = _OL_RE.match(line)
        if ul_match or ol_match:
            list_items = []
            list_type = "ul" if ul_match else "ol"
            while idx < total:
                ul_m = _UL_RE.match(lines[idx])
                ol_m = _OL_RE.match(lines[idx])
                if ul_m and list_type == "ul":
                    indent_len = len(ul_m.group(1))
                    list_items.append({"indent": indent_len, "text": ul_m.group(2)})
                    idx += 1
                elif ol_m and list_type == "ol":
                    indent_len = len(ol_m.group(1))
                    list_items.append({"indent": indent_len, "text": ol_m.group(3), "num": ol_m.group(2)})
                    idx += 1
                elif lines[idx].strip() == "":
                    break
                else:
                    if list_items:
                        list_items[-1]["text"] += " " + lines[idx].strip()
                    idx += 1
            blocks.append({"type": list_type, "items": list_items})
            continue

        para_lines = []
        while idx < total:
            cur = lines[idx]
            if not cur.strip():
                break
            if _HEADING_RE.match(cur.strip()) or cur.strip().startswith("```"):
                break
            if _HR_RE.match(cur.strip()):
                break
            if _is_table_start(lines, idx):
                break
            if _QUOTE_RE.match(cur):
                break
            if _UL_RE.match(cur) or _OL_RE.match(cur):
                break
            para_lines.append(cur)
            idx += 1
        if para_lines:
            blocks.append({"type": "paragraph", "text": " ".join(para_lines)})

    return blocks


def _is_table_start(lines, idx):
    if idx + 1 >= len(lines):
        return False
    if "|" not in lines[idx]:
        return False
    return bool(_TABLE_SEP_RE.match(lines[idx + 1].strip()))


# ── 字符宽度工具 ─────────────────────────────

def _visible_width(text):
    """计算去除 ANSI 转义后的可见字符宽度（考虑中文全角）"""
    plain = re.sub(r"\033\[[0-9;]*m", "", text)
    width = 0
    for ch in plain:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def _pad_to(text, target_width):
    """将 text 用空格填充到 target_width 可见宽度"""
    current = _visible_width(text)
    if current >= target_width:
        return text
    return text + " " * (target_width - current)


# ── 内联格式渲染 ─────────────────────────────

def _render_inline(text):
    t = get_theme()
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", lambda m: f"{t['link']}{m.group(1)}{RESET}", text)
    text = re.sub(r"`([^`]+)`", lambda m: f"{t['inline_code']}{m.group(1)}{RESET}", text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", lambda m: f"{t['bold_italic']}{m.group(1)}{RESET}", text)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: f"{t['bold']}{m.group(1)}{RESET}", text)
    text = re.sub(r"__(.+?)__", lambda m: f"{t['bold']}{m.group(1)}{RESET}", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", lambda m: f"{t['italic']}{m.group(1)}{RESET}", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", lambda m: f"{t['italic']}{m.group(1)}{RESET}", text)
    text = re.sub(r"~~(.+?)~~", lambda m: f"{t['strikethrough']}{m.group(1)}{RESET}", text)
    return text


def _styled(text, style):
    """安全包裹 ANSI 样式，空样式时不添加转义码"""
    if style:
        return f"{style}{text}{RESET}"
    return text


# ── 块级渲染 ─────────────────────────────


def render_blocks(blocks, width=None):
    if width is None:
        width = _console.width
    t = get_theme()
    indent = t["indent"]
    content_width = max(width - len(indent) * 2, 40)
    parts = []

    for i, block in enumerate(blocks):
        btype = block["type"]

        if btype == "heading":
            parts.append(_render_heading(block, indent))

        elif btype == "paragraph":
            text = _render_inline(block["text"])
            parts.append(f"{indent}{text}\n")

        elif btype == "code":
            parts.append(_render_code_block(block, indent, content_width))

        elif btype == "table":
            parts.append(_render_table(block, indent))

        elif btype == "ul":
            parts.append(_render_ul(block, indent))

        elif btype == "ol":
            parts.append(_render_ol(block, indent))

        elif btype == "quote":
            parts.append(_render_quote(block, indent))

        elif btype == "hr":
            hw = t["hr_width"]
            parts.append(f"{indent}{t['hr_style']}{t['hr_char'] * hw}{RESET}\n")

    return t["block_gap"].join(parts)


def _render_heading(block, indent):
    t = get_theme()
    level = block["level"]
    text = _render_inline(block["text"])
    style_key = f"heading{min(level, 4)}"
    style = t[style_key]

    if level == 1:
        hw = min(_visible_width(text) + 4, 50)
        line = f"{t['hr_style']}{t['hr_char'] * hw}{RESET}"
        return f"\n{indent}{style}{text}{RESET}\n{indent}{line}\n"
    elif level == 2:
        return f"\n{indent}{style}{text}{RESET}\n"
    else:
        return f"{indent}{style}{text}{RESET}\n"


def _render_code_block(block, indent, content_width):
    t = get_theme()
    lang = block["lang"] or "text"
    code = block["code"]
    border = t["code_border"]
    lang_style = t["code_lang_style"]

    if lang != "text":
        label = f"{indent}{border}{'─' * 2}{RESET} {lang_style}{lang}{RESET}\n"
    else:
        label = f"{indent}{border}{'─' * 24}{RESET}\n"

    try:
        syntax = Syntax(
            code, lang,
            theme=t["code_theme"],
            background_color=t.get("code_background", "default"),
            line_numbers=False,
            word_wrap=True,
            padding=(0, 1),
        )
        with _console.capture() as capture:
            _console.print(syntax, width=content_width - 4)
        rendered = capture.get().rstrip("\n")
        code_lines = rendered.split("\n")
    except Exception:
        code_lines = code.split("\n")

    buf = label
    for cl in code_lines:
        buf += f"{indent}{border}│{RESET} {cl}\n"
    buf += f"{indent}{border}{'─' * 24}{RESET}\n"
    return buf


def _render_table(block, indent):
    """纯 ANSI 自研表格 —— 无外框，表头加粗+底部横线，对齐精确"""
    t = get_theme()
    raw_lines = block["lines"]
    if len(raw_lines) < 2:
        return indent + "\n".join(raw_lines) + "\n"

    def _parse_row(line):
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [cell.strip() for cell in line.split("|")]

    headers = _parse_row(raw_lines[0])
    col_count = len(headers)
    pad = t["table_pad"]

    alignments = []
    for cell in _parse_row(raw_lines[1]):
        cell = cell.strip()
        if cell.startswith(":") and cell.endswith(":"):
            alignments.append("center")
        elif cell.endswith(":"):
            alignments.append("right")
        else:
            alignments.append("left")
    while len(alignments) < col_count:
        alignments.append("left")

    data_rows = []
    for line in raw_lines[2:]:
        if _TABLE_SEP_RE.match(line.strip()):
            continue
        data_rows.append(_parse_row(line))

    col_widths = [0] * col_count
    for i, h in enumerate(headers):
        col_widths[i] = max(col_widths[i], _visible_width(h))
    for row in data_rows:
        for i in range(min(len(row), col_count)):
            col_widths[i] = max(col_widths[i], _visible_width(row[i]))
    col_widths = [w + pad * 2 for w in col_widths]

    def _align_cell(text, width, align):
        text_w = _visible_width(text)
        space = width - text_w
        if space <= 0:
            return text
        if align == "center":
            left = space // 2
            right = space - left
            return " " * left + text + " " * right
        elif align == "right":
            return " " * space + text
        else:
            return text + " " * space

    border_style = t["table_border"]
    header_style = t["table_header"]
    cell_style = t["table_cell"]

    buf = indent
    for i, h in enumerate(headers):
        styled = _styled(_align_cell(h, col_widths[i], alignments[i]), header_style)
        buf += styled
        if i < col_count - 1:
            buf += f" {_styled('│', border_style)} "
    buf += "\n"

    buf += indent
    for i in range(col_count):
        buf += _styled("─" * col_widths[i], border_style)
        if i < col_count - 1:
            buf += _styled("─┼─", border_style)
    buf += "\n"

    for row in data_rows:
        buf += indent
        for i in range(col_count):
            cell_text = _render_inline(row[i]) if i < len(row) else ""
            styled = _styled(_align_cell(cell_text, col_widths[i], alignments[i]), cell_style)
            buf += styled
            if i < col_count - 1:
                buf += f" {_styled('│', border_style)} "
        buf += "\n"

    return buf


def _render_ul(block, indent):
    t = get_theme()
    buf = ""
    for item in block["items"]:
        depth = item["indent"] // 2
        key = f"bullet_l{min(depth, 2)}"
        bullet_char, bullet_style = t[key]
        prefix = indent + "  " * depth
        text = _render_inline(item["text"])
        if bullet_style:
            buf += f"{prefix}{bullet_style}{bullet_char}{RESET} {text}\n"
        else:
            buf += f"{prefix}{bullet_char} {text}\n"
    return buf


def _render_ol(block, indent):
    t = get_theme()
    buf = ""
    for item in block["items"]:
        depth = item["indent"] // 2
        prefix = indent + "  " * depth
        num = item.get("num", "1")
        text = _render_inline(item["text"])
        num_style = t['ol_num']
        if num_style:
            buf += f"{prefix}{num_style}{num}.{RESET} {text}\n"
        else:
            buf += f"{prefix}{num}. {text}\n"
    return buf


def _render_quote(block, indent):
    t = get_theme()
    bar_char, bar_style = t["quote_bar"]
    text_style = t["quote_text"]
    text = _render_inline(block["text"])
    lines = text.split("\n")
    buf = ""
    for line in lines:
        bar = f"{bar_style}{bar_char}{RESET}" if bar_style else bar_char
        txt = f"{text_style}{line}{RESET}" if text_style else line
        buf += f"{indent}{bar} {txt}\n"
    return buf


# ── 公开 API ─────────────────────────────

def render_markdown(text, width=None):
    blocks = _parse_blocks(text)
    return render_blocks(blocks, width)


def print_markdown(text, width=None):
    output = render_markdown(text, width)
    sys.stdout.write(f"\n{output}\n")
    sys.stdout.flush()
